"""Tests for the high-level programmatic API."""

from typing import ClassVar

import pytest

import yosoi as ys
from yosoi import api
from yosoi.models.contract import Contract


class ApiContract(Contract):
    title: str = ys.Title()


class ApiContract2(Contract):
    url: str = ys.Url()


def _by_contract(result):
    return {unit.contract: unit.records for unit in result.results}


def _by_url(result):
    return {unit.url: unit.records for unit in result.results}


def _grid(result):
    out = {}
    for unit in result.results:
        out.setdefault(unit.url, {})[unit.contract] = unit.records
    return out


async def test_scrape_accepts_a_list_of_contracts(monkeypatch):
    """scrape() with a LIST runs each contract concurrently and returns a name-keyed dict."""
    FakePipeline.instances.clear()
    monkeypatch.setattr(api, 'Pipeline', FakePipeline)

    result = await api.scrape('https://example.com', [ApiContract, ApiContract2], model=ys.claude_sdk())

    assert _by_contract(result) == {
        'ApiContract': [{'title': 'Example'}],
        'ApiContract2': [{'title': 'Example'}],
    }
    assert len(FakePipeline.instances) == 2
    # All concurrent contracts share ONE write-lock (serialised selector writes), and NO
    # DiscoveryBus is shared across them (sharing would force identical selectors).
    locks = [i.kwargs.get('write_lock') for i in FakePipeline.instances]
    assert all(lock is not None for lock in locks)
    assert len({id(lock) for lock in locks}) == 1
    assert all(i.kwargs.get('bus') is None for i in FakePipeline.instances)


async def test_fetch_builds_request_and_forwards_policy(mocker, monkeypatch):
    from yosoi.operations import FetchResult, FetchUnitResult

    monkeypatch.delenv('YOSOI_PAGE_FETCHER_TYPE', raising=False)
    run = mocker.patch(
        'yosoi.operations.run_fetch',
        mocker.AsyncMock(return_value=FetchResult(results=[FetchUnitResult(url='https://one.test', content='Hello')])),
    )

    result = await ys.fetch(
        'https://one.test',
        view='metadata',
        fetcher_type='simple',
        chars=500,
        include=('headers', 'fingerprint'),
        contracts=[ApiContract],
        policy=ys.Policy(),
        max_concurrency=2,
    )

    request = run.await_args.args[0]
    assert result.results[0].content == 'Hello'
    assert request.urls == ['https://one.test']
    assert request.view == 'metadata'
    assert request.fetcher_type == 'simple'
    assert request.page_size == 500
    assert request.include == ['headers', 'fingerprint']
    assert request.max_concurrency == 2
    assert request.contract_classes()[0] is ApiContract


async def test_search_builds_request_and_forwards_limit(mocker, monkeypatch):
    from yosoi.operations import SearchRequest, SearchResult

    monkeypatch.delenv('YOSOI_SEARCH_BACKEND', raising=False)
    monkeypatch.delenv('YOSOI_SEARCH_REGION', raising=False)
    monkeypatch.delenv('YOSOI_SEARCH_SAFESEARCH', raising=False)
    monkeypatch.delenv('YOSOI_SEARCH_MAX_RESULTS', raising=False)
    monkeypatch.delenv('YOSOI_SEARCH_PAGE', raising=False)
    monkeypatch.delenv('YOSOI_SEARCH_TIMELIMIT', raising=False)
    run = mocker.patch(
        'yosoi.operations.run_search',
        mocker.AsyncMock(return_value=SearchResult(request=SearchRequest(query='widgets'))),
    )

    result = await ys.search(
        'widgets',
        backend='google,bing,brave',
        region='us-en',
        safesearch='off',
        timelimit='w',
        limit=4,
        page=2,
    )

    assert result.request.query == 'widgets'
    request = run.await_args.args[0]
    assert request.backend == 'google,bing,brave'
    assert request.region == 'us-en'
    assert request.safesearch == 'off'
    assert request.timelimit == 'w'
    assert request.max_results == 4
    assert request.page == 2


async def test_search_uses_policy_defaults_and_call_site_overrides(mocker, monkeypatch):
    from yosoi.operations import SearchRequest, SearchResult

    monkeypatch.delenv('YOSOI_SEARCH_BACKEND', raising=False)
    monkeypatch.delenv('YOSOI_SEARCH_REGION', raising=False)
    monkeypatch.delenv('YOSOI_SEARCH_SAFESEARCH', raising=False)
    monkeypatch.delenv('YOSOI_SEARCH_MAX_RESULTS', raising=False)
    monkeypatch.delenv('YOSOI_SEARCH_PAGE', raising=False)
    monkeypatch.delenv('YOSOI_SEARCH_TIMELIMIT', raising=False)
    run = mocker.patch(
        'yosoi.operations.run_search',
        mocker.AsyncMock(return_value=SearchResult(request=SearchRequest(query='widgets'))),
    )

    await ys.search(
        'widgets',
        policy=ys.Policy(
            search=ys.SearchPolicy(
                backend='bing',
                region='wt-wt',
                safesearch='off',
                max_results=7,
                page=3,
                timelimit='m',
            )
        ),
        limit=2,
    )

    request = run.await_args.args[0]
    assert request.backend == 'bing'
    assert request.region == 'wt-wt'
    assert request.safesearch == 'off'
    assert request.timelimit == 'm'
    assert request.max_results == 2
    assert request.page == 3


async def test_search_rejects_conflicting_limit_aliases():
    with pytest.raises(ValueError, match='Pass only one'):
        await ys.search('widgets', max_results=3, limit=4)


async def test_scrape_accepts_a_list_of_urls(monkeypatch):
    """scrape() with a LIST of urls returns a url-keyed dict, one unit per url."""
    FakePipeline.instances.clear()
    monkeypatch.setattr(api, 'Pipeline', FakePipeline)

    result = await api.scrape(['https://a.example', 'https://b.example'], ApiContract, model=ys.claude_sdk())

    assert _by_url(result) == {
        'https://a.example': [{'title': 'Example'}],
        'https://b.example': [{'title': 'Example'}],
    }
    assert len(FakePipeline.instances) == 2


async def test_scrape_threads_opt_in_identity_per_url(monkeypatch):
    """identities={url: BrowserIdentity} is forwarded to that url's Pipeline (opt-in profile)."""
    from yosoi.core.fetcher.identity import BrowserIdentity

    FakePipeline.instances.clear()
    monkeypatch.setattr(api, 'Pipeline', FakePipeline)

    g = BrowserIdentity(id='google', headful=True, profile_dir='/tmp/prof')
    result = await api.scrape(
        ['https://google.test', 'https://bing.test'],
        ApiContract,
        model=ys.claude_sdk(),
        fetcher_type='headless',
        identities={'https://google.test': g},
    )

    assert {unit.url for unit in result.results} == {'https://google.test', 'https://bing.test'}
    by_url = {_scrape_kwargs(i)['url']: i for i in FakePipeline.instances}
    assert by_url['https://google.test'].kwargs['identity'] is g  # google gets the trusted profile
    assert by_url['https://bing.test'].kwargs['identity'] is None  # bing opted out -> plain


async def test_scrape_public_api_constructs_waterfall_with_identity(monkeypatch):
    """ys.scrape(..., fetcher_type='waterfall', identities=...) constructs cleanly."""
    from yosoi.core.fetcher.identity import BrowserIdentity

    FakePipeline.instances.clear()
    monkeypatch.setattr(api, 'Pipeline', FakePipeline)

    identity = BrowserIdentity(id='geo-us', headful=True, profile_dir='/tmp/prof')
    await api.scrape(
        'https://google.test',
        ApiContract,
        model=ys.claude_sdk(),
        fetcher_type='waterfall',
        identities={'https://google.test': identity},
    )

    instance = FakePipeline.instances[0]
    assert instance.kwargs['identity'] is identity
    assert _scrape_kwargs(instance)['fetcher_type'] == 'waterfall'


async def test_scrape_per_url_fetcher_type(monkeypatch):
    """fetcher_type can be a {url: tier} map — each url's pipeline gets its own tier."""
    FakePipeline.instances.clear()
    monkeypatch.setattr(api, 'Pipeline', FakePipeline)

    await api.scrape(
        ['https://google.test', 'https://bing.test'],
        ApiContract,
        model=ys.claude_sdk(),
        fetcher_type={'https://google.test': 'headful', 'https://bing.test': 'headless'},
    )
    by_url = {_scrape_kwargs(i)['url']: i for i in FakePipeline.instances}
    assert by_url['https://google.test'].scrape_kwargs['fetcher_type'] == 'headful'
    assert by_url['https://bing.test'].scrape_kwargs['fetcher_type'] == 'headless'


async def test_scrape_policy_fetcher_not_overwritten_by_default_fetcher(monkeypatch):
    """Default fetcher_type='auto' must not clobber explicit Policy scrape fetcher."""
    FakePipeline.instances.clear()
    monkeypatch.setattr(api, 'Pipeline', FakePipeline)

    await api.scrape(
        'https://x.test',
        ApiContract,
        policy=ys.Policy(model=ys.claude_sdk(), scrape=ys.ScrapePolicy(fetcher_type='simple')),
    )

    assert FakePipeline.instances[0].scrape_kwargs['fetcher_type'] == 'simple'


async def test_scrape_max_concurrency_caps_inflight(monkeypatch):
    """max_concurrency bounds how many (url, contract) units run at once."""
    import asyncio

    inflight = 0
    peak = 0

    class _SlowPipeline(FakePipeline):
        async def scrape(self, url: str, **kwargs: object):
            nonlocal inflight, peak
            inflight += 1
            peak = max(peak, inflight)
            await asyncio.sleep(0.02)
            inflight -= 1
            yield {'title': 'Example'}

    FakePipeline.instances.clear()
    monkeypatch.setattr(api, 'Pipeline', _SlowPipeline)
    urls = [f'https://u{i}.test' for i in range(6)]
    await api.scrape(urls, ApiContract, model=ys.claude_sdk(), max_concurrency=2)
    assert peak <= 2


async def test_scrape_policy_max_concurrency_caps_inflight(monkeypatch):
    """Policy scrape.max_concurrency bounds API fan-out on the policy-first path."""
    import asyncio

    inflight = 0
    peak = 0

    class _SlowPipeline(FakePipeline):
        async def scrape(self, url: str, **kwargs: object):
            nonlocal inflight, peak
            inflight += 1
            peak = max(peak, inflight)
            await asyncio.sleep(0.02)
            inflight -= 1
            yield {'title': 'Example'}

    FakePipeline.instances.clear()
    monkeypatch.setattr(api, 'Pipeline', _SlowPipeline)
    urls = [f'https://u{i}.test' for i in range(6)]
    await api.scrape(
        urls,
        ApiContract,
        policy=ys.Policy(model=ys.claude_sdk(), scrape=ys.ScrapePolicy(max_concurrency=2)),
    )
    assert peak <= 2


async def test_scrape_no_identities_is_default(monkeypatch):
    """Default (no identities) forwards identity=None — behavior unchanged."""
    FakePipeline.instances.clear()
    monkeypatch.setattr(api, 'Pipeline', FakePipeline)
    await api.scrape('https://x.test', ApiContract, model=ys.claude_sdk())
    assert FakePipeline.instances[0].kwargs['identity'] is None


async def test_scrape_defaults_to_auto_fetcher(monkeypatch):
    FakePipeline.instances.clear()
    monkeypatch.setattr(api, 'Pipeline', FakePipeline)

    await api.scrape('https://x.test', ApiContract, model=ys.claude_sdk())

    assert _scrape_kwargs(FakePipeline.instances[0])['fetcher_type'] == 'auto'


async def test_scrape_grid_urls_x_contracts(monkeypatch):
    """scrape([urls], [contracts]) returns {url: {contract_name: records}} — the full grid."""
    FakePipeline.instances.clear()
    monkeypatch.setattr(api, 'Pipeline', FakePipeline)

    result = await api.scrape(
        ['https://a.example', 'https://b.example'], [ApiContract, ApiContract2], model=ys.claude_sdk()
    )

    grid = _grid(result)
    assert set(grid) == {'https://a.example', 'https://b.example'}
    assert set(grid['https://a.example']) == {'ApiContract', 'ApiContract2'}
    assert len(FakePipeline.instances) == 4  # 2 urls x 2 contracts


class FakePipeline:
    """Pipeline test double that captures constructor and scrape arguments."""

    instances: ClassVar[list['FakePipeline']] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.scrape_kwargs: dict[str, object] | None = None
        FakePipeline.instances.append(self)

    async def __aenter__(self) -> 'FakePipeline':
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        return None

    async def scrape(self, url: str, **kwargs: object):
        self.scrape_kwargs = {'url': url, **kwargs}
        yield {'title': 'Example'}


def _scrape_kwargs(instance: FakePipeline) -> dict[str, object]:
    assert instance.scrape_kwargs is not None
    return instance.scrape_kwargs


async def test_scrape_returns_result_envelope_without_default_file_output(monkeypatch):
    """scrape() returns the canonical envelope and disables file output by default."""
    FakePipeline.instances.clear()
    monkeypatch.setattr(api, 'Pipeline', FakePipeline)

    result = await api.scrape('https://example.com', ApiContract, model=ys.opencode())

    assert result.results[0].records == [{'title': 'Example'}]
    instance = FakePipeline.instances[0]
    assert instance.kwargs['contract'] is ApiContract
    assert instance.kwargs['output_format'] == []
    assert instance.kwargs['quiet'] is True
    assert instance.scrape_kwargs is not None
    assert instance.scrape_kwargs['output_format'] == []


async def test_scrape_resolves_contract_name(monkeypatch):
    """scrape() accepts built-in or registered contract names."""
    FakePipeline.instances.clear()
    monkeypatch.setattr(api, 'Pipeline', FakePipeline)

    result = await api.scrape('https://example.com', 'ApiContract', model=ys.claude_sdk())

    assert result.results[0].records == [{'title': 'Example'}]
    assert FakePipeline.instances[0].kwargs['contract'] is ApiContract


async def test_scrape_propagates_exception_and_logs_warning(monkeypatch):
    """scrape() re-raises pipeline exceptions after logging a warning (lines 65-67)."""

    class BrokenPipeline:
        def __init__(self, **kwargs: object) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def scrape(self, url, **kwargs):
            raise ValueError('discovery failed')
            yield  # make it a generator

    monkeypatch.setattr(api, 'Pipeline', BrokenPipeline)

    with pytest.raises(ValueError, match='discovery failed'):
        await api.scrape('https://example.com', ApiContract, model=ys.opencode())


async def test_scrape_many_returns_result_envelope(monkeypatch):
    """scrape_many() returns the canonical envelope."""
    FakePipeline.instances.clear()
    monkeypatch.setattr(api, 'Pipeline', FakePipeline)

    result = await api.scrape_many(['https://a.com', 'https://b.com'], ApiContract, model=ys.opencode())

    assert _by_url(result) == {
        'https://a.com': [{'title': 'Example'}],
        'https://b.com': [{'title': 'Example'}],
    }


async def test_scrape_many_propagates_url_exception(monkeypatch):
    """scrape_many() re-raises exceptions from individual URL scrapes (lines 103-105)."""

    class BrokenPipeline:
        def __init__(self, **kwargs: object) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def scrape(self, url, **kwargs):
            raise RuntimeError('network error')
            yield

    monkeypatch.setattr(api, 'Pipeline', BrokenPipeline)

    with pytest.raises(RuntimeError, match='network error'):
        await api.scrape_many(['https://fail.com'], ApiContract, model=ys.opencode())


def test_scrape_sync_without_event_loop(monkeypatch):
    """scrape_sync() succeeds when there is no running event loop (lines 122-138)."""
    FakePipeline.instances.clear()
    monkeypatch.setattr(api, 'Pipeline', FakePipeline)

    result = api.scrape_sync('https://example.com', ApiContract, model=ys.opencode())

    assert result.results[0].records == [{'title': 'Example'}]


async def test_scrape_sync_raises_inside_event_loop(monkeypatch):
    """scrape_sync() raises RuntimeError when called from an active event loop (lines 139-141)."""
    FakePipeline.instances.clear()
    monkeypatch.setattr(api, 'Pipeline', FakePipeline)

    with pytest.raises(RuntimeError, match='active event loop'):
        api.scrape_sync('https://example.com', ApiContract, model=ys.opencode())


def test_resolve_model_none_calls_auto_config(monkeypatch):
    """_resolve_model(None) delegates to auto_config() with no arguments (line 146)."""
    sentinel = object()
    monkeypatch.setattr(api, 'auto_config', lambda **_kw: sentinel)

    result = api._resolve_model(None)

    assert result is sentinel


def test_resolve_model_string_passes_model_name(monkeypatch):
    """_resolve_model('name') delegates to auto_config(model='name') (line 148)."""
    captured: dict[str, object] = {}

    def fake_auto_config(**kw: object) -> object:
        captured.update(kw)
        return object()

    monkeypatch.setattr(api, 'auto_config', fake_auto_config)

    api._resolve_model('my-model')

    assert captured.get('model') == 'my-model'


async def test_scrape_download_settings_without_allow_stay_default_deny(monkeypatch):
    """Regression: passing download sub-settings without allow_downloads must not enable downloads."""
    FakePipeline.instances.clear()
    monkeypatch.setattr(api, 'Pipeline', FakePipeline)

    await api.scrape(
        'https://example.com',
        ApiContract,
        model=ys.claude_sdk(),
        allowed_download_types=('pdf',),
        max_download_bytes=1_000_000,
    )

    instance = FakePipeline.instances[0]
    assert instance.kwargs['allow_downloads'] is False


async def test_scrape_per_url_fetcher_miss_defers_to_policy(monkeypatch):
    """Regression: a per-URL fetcher map miss ('auto') must not clobber the policy fetcher."""
    FakePipeline.instances.clear()
    monkeypatch.setattr(api, 'Pipeline', FakePipeline)

    await api.scrape(
        ['https://mapped.test', 'https://unmapped.test'],
        ApiContract,
        policy=ys.Policy(model=ys.claude_sdk(), scrape=ys.ScrapePolicy(fetcher_type='simple')),
        fetcher_type={'https://mapped.test': 'headful'},
    )

    by_url = {_scrape_kwargs(i)['url']: i for i in FakePipeline.instances}
    assert by_url['https://mapped.test'].scrape_kwargs['fetcher_type'] == 'headful'
    assert by_url['https://unmapped.test'].scrape_kwargs['fetcher_type'] == 'simple'


def _compat_layer(model=None, **overrides):
    from yosoi.models.selectors import SelectorLevel

    defaults = {
        'force': False,
        'skip_verification': False,
        'fetcher_type': 'auto',
        'selector_level': max(SelectorLevel),
        'save_formats': (),
        'quiet': True,
        'allow_downloads': False,
        'allowed_download_types': (),
        'download_dir': None,
        'max_download_bytes': None,
        'keep_downloads': True,
        'max_concurrency': None,
    }
    defaults.update(overrides)
    return api._compat_policy_layer(model, **defaults)


def test_compat_layer_converts_llm_config_with_runtime_key():
    from yosoi.core.discovery.config import LLMConfig

    policy = _compat_layer(LLMConfig(provider='groq', model_name='llama', api_key='raw-key', temperature=0.2))

    assert policy.model is not None
    assert policy.model.provider == 'groq'
    assert policy.model.temperature == 0.2
    assert policy.model._runtime_api_key == 'raw-key'
    assert 'raw-key' not in policy.model_dump_json()


def test_compat_layer_converts_yosoi_config_force_discovery_and_debug():
    from pathlib import Path

    from yosoi.core.configs import DebugConfig, DiscoveryConfig, YosoiConfig
    from yosoi.core.discovery.config import LLMConfig

    cfg = YosoiConfig(
        llm=LLMConfig(provider='groq', model_name='llama', api_key='raw-key'),
        force=True,
        debug=DebugConfig(save_html=True, html_dir=Path('/tmp/debug-html')),
        discovery=DiscoveryConfig(max_concurrent=7, replay_verify_threshold=0.8),
    )

    policy = _compat_layer(cfg)

    assert policy.model is not None
    assert policy.model._runtime_api_key == 'raw-key'
    assert policy.scrape is not None
    assert policy.scrape.force is True
    assert policy.discovery is not None
    assert policy.discovery.max_concurrent == 7
    assert policy.discovery.replay_verify_threshold == 0.8
    assert policy.output is not None
    assert policy.output.debug_html is True
    assert str(policy.output.debug_html_dir) == '/tmp/debug-html'


def test_compat_layer_maps_output_and_enabled_downloads():
    policy = _compat_layer(
        save_formats=('jsonl', 'csv'),
        quiet=False,
        allow_downloads=True,
        allowed_download_types=('pdf',),
        download_dir='dl',
        max_download_bytes=1024,
        keep_downloads=False,
    )

    assert policy.output is not None
    assert policy.output.formats == ('jsonl', 'csv')
    assert policy.output.quiet is False
    assert policy.download is not None
    assert policy.download.allow is True
    assert policy.download.allowed_types == ('pdf',)
    assert policy.download.directory == 'dl'
    assert policy.download.max_bytes == 1024
    assert policy.download.keep is False


def test_compat_layer_parses_string_model():
    policy = _compat_layer('groq:llama')

    assert policy.model is not None
    assert policy.model.provider == 'groq'
    assert policy.model.model_name == 'llama'


def test_compat_layer_maps_each_scrape_kwarg():
    from yosoi.models.selectors import SelectorLevel

    policy = _compat_layer(
        skip_verification=True,
        fetcher_type='headless',
        selector_level=SelectorLevel.XPATH,
        max_concurrency=2,
    )

    assert policy.scrape == ys.ScrapePolicy(
        skip_verification=True,
        fetcher_type='headless',
        selector_level=SelectorLevel.XPATH,
        max_concurrency=2,
    )


def test_compat_layer_default_yosoi_config_contributes_no_extra_layers():
    from yosoi.core.configs import YosoiConfig
    from yosoi.core.discovery.config import LLMConfig

    cfg = YosoiConfig(llm=LLMConfig(provider='groq', model_name='llama', api_key='k'))

    policy = _compat_layer(cfg)

    assert policy.scrape is None
    assert policy.discovery is None
    assert policy.output is None


def test_compat_layer_downloads_enabled_without_sub_settings():
    policy = _compat_layer(allow_downloads=True)

    assert policy.download == ys.DownloadPolicy(allow=True)


async def test_scrape_many_llm_config_overrides_resolved_spec(monkeypatch):
    """An explicit LLMConfig keeps its exact instance (incl. raw key) on the pipeline."""
    from yosoi.core.discovery.config import LLMConfig

    FakePipeline.instances.clear()
    monkeypatch.setattr(api, 'Pipeline', FakePipeline)
    cfg = LLMConfig(provider='groq', model_name='llama', api_key='raw-key')

    await api.scrape_many(['https://x.test'], ApiContract, model=cfg)

    assert FakePipeline.instances[0].kwargs['llm_config'] is cfg


async def test_scrape_many_yosoi_config_overrides_resolved_spec(monkeypatch):
    from yosoi.core.configs import YosoiConfig
    from yosoi.core.discovery.config import LLMConfig

    FakePipeline.instances.clear()
    monkeypatch.setattr(api, 'Pipeline', FakePipeline)
    cfg = YosoiConfig(llm=LLMConfig(provider='groq', model_name='llama', api_key='raw-key'))

    await api.scrape_many(['https://x.test'], ApiContract, model=cfg)

    assert FakePipeline.instances[0].kwargs['llm_config'] is cfg.llm
