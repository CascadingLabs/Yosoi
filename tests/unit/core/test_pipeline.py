"""Unit tests for Pipeline methods."""

import pytest

import yosoi as ys
from yosoi.core.discovery import DiscoveryOrchestrator, MCPDiscoveryOrchestrator
from yosoi.core.pipeline import Pipeline
from yosoi.models.contract import Contract
from yosoi.models.results import FetchResult, FieldVerificationResult, VerificationResult
from yosoi.storage.tracking import DomainStats
from yosoi.utils.exceptions import BotDetectionError, DownloadError


class SimpleContract(Contract):
    title: str = ys.Title()
    price: float = ys.Price()


def _make_pipeline_stub(mocker, contract=None):
    stub = Pipeline.__new__(Pipeline)
    stub.contract = contract or SimpleContract
    from yosoi.core.verification import SemanticValidator, field_rules_for_contract

    stub.semantic_validator = SemanticValidator()
    stub._field_rules = field_rules_for_contract(stub.contract)
    stub.console = mocker.MagicMock()
    stub.logger = mocker.MagicMock()
    stub.cleaner = mocker.MagicMock()
    stub.discovery = mocker.MagicMock()
    stub.discovery.discover_selectors = mocker.AsyncMock()
    stub._mcp_discovery = None
    stub._force_mcp = False
    stub._discovery_strategy = mocker.MagicMock()
    stub._discovery_strategy.load = mocker.AsyncMock(return_value=None)
    stub._discovery_strategy.save = mocker.AsyncMock()
    stub.verifier = mocker.MagicMock()
    stub.extractor = mocker.MagicMock()
    stub.storage = mocker.MagicMock()
    for m in (
        'save_selectors',
        'load_selectors',
        'load_field_selector',
        'selector_exists',
        'save_content',
        'load_content',
        'content_exists',
        'list_domains',
        'get_summary',
        'load_snapshots',
        'save_snapshots',
        'record_verdict',
        'export_summary',
    ):
        setattr(stub.storage, m, mocker.AsyncMock())
    stub.storage.load_snapshots.return_value = None
    stub.tracker = mocker.MagicMock()
    stub.tracker.record_url = mocker.AsyncMock()
    stub.tracker.get_all_stats = mocker.AsyncMock()
    stub._client = mocker.AsyncMock()
    stub.debug = mocker.MagicMock()
    stub.debug.save_debug_html = mocker.AsyncMock()
    stub.debug.save_debug_selectors = mocker.AsyncMock()
    stub.debug_mode = False
    stub.output_formats = ['json']
    stub.force = False
    stub._allow_downloads = False
    stub._allowed_download_types = ()
    from yosoi.models.selectors import SelectorLevel
    from yosoi.utils.signatures import contract_signature

    stub.selector_level = SelectorLevel.CSS
    stub._contract_sig = contract_signature(stub.contract)
    return stub


def _mock_async_client(mocker, stub, *, raise_on_head=None):
    if raise_on_head is not None:
        stub._client.head.side_effect = raise_on_head
    else:
        stub._client.head.side_effect = None
        stub._client.head.return_value = mocker.MagicMock()
    return stub._client


async def test_normalize_url_already_https(mocker):
    stub = _make_pipeline_stub(mocker)
    assert await Pipeline.normalize_url(stub, 'https://example.com') == 'https://example.com'


async def test_normalize_url_already_http(mocker):
    stub = _make_pipeline_stub(mocker)
    assert await Pipeline.normalize_url(stub, 'http://example.com') == 'http://example.com'


async def test_normalize_url_adds_https_on_success(mocker):
    stub = _make_pipeline_stub(mocker)
    _mock_async_client(mocker, stub)
    result = await Pipeline.normalize_url(stub, 'example.com')
    assert result == 'https://example.com'


async def test_normalize_url_falls_back_to_http_on_error(mocker):
    import httpx

    stub = _make_pipeline_stub(mocker)
    _mock_async_client(mocker, stub, raise_on_head=httpx.HTTPError('fail'))
    result = await Pipeline.normalize_url(stub, 'example.com')
    assert result == 'http://example.com'


def test_extract_domain_strips_www(mocker):
    stub = _make_pipeline_stub(mocker)
    assert Pipeline._extract_domain(stub, 'https://www.example.com/page') == 'example.com'


def test_extract_domain_no_www(mocker):
    stub = _make_pipeline_stub(mocker)
    assert Pipeline._extract_domain(stub, 'https://shop.example.com/path') == 'shop.example.com'


def test_extract_domain_preserves_subdomain(mocker):
    stub = _make_pipeline_stub(mocker)
    result = Pipeline._extract_domain(stub, 'https://blog.example.com')
    assert result == 'blog.example.com'


def test_pipeline_accepts_model_string(mocker):
    mocker.patch('yosoi.storage.persistence.init_yosoi')
    mocker.patch('yosoi.storage.tracking.get_tracking_path', return_value='/tmp/tracking.json')
    mocker.patch('yosoi.utils.files.is_initialized', return_value=True)
    mocker.patch('yosoi.utils.logging.setup_local_logging', return_value='/tmp/test.log')
    mocker.patch('yosoi.core.discovery.field_agent.Agent')
    mocker.patch('yosoi.core.discovery.field_agent.create_model')
    p = Pipeline(llm_config='groq:llama-3.3-70b-versatile', contract=SimpleContract)
    assert p.discovery is not None


def test_pipeline_uses_static_primary_with_lazy_mcp(mocker, monkeypatch):
    monkeypatch.setenv('GROQ_KEY', 'test-key')
    mocker.patch('yosoi.storage.persistence.init_yosoi')
    mocker.patch('yosoi.storage.discovery_strategy.init_yosoi')
    mocker.patch('yosoi.storage.tracking.get_tracking_path', return_value='/tmp/tracking.json')
    mocker.patch('yosoi.utils.files.is_initialized', return_value=True)
    mocker.patch('yosoi.utils.logging.setup_local_logging', return_value='/tmp/test.log')
    p = Pipeline(llm_config='groq:llama-3.3-70b-versatile', contract=SimpleContract)
    assert isinstance(p.discovery, DiscoveryOrchestrator)
    assert p._mcp_discovery is None
    assert p._force_mcp is False


def test_pipeline_force_mcp_env_override(mocker, monkeypatch):
    mocker.patch('yosoi.storage.persistence.init_yosoi')
    mocker.patch('yosoi.storage.discovery_strategy.init_yosoi')
    mocker.patch('yosoi.storage.tracking.get_tracking_path', return_value='/tmp/tracking.json')
    mocker.patch('yosoi.utils.files.is_initialized', return_value=True)
    mocker.patch('yosoi.utils.logging.setup_local_logging', return_value='/tmp/test.log')
    monkeypatch.setenv('GROQ_KEY', 'test-key')
    monkeypatch.setenv('YOSOI_DISCOVERY_MODE', 'mcp')
    mocker.patch('yosoi.core.discovery.mcp_orchestrator.MCPDiscoveryAgent')
    p = Pipeline(llm_config='groq:llama-3.3-70b-versatile', contract=SimpleContract)
    assert p._force_mcp is True
    assert isinstance(p._ensure_mcp_discovery(), MCPDiscoveryOrchestrator)


class TestEscalationSignal:
    def test_required_discovery_fields(self, mocker):
        stub = _make_pipeline_stub(mocker)
        assert stub._required_discovery_fields() == {'title', 'price'}

    def test_unsatisfied_required_flags_missing(self, mocker):
        stub = _make_pipeline_stub(mocker)
        assert stub._unsatisfied_required({'title': 'Book'}) == {'price'}

    def test_unsatisfied_required_empty_when_all_present(self, mocker):
        stub = _make_pipeline_stub(mocker)
        assert stub._unsatisfied_required({'title': 'Book', 'price': '9.99'}) == set()

    def test_unsatisfied_required_ignores_overrides(self, mocker):
        stub = _make_pipeline_stub(mocker)
        mocker.patch.object(stub.contract, 'get_selector_overrides', return_value={'price': {'primary': '.p'}})
        assert stub._unsatisfied_required({'title': 'Book'}) == set()


class TestEscalation:
    async def test_escalate_merges_and_reports_improvement(self, mocker):
        stub = _make_pipeline_stub(mocker)
        mcp = mocker.MagicMock()
        mcp.discover_selectors = mocker.AsyncMock(return_value={'price': {'primary': '.price'}})
        mocker.patch.object(stub, '_ensure_mcp_discovery', return_value=mcp)
        mocker.patch.object(stub, '_resolve_root', return_value=None)
        mocker.patch.object(stub, '_verify', return_value={'price': {'primary': '.price'}})
        mocker.patch.object(stub, '_extract', return_value={'title': 'Book', 'price': '9.99'})
        verified = {'title': {'primary': 'h1'}}
        extracted, new_verified, _root, improved = await stub._escalate_to_mcp(
            'https://x.com', '<html/>', '<html/>', verified, None, None, {'title': 'Book'}, {'price'}
        )
        assert new_verified['price'] == {'primary': '.price'}
        assert extracted == {'title': 'Book', 'price': '9.99'}
        assert improved is True

    async def test_escalate_no_improvement_when_field_still_unmet(self, mocker):
        stub = _make_pipeline_stub(mocker)
        mcp = mocker.MagicMock()
        mcp.discover_selectors = mocker.AsyncMock(return_value={'price': {'primary': '.price'}})
        mocker.patch.object(stub, '_ensure_mcp_discovery', return_value=mcp)
        mocker.patch.object(stub, '_resolve_root', return_value=None)
        mocker.patch.object(stub, '_verify', return_value={})
        mocker.patch.object(stub, '_extract', return_value={'title': 'Book'})
        _extracted, _verified, _root, improved = await stub._escalate_to_mcp(
            'https://x.com',
            '<html/>',
            '<html/>',
            {'title': {'primary': 'h1'}},
            None,
            None,
            {'title': 'Book'},
            {'price'},
        )
        assert improved is False

    async def test_escalate_survives_mcp_failure(self, mocker):
        stub = _make_pipeline_stub(mocker)
        mcp = mocker.MagicMock()
        mcp.discover_selectors = mocker.AsyncMock(side_effect=RuntimeError('boom'))
        mocker.patch.object(stub, '_ensure_mcp_discovery', return_value=mcp)
        mocker.patch('yosoi.core.pipeline.base.observability')
        verified = {'title': {'primary': 'h1'}}
        extracted, new_verified, root, improved = await stub._escalate_to_mcp(
            'https://x.com', '<html/>', '<html/>', verified, None, None, {'title': 'Book'}, {'price'}
        )
        assert new_verified == verified
        assert extracted == {'title': 'Book'}
        assert root is None
        assert improved is False


def test_create_fetcher_valid_type(mocker):
    stub = _make_pipeline_stub(mocker)
    mock_fetcher = mocker.MagicMock()
    mocker.patch('yosoi.core.pipeline.base.create_fetcher', return_value=mock_fetcher)
    result = Pipeline._create_fetcher(stub, 'simple')
    assert result is mock_fetcher


def test_create_fetcher_invalid_type_returns_none(mocker):
    stub = _make_pipeline_stub(mocker)
    mocker.patch('yosoi.core.pipeline.base.create_fetcher', side_effect=ValueError('bad'))
    result = Pipeline._create_fetcher(stub, 'nonexistent')
    assert result is None


def test_create_auto_fetcher_passes_console_and_a3node(mocker):
    stub = _make_pipeline_stub(mocker)
    stub._experimental_a3node = False
    create_fetcher = mocker.patch('yosoi.core.pipeline.base.create_fetcher', return_value=mocker.MagicMock())
    Pipeline._create_fetcher(stub, 'auto', console=stub.console)
    create_fetcher.assert_called_once_with(
        'auto', console=stub.console, experimental_a3node=False, allow_downloads=False, download_dir=None
    )


async def test_record_fetch_strategy_selector_level_uses_highest_verified_level(mocker):
    from yosoi.core.fetcher.waterfall import JSFetcher

    stub = _make_pipeline_stub(mocker)
    stub._last_level_distribution = {'css': 2, 'xpath': 1}
    fetcher = mocker.Mock(spec=JSFetcher)
    await Pipeline._record_fetch_strategy_selector_level(stub, fetcher, 'qscrape.dev')
    fetcher.update_selector_level.assert_called_once_with('qscrape.dev', 'xpath')


async def test_clean_returns_cleaned_html(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.cleaner.clean_html.return_value = '<html><body>Clean</body></html>'
    result_obj = FetchResult(url='https://x.com', html='<html>Dirty</html>')
    result = await Pipeline._clean(stub, 'https://x.com', result_obj)
    assert result == '<html><body>Clean</body></html>'
    stub.debug.save_debug_html.assert_called_once()


async def test_clean_returns_none_when_cleaner_returns_empty(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.cleaner.clean_html.return_value = ''
    result_obj = FetchResult(url='https://x.com', html='<html>x</html>')
    result = await Pipeline._clean(stub, 'https://x.com', result_obj)
    assert result is None


def _make_verification_result(success: bool, fields: list[str]):
    results = {}
    for f in fields:
        results[f] = FieldVerificationResult(
            field_name=f,
            status='verified' if success else 'failed',
            working_level='primary' if success else None,
            selector='.cls' if success else None,
        )
    return VerificationResult(
        total_fields=len(fields),
        verified_count=len(fields) if success else 0,
        results=results,
    )


def test_verify_skip_verification_returns_selectors_unchanged(mocker):
    stub = _make_pipeline_stub(mocker)
    selectors = {'title': {'primary': 'h1'}}
    result = Pipeline._verify(stub, 'https://x.com', '<html/>', selectors, skip_verification=True)
    assert result is selectors
    stub.verifier.verify.assert_not_called()


def test_verify_success_returns_verified_selectors(mocker):
    stub = _make_pipeline_stub(mocker)
    selectors = {'title': {'primary': 'h1'}, 'price': {'primary': '.price'}}
    vr = _make_verification_result(True, ['title', 'price'])
    stub.verifier.verify.return_value = vr
    result = Pipeline._verify(stub, 'https://x.com', '<html/>', selectors, skip_verification=False)
    assert result is not None
    assert 'title' in result
    assert 'price' in result


def test_verify_all_fail_returns_none(mocker):
    stub = _make_pipeline_stub(mocker)
    selectors = {'title': {'primary': 'h1'}}
    vr = _make_verification_result(False, ['title'])
    stub.verifier.verify.return_value = vr
    result = Pipeline._verify(stub, 'https://x.com', '<html/>', selectors, skip_verification=False)
    assert result is None


def test_verify_partial_failure_prints_partial_warning(mocker):
    stub = _make_pipeline_stub(mocker)
    results = {
        'title': FieldVerificationResult(field_name='title', status='verified', working_level='primary', selector='h1'),
        'price': FieldVerificationResult(field_name='price', status='failed', working_level=None, selector=None),
    }
    vr = VerificationResult(total_fields=2, verified_count=1, results=results)
    stub.verifier.verify.return_value = vr
    selectors = {'title': {'primary': 'h1'}, 'price': {'primary': '.p'}}
    Pipeline._verify(stub, 'https://x.com', '<html/>', selectors, skip_verification=False)
    stub.console.print.assert_called()


def test_extract_returns_content_dict(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.extractor.extract_content_with_html.return_value = {'title': 'Book'}
    result = Pipeline._extract(stub, 'https://x.com', '<html/>', {'title': {'primary': 'h1'}})
    assert result == {'title': 'Book'}


def test_extract_returns_none_when_extractor_fails(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.extractor.extract_content_with_html.return_value = None
    result = Pipeline._extract(stub, 'https://x.com', '<html/>', {'title': {'primary': 'h1'}})
    assert result is None


def test_pipeline_validate_with_contract_success(mocker):
    stub = _make_pipeline_stub(mocker, SimpleContract)
    result = Pipeline._validate_with_contract(stub, {'title': '  Book  ', 'price': '£9.99'})
    assert result['title'] == 'Book'
    assert result['price'] == 9.99


def test_pipeline_validate_with_contract_fallback_on_error(mocker):
    # _validate_with_contract uses pipeline.utils' logger, not stub.logger.
    # The warning is emitted; we verify by checking the return value (raw fallback).
    stub = _make_pipeline_stub(mocker, SimpleContract)
    raw = {'price': 'not-a-number'}
    result = Pipeline._validate_with_contract(stub, raw)
    assert result is raw
    # NOTE: do NOT assert stub.logger.warning — that's the stub's mock logger,
    # not pipeline.utils.logger which is what _validate_with_contract uses.


def test_validate_with_contract_injects_source_url(mocker):
    class UrlContract(Contract):
        title: str = ys.Title()

    stub = _make_pipeline_stub(mocker, UrlContract)
    result = Pipeline._validate_with_contract(stub, {'title': 'hello'}, url='https://example.com')
    assert result['title'] == 'hello'


async def test_save_and_track_saves_selectors_and_content(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.tracker.record_url.return_value = DomainStats(llm_calls=1, url_count=1)
    await Pipeline._save_and_track(
        stub,
        url='https://x.com',
        domain='x.com',
        verified={'title': {'primary': 'h1'}},
        extracted={'title': 'Book'},
        used_llm=True,
        output_format=['json'],
    )
    stub.storage.save_selectors.assert_called_once()
    stub.storage.save_content.assert_called_once()
    stub.tracker.record_url.assert_called_once_with(
        'https://x.com', used_llm=True, level_distribution=None, elapsed=None
    )


async def test_save_and_track_skips_content_when_none(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.tracker.record_url.return_value = DomainStats(llm_calls=1, url_count=1)
    await Pipeline._save_and_track(
        stub,
        url='https://x.com',
        domain='x.com',
        verified={'title': {'primary': 'h1'}},
        extracted=None,
        used_llm=True,
        output_format=['json'],
    )
    stub.storage.save_selectors.assert_called_once()
    stub.storage.save_content.assert_not_called()


async def test_save_and_track_passes_elapsed_to_record_url(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.tracker.record_url.return_value = DomainStats(llm_calls=1, url_count=1)
    await Pipeline._save_and_track(
        stub,
        url='https://x.com',
        domain='x.com',
        verified={'title': {'primary': 'h1'}},
        extracted={'title': 'Book'},
        used_llm=True,
        output_format=['json'],
        elapsed=3.5,
    )
    stub.tracker.record_url.assert_called_once_with(
        'https://x.com', used_llm=True, level_distribution=None, elapsed=3.5
    )


async def test_track_cached_success_calls_record_url(mocker):
    stub = _make_pipeline_stub(mocker)
    stub._url_start = 100.0
    mocker.patch('yosoi.core.pipeline.base.time')
    mocker.patch('yosoi.core.pipeline.base.time.monotonic', return_value=102.5)
    stub.tracker.record_url.return_value = DomainStats(llm_calls=0, url_count=3)
    await Pipeline._track_cached_success(stub, 'https://x.com', 'x.com')
    call_args = stub.tracker.record_url.call_args
    assert call_args[0] == ('https://x.com',)
    assert call_args[1]['used_llm'] is False
    assert call_args[1]['level_distribution'] is None
    assert call_args[1]['elapsed'] is not None


def test_print_tracking_stats_shows_efficiency(mocker):
    stub = _make_pipeline_stub(mocker)
    Pipeline._print_tracking_stats(stub, 'example.com', DomainStats(llm_calls=2, url_count=10))
    calls = [str(c) for c in stub.console.print.call_args_list]
    joined = ' '.join(calls)
    assert 'llm_calls' in joined.lower() or '2' in joined or 'LLM' in joined


def test_print_tracking_stats_no_efficiency_when_zero_llm(mocker):
    stub = _make_pipeline_stub(mocker)
    Pipeline._print_tracking_stats(stub, 'example.com', DomainStats(llm_calls=0, url_count=5))
    stub.console.print.assert_called()


def test_handle_bot_detection_prints_info(mocker):
    stub = _make_pipeline_stub(mocker)
    err = BotDetectionError(url='https://x.com', status_code=403, indicators=['captcha'])
    Pipeline._handle_bot_detection(stub, err, attempt=1, max_retries=2)
    stub.console.print.assert_called()


def test_handle_bot_detection_prints_abort_when_exhausted(mocker):
    stub = _make_pipeline_stub(mocker)
    err = BotDetectionError(url='https://x.com', status_code=403, indicators=['cloudflare'])
    Pipeline._handle_bot_detection(stub, err, attempt=2, max_retries=2)
    calls = [str(c) for c in stub.console.print.call_args_list]
    assert any('ABORTING' in c or 'voidcrawl' in c.lower() for c in calls)


async def test_extract_with_cached_fail_open_on_fetch_failure(mocker):
    stub = _make_pipeline_stub(mocker)
    mock_fetcher = mocker.MagicMock()
    mock_fetcher.fetch = mocker.AsyncMock(return_value=FetchResult(url='https://x.com', html=None, is_blocked=True))
    items, cache_valid = await Pipeline._extract_with_cached(
        stub, 'https://x.com', mock_fetcher, {'title': {'primary': 'h1'}}, False
    )
    assert cache_valid is True
    assert items is None


async def test_extract_with_cached_returns_invalid_when_verification_fails(mocker):
    stub = _make_pipeline_stub(mocker)
    mock_fetcher = mocker.MagicMock()
    mock_fetcher.fetch = mocker.AsyncMock(return_value=FetchResult(url='https://x.com', html='<html/>'))
    stub.cleaner.clean_html.return_value = '<html/>'
    vr = _make_verification_result(False, ['title'])
    stub.verifier.verify.return_value = vr
    items, cache_valid = await Pipeline._extract_with_cached(
        stub, 'https://x.com', mock_fetcher, {'title': {'primary': 'h1'}}, False
    )
    assert cache_valid is False
    assert items is None


async def test_extract_with_cached_skips_verification_when_flag_set(mocker):
    stub = _make_pipeline_stub(mocker)
    mock_fetcher = mocker.MagicMock()
    mock_fetcher.fetch = mocker.AsyncMock(return_value=FetchResult(url='https://x.com', html='<html/>'))
    stub.cleaner.clean_html.return_value = '<html/>'
    stub.extractor.extract_content_with_html.return_value = None
    _items, cache_valid = await Pipeline._extract_with_cached(
        stub, 'https://x.com', mock_fetcher, {'title': {'primary': 'h1'}}, True
    )
    stub.verifier.verify.assert_not_called()
    assert cache_valid is True


async def test_stale_container_triggers_rediscovery(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.cleaner.clean_html.return_value = '<html><body><h1>Title</h1></body></html>'
    stub.verifier._test_selector = mocker.MagicMock(return_value=(False, 'no_elements_found'))
    mock_fetcher = mocker.MagicMock()
    mock_fetcher.fetch = mocker.AsyncMock(
        return_value=FetchResult(url='https://x.com', html='<html><body><h1>Title</h1></body></html>')
    )
    mocker.patch.object(
        stub, '_resolve_root', return_value={'primary': {'type': 'css', 'value': 'article.product_pod'}}
    )
    items, cache_valid = await Pipeline._extract_with_cached(
        stub, 'https://x.com', mock_fetcher, {'title': {'primary': 'h1'}}, False
    )
    assert cache_valid is False
    assert items is None


# ---------------------------------------------------------------------------
# _fetch — patch pipeline.extraction.get_async_retryer (method lives there)
# ---------------------------------------------------------------------------


async def test_fetch_returns_result_on_success(mocker):
    stub = _make_pipeline_stub(mocker)
    fetch_result = FetchResult(url='https://x.com', html='<html/>', status_code=200)
    mock_fetcher = mocker.MagicMock()
    mock_fetcher.fetch = mocker.AsyncMock(return_value=fetch_result)
    from tenacity import AsyncRetrying, stop_after_attempt

    mocker.patch(
        'yosoi.core.pipeline.extraction.get_async_retryer',
        return_value=AsyncRetrying(stop=stop_after_attempt(1), reraise=True),
    )
    result = await Pipeline._fetch(stub, 'https://x.com', mock_fetcher, max_retries=1)
    assert result is fetch_result


async def test_fetch_returns_none_when_all_retries_fail(mocker):
    stub = _make_pipeline_stub(mocker)
    mock_fetcher = mocker.MagicMock()
    mock_fetcher.fetch = mocker.AsyncMock(
        return_value=FetchResult(url='https://x.com', html=None, is_blocked=True, block_reason='blocked')
    )
    from tenacity import AsyncRetrying, stop_after_attempt, wait_none

    mocker.patch(
        'yosoi.core.pipeline.extraction.get_async_retryer',
        return_value=AsyncRetrying(stop=stop_after_attempt(1), wait=wait_none(), reraise=False),
    )
    result = await Pipeline._fetch(stub, 'https://x.com', mock_fetcher, max_retries=1)
    assert result is None


# ---------------------------------------------------------------------------
# _discover — patch pipeline.discovery.get_async_retryer (method lives there)
# ---------------------------------------------------------------------------


async def test_discover_returns_overrides_when_no_fields_need_discovery(mocker):
    stub = _make_pipeline_stub(mocker)

    class OverrideContract(Contract):
        title: str = ys.Field(selector='.title')  # type: ignore[assignment]

    stub.contract = OverrideContract
    stub.contract.get_selector_overrides = mocker.MagicMock(return_value={'title': {'primary': '.title'}})
    stub.contract.field_descriptions = mocker.MagicMock(return_value={})
    stub.debug.save_debug_selectors = mocker.AsyncMock()
    selectors, used_llm = await Pipeline._discover(stub, 'https://x.com', '<html/>', max_retries=1)
    assert selectors == {'title': {'primary': '.title'}}
    assert used_llm is False
    stub.discovery.discover_selectors.assert_not_called()


async def test_discover_returns_selectors_on_ai_success(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.contract.get_selector_overrides = mocker.MagicMock(return_value={})
    stub.contract.field_descriptions = mocker.MagicMock(return_value={'title': 'The title'})
    stub.discovery.discover_selectors = mocker.AsyncMock(return_value={'title': {'primary': 'h1'}})
    stub.debug.save_debug_selectors = mocker.AsyncMock()
    from tenacity import AsyncRetrying, stop_after_attempt, wait_none

    mocker.patch(
        'yosoi.core.pipeline.discovery.get_async_retryer',
        return_value=AsyncRetrying(stop=stop_after_attempt(1), wait=wait_none(), reraise=False),
    )
    selectors, used_llm = await Pipeline._discover(stub, 'https://x.com', '<html/>', max_retries=1)
    assert selectors == {'title': {'primary': 'h1'}}
    assert used_llm is True


async def test_discover_returns_none_when_all_ai_attempts_fail(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.contract.get_selector_overrides = mocker.MagicMock(return_value={})
    stub.contract.field_descriptions = mocker.MagicMock(return_value={'title': 'The title'})
    stub.discovery.discover_selectors = mocker.AsyncMock(return_value=None)
    from tenacity import AsyncRetrying, stop_after_attempt, wait_none

    mocker.patch(
        'yosoi.core.pipeline.discovery.get_async_retryer',
        return_value=AsyncRetrying(stop=stop_after_attempt(1), wait=wait_none(), reraise=False),
    )
    selectors, used_llm = await Pipeline._discover(stub, 'https://x.com', '<html/>', max_retries=1)
    assert selectors is None
    assert used_llm is False


async def test_discover_succeeds_at_css(mocker):
    stub = _make_pipeline_stub(mocker)
    mocker.patch.object(Pipeline, '_discover', return_value=({'title': {'primary': 'h1'}}, True))
    selectors, used_llm = await Pipeline._discover(stub, 'https://x.com', '<html/>')
    assert selectors == {'title': {'primary': 'h1'}}
    assert used_llm is True
    Pipeline._discover.assert_called_once()


async def test_discover_delegates_to_discover(mocker):
    from yosoi.models.selectors import SelectorLevel

    stub = _make_pipeline_stub(mocker)
    stub.selector_level = SelectorLevel.XPATH
    mocker.patch.object(Pipeline, '_discover', return_value=({'title': {'primary': '//h1'}}, True))
    selectors, used_llm = await Pipeline._discover(stub, 'https://x.com', '<html/>')
    assert selectors is not None
    assert used_llm is True
    Pipeline._discover.assert_called_once()


async def test_discover_does_not_retry_beyond_max_level(mocker):
    from yosoi.models.selectors import SelectorLevel

    stub = _make_pipeline_stub(mocker)
    stub.selector_level = SelectorLevel.CSS
    mocker.patch.object(Pipeline, '_discover', return_value=(None, False))
    selectors, _used_llm = await Pipeline._discover(stub, 'https://x.com', '<html/>')
    assert selectors is None
    Pipeline._discover.assert_called_once()


async def test_discover_returns_none_when_all_levels_fail(mocker):
    from yosoi.models.selectors import SelectorLevel

    stub = _make_pipeline_stub(mocker)
    stub.selector_level = SelectorLevel.XPATH
    mocker.patch.object(Pipeline, '_discover', return_value=(None, False))
    selectors, used_llm = await Pipeline._discover(stub, 'https://x.com', '<html/>')
    assert selectors is None
    assert used_llm is False


async def test_process_url_raises_when_fetch_fails(mocker):
    stub = _make_pipeline_stub(mocker)
    mocker.patch.object(Pipeline, 'normalize_url', return_value='https://x.com')
    mocker.patch.object(Pipeline, '_extract_domain', return_value='x.com')
    mocker.patch.object(Pipeline, '_create_fetcher', return_value=mocker.MagicMock())
    stub.storage.load_selectors.return_value = None
    mocker.patch.object(Pipeline, '_fetch', return_value=None)
    mocker.patch('yosoi.core.pipeline.base.observability')
    with pytest.raises(RuntimeError):
        await Pipeline.process_url(stub, 'https://x.com')


async def test_process_url_raises_when_create_fetcher_fails(mocker):
    stub = _make_pipeline_stub(mocker)
    mocker.patch.object(Pipeline, 'normalize_url', return_value='https://x.com')
    mocker.patch.object(Pipeline, '_extract_domain', return_value='x.com')
    mocker.patch.object(Pipeline, '_create_fetcher', return_value=None)
    mocker.patch('yosoi.core.pipeline.base.observability')
    with pytest.raises(RuntimeError):
        await Pipeline.process_url(stub, 'https://x.com')


async def test_process_url_succeeds_with_cached_selectors(mocker):
    from datetime import datetime, timezone

    from yosoi.models.snapshot import SelectorSnapshot

    stub = _make_pipeline_stub(mocker)
    mocker.patch.object(Pipeline, 'normalize_url', return_value='https://x.com')
    mocker.patch.object(Pipeline, '_extract_domain', return_value='x.com')
    mocker.patch.object(Pipeline, '_create_fetcher', return_value=mocker.MagicMock())
    now = datetime.now(timezone.utc)
    stub.storage.load_snapshots.return_value = {
        'title': SelectorSnapshot(primary={'type': 'css', 'value': 'h1'}, discovered_at=now),
    }
    stub.storage.load_selectors.return_value = {'title': {'primary': 'h1'}}
    mocker.patch.object(Pipeline, '_extract_with_cached', return_value=([{'title': 'Book'}], True))
    stub.tracker.record_url.return_value = DomainStats(url_count=1)
    mocker.patch('yosoi.core.pipeline.base.observability')
    await Pipeline.process_url(stub, 'https://x.com')


async def test_process_url_cache_miss_uses_gated_fresh(mocker):
    stub = _make_pipeline_stub(mocker)
    fetcher = mocker.MagicMock()
    fetcher.__aenter__ = mocker.AsyncMock(return_value=fetcher)
    fetcher.__aexit__ = mocker.AsyncMock(return_value=None)
    mocker.patch.object(Pipeline, 'normalize_url', return_value='https://x.com')
    mocker.patch.object(Pipeline, '_extract_domain', return_value='x.com')
    mocker.patch.object(Pipeline, '_create_fetcher', return_value=fetcher)
    mocker.patch.object(Pipeline, '_try_cached', return_value=None)
    scrape_fresh = mocker.patch.object(Pipeline, '_scrape_fresh')

    async def gated_fresh(*args, **kwargs):
        yield {'title': 'Book', 'price': 1.0}

    gated = mocker.patch.object(Pipeline, '_gated_fresh', side_effect=gated_fresh)
    mocker.patch('yosoi.core.pipeline.base.observability')

    await Pipeline.process_url(stub, 'https://x.com')

    gated.assert_called_once()
    scrape_fresh.assert_not_called()


async def test_process_url_full_success_path(mocker):
    stub = _make_pipeline_stub(mocker)
    fetch_result = FetchResult(url='https://x.com', html='<html/>', status_code=200)
    mocker.patch.object(Pipeline, 'normalize_url', return_value='https://x.com')
    mocker.patch.object(Pipeline, '_extract_domain', return_value='x.com')
    mocker.patch.object(Pipeline, '_create_fetcher', return_value=mocker.MagicMock())
    stub.storage.load_selectors.return_value = None
    mocker.patch.object(Pipeline, '_fetch', return_value=fetch_result)
    mocker.patch.object(Pipeline, '_clean', return_value='<clean/>')
    mocker.patch.object(Pipeline, '_discover', return_value=({'title': {'primary': 'h1'}}, True))
    mocker.patch.object(Pipeline, '_verify', return_value={'title': {'primary': 'h1'}})
    mocker.patch.object(Pipeline, '_extract', return_value={'title': 'Book'})
    mocker.patch.object(Pipeline, '_validate_with_contract', return_value={'title': 'Book'})
    mocker.patch.object(Pipeline, '_save_and_track')
    mocker.patch('yosoi.core.pipeline.base.observability')
    await Pipeline.process_url(stub, 'https://x.com')


async def test_process_url_succeeds_even_when_extraction_fails(mocker):
    stub = _make_pipeline_stub(mocker)
    fetch_result = FetchResult(url='https://x.com', html='<html/>', status_code=200)
    mocker.patch.object(Pipeline, 'normalize_url', return_value='https://x.com')
    mocker.patch.object(Pipeline, '_extract_domain', return_value='x.com')
    mocker.patch.object(Pipeline, '_create_fetcher', return_value=mocker.MagicMock())
    stub.storage.load_selectors.return_value = None
    mocker.patch.object(Pipeline, '_fetch', return_value=fetch_result)
    mocker.patch.object(Pipeline, '_clean', return_value='<clean/>')
    mocker.patch.object(Pipeline, '_discover', return_value=({'title': {'primary': 'h1'}}, True))
    mocker.patch.object(Pipeline, '_verify', return_value={'title': {'primary': 'h1'}})
    mocker.patch.object(Pipeline, '_extract', return_value=None)
    mocker.patch.object(Pipeline, '_save_and_track')
    mocker.patch('yosoi.core.pipeline.base.observability')
    await Pipeline.process_url(stub, 'https://x.com')


async def test_process_url_raises_when_clean_fails(mocker):
    stub = _make_pipeline_stub(mocker)
    fetch_result = FetchResult(url='https://x.com', html='<html/>', status_code=200)
    mocker.patch.object(Pipeline, 'normalize_url', return_value='https://x.com')
    mocker.patch.object(Pipeline, '_extract_domain', return_value='x.com')
    mocker.patch.object(Pipeline, '_create_fetcher', return_value=mocker.MagicMock())
    stub.storage.load_selectors.return_value = None
    mocker.patch.object(Pipeline, '_fetch', return_value=fetch_result)
    mocker.patch.object(Pipeline, '_clean', return_value=None)
    mocker.patch('yosoi.core.pipeline.base.observability')
    with pytest.raises(RuntimeError):
        await Pipeline.process_url(stub, 'https://x.com')


async def test_process_url_raises_when_discover_fails(mocker):
    stub = _make_pipeline_stub(mocker)
    fetch_result = FetchResult(url='https://x.com', html='<html/>', status_code=200)
    mocker.patch.object(Pipeline, 'normalize_url', return_value='https://x.com')
    mocker.patch.object(Pipeline, '_extract_domain', return_value='x.com')
    mocker.patch.object(Pipeline, '_create_fetcher', return_value=mocker.MagicMock())
    stub.storage.load_selectors.return_value = None
    mocker.patch.object(Pipeline, '_fetch', return_value=fetch_result)
    mocker.patch.object(Pipeline, '_clean', return_value='<clean/>')
    mocker.patch.object(Pipeline, '_discover', return_value=(None, False))
    mocker.patch('yosoi.core.pipeline.base.observability')
    with pytest.raises(RuntimeError):
        await Pipeline.process_url(stub, 'https://x.com')


async def test_process_url_raises_when_verify_fails(mocker):
    stub = _make_pipeline_stub(mocker)
    fetch_result = FetchResult(url='https://x.com', html='<html/>', status_code=200)
    mocker.patch.object(Pipeline, 'normalize_url', return_value='https://x.com')
    mocker.patch.object(Pipeline, '_extract_domain', return_value='x.com')
    mocker.patch.object(Pipeline, '_create_fetcher', return_value=mocker.MagicMock())
    stub.storage.load_selectors.return_value = None
    mocker.patch.object(Pipeline, '_fetch', return_value=fetch_result)
    mocker.patch.object(Pipeline, '_clean', return_value='<clean/>')
    mocker.patch.object(Pipeline, '_discover', return_value=({'title': {'primary': 'h1'}}, True))
    mocker.patch.object(Pipeline, '_verify', return_value=None)
    mocker.patch('yosoi.core.pipeline.base.observability')
    with pytest.raises(RuntimeError):
        await Pipeline.process_url(stub, 'https://x.com')


async def test_process_urls_collects_results(mocker):
    stub = _make_pipeline_stub(mocker)
    mocker.patch.object(Pipeline, 'process_url', side_effect=[None, RuntimeError('fail')])
    mocker.patch('yosoi.core.pipeline.base.observability')
    results = await Pipeline.process_urls(stub, ['https://a.com', 'https://b.com'])
    assert 'https://a.com' in results['successful']
    assert 'https://b.com' in results['failed']


async def test_process_urls_catches_exceptions(mocker):
    stub = _make_pipeline_stub(mocker)
    mocker.patch.object(Pipeline, 'process_url', side_effect=RuntimeError('boom'))
    mocker.patch('yosoi.core.pipeline.base.observability')
    results = await Pipeline.process_urls(stub, ['https://a.com'])
    assert 'https://a.com' in results['failed']


async def test_process_urls_uses_pipeline_force_flag(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.force = True
    calls = []

    async def capture_call(url, *args, **kwargs):
        calls.append(kwargs.get('force', args[0] if args else None))
        return True

    mocker.patch.object(Pipeline, 'process_url', side_effect=capture_call)
    mocker.patch('yosoi.core.pipeline.base.observability')
    await Pipeline.process_urls(stub, ['https://a.com'])
    assert len(calls) == 1


async def test_show_summary_prints_warning_when_no_domains(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.storage.list_domains.return_value = []
    await Pipeline.show_summary(stub)
    stub.console.print.assert_called()


async def test_show_summary_prints_table_with_domains(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.storage.list_domains.return_value = ['example.com']
    stub.storage.load_selectors.return_value = {'title': {'primary': 'h1'}}
    await Pipeline.show_summary(stub)
    stub.console.print.assert_called()


async def test_show_llm_stats_with_data(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.tracker.get_all_stats.return_value = {'example.com': DomainStats(llm_calls=2, url_count=10)}
    await Pipeline.show_llm_stats(stub)
    stub.console.print.assert_called()


async def test_show_llm_stats_no_calls(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.tracker.get_all_stats.return_value = {}
    await Pipeline.show_llm_stats(stub)
    stub.console.print.assert_called()


async def test_process_url_respects_explicit_force_override(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.force = False
    mocker.patch.object(Pipeline, 'normalize_url', return_value='https://x.com')
    mocker.patch.object(Pipeline, '_extract_domain', return_value='x.com')
    mock_fetcher = mocker.MagicMock()
    mocker.patch.object(Pipeline, '_create_fetcher', return_value=mock_fetcher)
    stub.storage.load_selectors.return_value = {'title': {'primary': 'h1'}}
    mocker.patch.object(Pipeline, '_fetch', return_value=None)
    mocker.patch('yosoi.core.pipeline.base.observability')
    with pytest.raises(RuntimeError):
        await Pipeline.process_url(stub, 'https://x.com', force=True)
    stub.storage.load_selectors.assert_not_called()


async def test_normalize_url_http_url_returned_unchanged(mocker):
    stub = _make_pipeline_stub(mocker)
    url = 'http://example.com/path?q=1'
    assert await Pipeline.normalize_url(stub, url) == url


async def test_normalize_url_https_url_returned_unchanged(mocker):
    stub = _make_pipeline_stub(mocker)
    url = 'https://example.com/path'
    assert await Pipeline.normalize_url(stub, url) == url


async def test_normalize_url_prepends_https_exactly(mocker):
    stub = _make_pipeline_stub(mocker)
    _mock_async_client(mocker, stub)
    result = await Pipeline.normalize_url(stub, 'www.example.com')
    assert result == 'https://www.example.com'


async def test_normalize_url_prepends_http_on_https_failure(mocker):
    import httpx

    stub = _make_pipeline_stub(mocker)
    _mock_async_client(mocker, stub, raise_on_head=httpx.HTTPError('fail'))
    result = await Pipeline.normalize_url(stub, 'example.com')
    assert result == 'http://example.com'


def test_extract_domain_exactly_removes_www_prefix(mocker):
    stub = _make_pipeline_stub(mocker)
    assert Pipeline._extract_domain(stub, 'https://www.example.com') == 'example.com'


def test_extract_domain_does_not_modify_subdomain(mocker):
    stub = _make_pipeline_stub(mocker)
    assert Pipeline._extract_domain(stub, 'https://api.example.com') == 'api.example.com'


def test_verify_calls_verifier_with_correct_args(mocker):
    stub = _make_pipeline_stub(mocker)
    selectors = {'title': {'primary': 'h1'}}
    vr = _make_verification_result(True, ['title'])
    stub.verifier.verify.return_value = vr
    Pipeline._verify(stub, 'https://x.com', '<html>test</html>', selectors, skip_verification=False)
    from yosoi.models.selectors import SelectorLevel

    stub.verifier.verify.assert_called_once_with('<html>test</html>', selectors, max_level=SelectorLevel.CSS)


def test_verify_returns_only_verified_fields(mocker):
    stub = _make_pipeline_stub(mocker)
    results = {
        'title': FieldVerificationResult(field_name='title', status='verified', working_level='primary', selector='h1'),
        'price': FieldVerificationResult(field_name='price', status='failed'),
    }
    vr = VerificationResult(total_fields=2, verified_count=1, results=results)
    stub.verifier.verify.return_value = vr
    selectors = {'title': {'primary': 'h1'}, 'price': {'primary': '.p'}}
    result = Pipeline._verify(stub, 'https://x.com', '<html/>', selectors, skip_verification=False)
    assert result is not None
    assert 'title' in result
    assert 'price' not in result


def test_verify_failed_result_calls_print_verification_failure(mocker):
    stub = _make_pipeline_stub(mocker)
    selectors = {'title': {'primary': 'h1'}}
    vr = _make_verification_result(False, ['title'])
    stub.verifier.verify.return_value = vr
    print_fail_mock = mocker.patch.object(Pipeline, '_print_verification_failure')
    Pipeline._verify(stub, 'https://x.com', '<html/>', selectors, skip_verification=False)
    print_fail_mock.assert_called_once_with(vr)


async def test_save_and_track_calls_record_url_with_used_llm_true(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.tracker.record_url.return_value = DomainStats(llm_calls=1, url_count=1)
    await Pipeline._save_and_track(
        stub,
        url='https://x.com',
        domain='x.com',
        verified={'title': {'primary': 'h1'}},
        extracted=None,
        used_llm=True,
        output_format=['json'],
    )
    stub.tracker.record_url.assert_called_once_with(
        'https://x.com', used_llm=True, level_distribution=None, elapsed=None
    )


async def test_save_and_track_calls_record_url_with_used_llm_false(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.tracker.record_url.return_value = DomainStats(llm_calls=0, url_count=1)
    await Pipeline._save_and_track(
        stub,
        url='https://x.com',
        domain='x.com',
        verified={},
        extracted=None,
        used_llm=False,
        output_format=['json'],
    )
    stub.tracker.record_url.assert_called_once_with(
        'https://x.com', used_llm=False, level_distribution=None, elapsed=None
    )


async def test_save_and_track_saves_content_with_output_format(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.tracker.record_url.return_value = DomainStats(llm_calls=1, url_count=1)
    await Pipeline._save_and_track(
        stub,
        url='https://x.com',
        domain='x.com',
        verified={'title': {'primary': 'h1'}},
        extracted={'title': 'Book'},
        used_llm=True,
        output_format=['markdown'],
    )
    stub.storage.save_content.assert_called_once_with(
        'https://x.com', {'title': 'Book'}, 'markdown', contract_sig=stub._contract_sig
    )


async def test_save_and_track_passes_contract_sig_to_save_content(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.tracker.record_url.return_value = DomainStats(llm_calls=1, url_count=1)
    await Pipeline._save_and_track(
        stub,
        url='https://x.com',
        domain='x.com',
        verified={'title': {'primary': 'h1'}},
        extracted={'title': 'Book'},
        used_llm=True,
        output_format=['json'],
    )
    _, kwargs = stub.storage.save_content.call_args
    assert kwargs.get('contract_sig') == stub._contract_sig


async def test_track_cached_success_calls_record_url_used_llm_false(mocker):
    stub = _make_pipeline_stub(mocker)
    stub._url_start = 100.0
    mocker.patch('yosoi.core.pipeline.base.time.monotonic', return_value=103.0)
    stub.tracker.record_url.return_value = DomainStats(llm_calls=0, url_count=1)
    await Pipeline._track_cached_success(stub, 'https://example.com', 'example.com')
    call_args = stub.tracker.record_url.call_args
    assert call_args[0] == ('https://example.com',)
    assert call_args[1]['used_llm'] is False
    assert call_args[1]['level_distribution'] is None
    assert call_args[1]['elapsed'] == 3.0


def test_print_tracking_stats_shows_llm_call_count(mocker):
    stub = _make_pipeline_stub(mocker)
    Pipeline._print_tracking_stats(stub, 'x.com', DomainStats(llm_calls=5, url_count=10))
    call_args = ' '.join(str(c) for c in stub.console.print.call_args_list)
    assert '5' in call_args


def test_print_tracking_stats_shows_url_count(mocker):
    stub = _make_pipeline_stub(mocker)
    Pipeline._print_tracking_stats(stub, 'x.com', DomainStats(llm_calls=1, url_count=7))
    call_args = ' '.join(str(c) for c in stub.console.print.call_args_list)
    assert '7' in call_args


def test_print_tracking_stats_efficiency_calculation(mocker):
    stub = _make_pipeline_stub(mocker)
    Pipeline._print_tracking_stats(stub, 'x.com', DomainStats(llm_calls=2, url_count=10))
    call_args = ' '.join(str(c) for c in stub.console.print.call_args_list)
    assert '5.0' in call_args


def test_print_tracking_stats_no_efficiency_when_llm_zero(mocker):
    stub = _make_pipeline_stub(mocker)
    Pipeline._print_tracking_stats(stub, 'x.com', DomainStats(llm_calls=0, url_count=3))
    stub.console.print.assert_called()


def test_print_tracking_stats_shows_total_elapsed(mocker):
    stub = _make_pipeline_stub(mocker)
    Pipeline._print_tracking_stats(stub, 'x.com', DomainStats(llm_calls=1, url_count=2, total_elapsed=5.3))
    call_args = ' '.join(str(c) for c in stub.console.print.call_args_list)
    assert '5.3' in call_args


def test_handle_bot_detection_shows_url(mocker):
    stub = _make_pipeline_stub(mocker)
    err = BotDetectionError(url='https://blocked.com', status_code=403, indicators=['captcha'])
    Pipeline._handle_bot_detection(stub, err, attempt=1, max_retries=3)
    call_args = ' '.join(str(c) for c in stub.console.print.call_args_list)
    assert 'blocked.com' in call_args or 'https://blocked.com' in call_args


def test_handle_bot_detection_shows_status_code(mocker):
    stub = _make_pipeline_stub(mocker)
    err = BotDetectionError(url='https://x.com', status_code=429, indicators=['rate-limit'])
    Pipeline._handle_bot_detection(stub, err, attempt=1, max_retries=3)
    call_args = ' '.join(str(c) for c in stub.console.print.call_args_list)
    assert '429' in call_args


def test_handle_bot_detection_abort_only_when_exhausted(mocker):
    stub = _make_pipeline_stub(mocker)
    err = BotDetectionError(url='https://x.com', status_code=403, indicators=['cf'])
    Pipeline._handle_bot_detection(stub, err, attempt=1, max_retries=3)
    call_args = ' '.join(str(c) for c in stub.console.print.call_args_list)
    assert 'ABORTING' not in call_args


def test_handle_bot_detection_abort_when_exactly_at_max_retries(mocker):
    stub = _make_pipeline_stub(mocker)
    err = BotDetectionError(url='https://x.com', status_code=403, indicators=['cf'])
    Pipeline._handle_bot_detection(stub, err, attempt=3, max_retries=3)
    call_args = ' '.join(str(c) for c in stub.console.print.call_args_list)
    assert 'ABORTING' in call_args


async def test_extract_with_cached_returns_items_on_success(mocker):
    stub = _make_pipeline_stub(mocker)
    mock_fetcher = mocker.MagicMock()
    mock_fetcher.fetch = mocker.AsyncMock(return_value=FetchResult(url='https://x.com', html='<html/>'))
    stub.cleaner.clean_html.return_value = '<html/>'
    vr = _make_verification_result(True, ['title', 'price'])
    stub.verifier.verify.return_value = vr
    stub.extractor.extract_content_with_html.return_value = {'title': 'Book', 'price': '9.99'}
    items, cache_valid = await Pipeline._extract_with_cached(
        stub,
        'https://x.com',
        mock_fetcher,
        {'title': {'primary': 'h1'}, 'price': {'primary': '.price'}},
        False,
    )
    assert cache_valid is True
    assert items == [{'title': 'Book', 'price': '9.99'}]


async def test_extract_with_cached_fail_open_on_exception(mocker):
    stub = _make_pipeline_stub(mocker)
    mock_fetcher = mocker.MagicMock()
    mock_fetcher.fetch = mocker.AsyncMock(side_effect=RuntimeError('network error'))
    items, cache_valid = await Pipeline._extract_with_cached(
        stub, 'https://x.com', mock_fetcher, {'title': {'primary': 'h1'}}, False
    )
    assert cache_valid is True
    assert items is None


async def test_extract_with_cached_fails_fast_on_download_error(mocker):
    class FileContract(Contract):
        report: list[dict] = ys.File(trigger='a.export', allowed_types=['csv'])

    stub = _make_pipeline_stub(mocker, contract=FileContract)
    stub._allow_downloads = True
    mock_fetcher = mocker.MagicMock()
    mock_fetcher.supports_browse = True
    mock_fetcher.fetch = mocker.AsyncMock(side_effect=DownloadError('report', 'content does not match allowed_types'))

    with pytest.raises(DownloadError):
        await Pipeline._extract_with_cached(stub, 'https://x.com', mock_fetcher, {}, False)


async def test_extract_with_cached_missing_contract_field_triggers_rediscovery(mocker):
    class TwoFieldContract(Contract):
        title: str = ys.Title()
        price: float = ys.Price()

    stub = _make_pipeline_stub(mocker, contract=TwoFieldContract)
    mock_fetcher = mocker.MagicMock()
    mock_fetcher.fetch = mocker.AsyncMock(return_value=FetchResult(url='https://x.com', html='<html/>'))
    stub.cleaner.clean_html.return_value = '<html/>'
    vr = _make_verification_result(True, ['title'])
    stub.verifier.verify.return_value = vr
    items, cache_valid = await Pipeline._extract_with_cached(
        stub, 'https://x.com', mock_fetcher, {'title': {'primary': 'h1'}}, False
    )
    assert cache_valid is False
    assert items is None


async def test_extract_with_cached_missing_overridden_field_does_not_trigger_rediscovery(mocker):
    from yosoi.types.field import Field as YsField

    class OverriddenContract(Contract):
        title: str = ys.Title()
        price: float = YsField(description='Price', selector='p.price')  # type: ignore[assignment]

    stub = _make_pipeline_stub(mocker, contract=OverriddenContract)
    mock_fetcher = mocker.MagicMock()
    mock_fetcher.fetch = mocker.AsyncMock(return_value=FetchResult(url='https://x.com', html='<html/>'))
    stub.cleaner.clean_html.return_value = '<html/>'
    vr = _make_verification_result(True, ['title'])
    stub.verifier.verify.return_value = vr
    stub.extractor.extract_content_with_html.return_value = {'title': 'Book'}
    items, cache_valid = await Pipeline._extract_with_cached(
        stub, 'https://x.com', mock_fetcher, {'title': {'primary': 'h1'}}, False
    )
    assert cache_valid is True
    assert items == [{'title': 'Book'}]


def test_extract_calls_extractor_with_correct_args(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.extractor.extract_content_with_html.return_value = {'title': 'Book'}
    Pipeline._extract(stub, 'https://x.com', '<html>content</html>', {'title': {'primary': 'h1'}})
    from yosoi.models.selectors import SelectorLevel

    stub.extractor.extract_content_with_html.assert_called_once_with(
        'https://x.com', '<html>content</html>', {'title': {'primary': 'h1'}}, max_level=SelectorLevel.CSS
    )


def test_print_verification_failure_calls_console_print(mocker):
    stub = _make_pipeline_stub(mocker)
    results = {'title': FieldVerificationResult(field_name='title', status='failed')}
    vr = VerificationResult(total_fields=1, verified_count=0, results=results)
    Pipeline._print_verification_failure(stub, vr)
    stub.console.print.assert_called()


def test_print_partial_failure_shows_failed_field_names(mocker):
    stub = _make_pipeline_stub(mocker)
    results = {
        'title': FieldVerificationResult(field_name='title', status='verified', working_level='primary', selector='h1'),
        'price': FieldVerificationResult(field_name='price', status='failed'),
    }
    vr = VerificationResult(total_fields=2, verified_count=1, results=results)
    Pipeline._print_partial_failure(stub, vr)
    call_args = ' '.join(str(c) for c in stub.console.print.call_args_list)
    assert 'price' in call_args


async def test_process_url_uses_pipeline_format_when_output_format_none(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.output_formats = ['markdown']
    mocker.patch.object(Pipeline, 'normalize_url', return_value='https://x.com')
    mocker.patch.object(Pipeline, '_extract_domain', return_value='x.com')
    mocker.patch.object(Pipeline, '_create_fetcher', return_value=mocker.MagicMock())
    stub.storage.load_selectors.return_value = None
    mock_fetch = mocker.patch.object(Pipeline, '_fetch', return_value=None)
    mocker.patch('yosoi.core.pipeline.base.observability')
    with pytest.raises(RuntimeError):
        await Pipeline.process_url(stub, 'https://x.com', output_format=None)
    mock_fetch.assert_called_once()


async def test_show_summary_shows_domain_count(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.storage.list_domains.return_value = ['a.com', 'b.com']
    stub.storage.load_selectors.return_value = {'title': {'primary': 'h1'}}
    await Pipeline.show_summary(stub)
    call_args = ' '.join(str(c) for c in stub.console.print.call_args_list)
    assert '2' in call_args


async def test_show_llm_stats_shows_efficiency_when_llm_calls_nonzero(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.tracker.get_all_stats.return_value = {'x.com': DomainStats(llm_calls=4, url_count=20)}
    await Pipeline.show_llm_stats(stub)
    call_args = ' '.join(str(c) for c in stub.console.print.call_args_list)
    assert '5.0' in call_args


async def test_show_llm_stats_sums_all_domains(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.tracker.get_all_stats.return_value = {
        'a.com': DomainStats(llm_calls=2, url_count=10),
        'b.com': DomainStats(llm_calls=3, url_count=15),
    }
    await Pipeline.show_llm_stats(stub)
    call_args = ' '.join(str(c) for c in stub.console.print.call_args_list)
    assert '5' in call_args
    assert '25' in call_args


async def test_clean_calls_cleaner_with_html(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.cleaner.clean_html.return_value = '<clean/>'
    result_obj = FetchResult(url='https://x.com', html='<dirty/>')
    await Pipeline._clean(stub, 'https://x.com', result_obj)
    stub.cleaner.clean_html.assert_called_once_with('<dirty/>')


async def test_clean_saves_debug_html(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.cleaner.clean_html.return_value = '<clean/>'
    result_obj = FetchResult(url='https://x.com', html='<dirty/>')
    await Pipeline._clean(stub, 'https://x.com', result_obj)
    stub.debug.save_debug_html.assert_called_once_with('https://x.com', '<clean/>')


async def test_discover_merges_overrides_with_ai_selectors(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.contract.get_selector_overrides = mocker.MagicMock(return_value={'author': {'primary': '.author'}})
    stub.contract.field_descriptions = mocker.MagicMock(return_value={'title': 'The title'})
    stub.discovery.discover_selectors = mocker.AsyncMock(return_value={'title': {'primary': 'h1'}})
    stub.debug.save_debug_selectors = mocker.AsyncMock()
    from tenacity import AsyncRetrying, stop_after_attempt, wait_none

    mocker.patch(
        'yosoi.core.pipeline.discovery.get_async_retryer',
        return_value=AsyncRetrying(stop=stop_after_attempt(1), wait=wait_none(), reraise=False),
    )
    _selectors, _used_llm = await Pipeline._discover(stub, 'https://x.com', '<html/>', max_retries=1)
    assert _selectors is not None
    assert 'title' in _selectors
    assert 'author' in _selectors


async def test_discover_all_override_returns_false_for_used_llm(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.contract.get_selector_overrides = mocker.MagicMock(return_value={'title': {'primary': '.t'}})
    stub.contract.field_descriptions = mocker.MagicMock(return_value={})
    stub.debug.save_debug_selectors = mocker.AsyncMock()
    _selectors, used_llm = await Pipeline._discover(stub, 'https://x.com', '<html/>', max_retries=1)
    assert used_llm is False


async def test_discover_ai_success_returns_true_for_used_llm(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.contract.get_selector_overrides = mocker.MagicMock(return_value={})
    stub.contract.field_descriptions = mocker.MagicMock(return_value={'title': 'The title'})
    stub.discovery.discover_selectors = mocker.AsyncMock(return_value={'title': {'primary': 'h1'}})
    stub.debug.save_debug_selectors = mocker.AsyncMock()
    from tenacity import AsyncRetrying, stop_after_attempt, wait_none

    mocker.patch(
        'yosoi.core.pipeline.discovery.get_async_retryer',
        return_value=AsyncRetrying(stop=stop_after_attempt(1), wait=wait_none(), reraise=False),
    )
    _, used_llm = await Pipeline._discover(stub, 'https://x.com', '<html/>', max_retries=1)
    assert used_llm is True


def test_print_summary_shows_skipped_when_present(mocker):
    stub = _make_pipeline_stub(mocker)
    results = {'successful': ['https://a.com'], 'failed': [], 'skipped': ['https://b.com']}
    Pipeline._print_summary(stub, results, 1.5)
    all_calls = ' '.join(str(c) for c in stub.console.print.call_args_list)
    assert 'skip' in all_calls.lower() or '1' in all_calls


def test_print_summary_lists_failed_urls(mocker):
    stub = _make_pipeline_stub(mocker)
    results = {'successful': [], 'failed': ['https://x.com', 'https://y.com']}
    Pipeline._print_summary(stub, results, 2.0)
    all_calls = ' '.join(str(c) for c in stub.console.print.call_args_list)
    assert 'https://x.com' in all_calls
    assert 'https://y.com' in all_calls


def test_print_summary_no_skipped_key_no_error(mocker):
    stub = _make_pipeline_stub(mocker)
    results = {'successful': ['https://a.com'], 'failed': []}
    Pipeline._print_summary(stub, results, 0.5)
    stub.console.print.assert_called()


async def test_process_urls_calls_on_complete_on_success(mocker):
    stub = _make_pipeline_stub(mocker)
    mocker.patch.object(Pipeline, 'process_url', return_value=None)
    mocker.patch('yosoi.core.pipeline.base.observability')
    completed: list[tuple[str, bool]] = []

    async def on_complete(url: str, success: bool, elapsed: float) -> None:
        completed.append((url, success))

    await Pipeline.process_urls(stub, ['https://a.com'], on_complete=on_complete)
    assert len(completed) == 1
    assert completed[0] == ('https://a.com', True)


async def test_process_urls_calls_on_complete_on_failure(mocker):
    stub = _make_pipeline_stub(mocker)
    mocker.patch.object(Pipeline, 'process_url', side_effect=RuntimeError('boom'))
    mocker.patch('yosoi.core.pipeline.base.observability')
    completed: list[tuple[str, bool]] = []

    async def on_complete(url: str, success: bool, elapsed: float) -> None:
        completed.append((url, success))

    await Pipeline.process_urls(stub, ['https://fail.com'], on_complete=on_complete)
    assert len(completed) == 1
    assert completed[0] == ('https://fail.com', False)


import time as _time


class TestBuildConcurrentTable:
    def test_empty_status(self):
        from yosoi.core.pipeline import _build_concurrent_table

        table = _build_concurrent_table({})
        assert table.title == 'Concurrent Processing'
        assert table.row_count == 0

    def test_queued_status(self):
        from yosoi.core.pipeline import _build_concurrent_table

        table = _build_concurrent_table({'https://example.com': ('Queued', 0.0)})
        assert table.row_count == 1

    def test_running_status_with_elapsed(self):
        from yosoi.core.pipeline import _build_concurrent_table

        now = _time.monotonic()
        table = _build_concurrent_table({'https://example.com': ('Running', now)})
        assert table.row_count == 1

    def test_done_status(self):
        from yosoi.core.pipeline import _build_concurrent_table

        table = _build_concurrent_table({'https://example.com': ('Done', 5.2)})
        assert table.row_count == 1

    def test_failed_status(self):
        from yosoi.core.pipeline import _build_concurrent_table

        table = _build_concurrent_table({'https://example.com': ('Failed', 3.0)})
        assert table.row_count == 1

    def test_skipped_status(self):
        from yosoi.core.pipeline import _build_concurrent_table

        table = _build_concurrent_table({'https://example.com': ('Skipped', 0.0)})
        assert table.row_count == 1

    def test_multiple_urls(self):
        from yosoi.core.pipeline import _build_concurrent_table

        url_status = {
            'https://a.com': ('Queued', 0.0),
            'https://b.com': ('Done', 2.0),
            'https://c.com': ('Failed', 1.0),
        }
        table = _build_concurrent_table(url_status)
        assert table.row_count == 3

    def test_unknown_status_uses_default_style(self):
        from yosoi.core.pipeline import _build_concurrent_table

        table = _build_concurrent_table({'https://example.com': ('UnknownStatus', 1.0)})
        assert table.row_count == 1


class TestProcessUrlsAutoLive:
    @pytest.mark.asyncio
    async def test_workers_gt1_quiet_false_no_callbacks_uses_live(self, mocker):
        stub = _make_pipeline_stub(mocker)
        stub.console.quiet = False
        mock_live_fn = mocker.AsyncMock(return_value={'successful': [], 'failed': [], 'skipped': []})
        mock_concurrent_fn = mocker.AsyncMock(return_value={'successful': [], 'failed': [], 'skipped': []})
        mocker.patch.object(Pipeline, '_process_urls_with_live', mock_live_fn)
        mocker.patch.object(Pipeline, '_process_urls_concurrent', mock_concurrent_fn)
        await Pipeline.process_urls(stub, ['https://a.com', 'https://b.com'], workers=2)
        mock_live_fn.assert_awaited_once()
        mock_concurrent_fn.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_workers_gt1_quiet_true_uses_concurrent_directly(self, mocker):
        stub = _make_pipeline_stub(mocker)
        stub.console.quiet = True
        mock_concurrent = mocker.AsyncMock(return_value={'successful': [], 'failed': [], 'skipped': []})
        mocker.patch.object(Pipeline, '_process_urls_concurrent', mock_concurrent)
        mock_live_fn = mocker.AsyncMock()
        mocker.patch.object(Pipeline, '_process_urls_with_live', mock_live_fn)
        await Pipeline.process_urls(stub, ['https://a.com', 'https://b.com'], workers=2)
        mock_concurrent.assert_awaited_once()
        mock_live_fn.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_workers_gt1_on_complete_provided_uses_concurrent_directly(self, mocker):
        stub = _make_pipeline_stub(mocker)
        stub.console.quiet = False
        mock_concurrent = mocker.AsyncMock(return_value={'successful': [], 'failed': [], 'skipped': []})
        mocker.patch.object(Pipeline, '_process_urls_concurrent', mock_concurrent)
        mock_live_fn = mocker.AsyncMock()
        mocker.patch.object(Pipeline, '_process_urls_with_live', mock_live_fn)

        async def dummy_on_complete(url: str, success: bool, elapsed: float) -> None:
            pass

        await Pipeline.process_urls(
            stub,
            ['https://a.com', 'https://b.com'],
            workers=2,
            on_complete=dummy_on_complete,
        )
        mock_concurrent.assert_awaited_once()
        mock_live_fn.assert_not_awaited()


# ---------------------------------------------------------------------------
# Coverage: _validate_single_item branches in pipeline.utils
# ---------------------------------------------------------------------------

import yosoi as ys
from yosoi.models.contract import Contract


class _PriceContract(Contract):
    title: str = ys.Title()
    price: float = ys.Price()


class _CountContract(Contract):
    title: str = ys.Title()
    count: int = ys.Field(description='Count', default=0)  # type: ignore[assignment]


def test_validate_single_item_drops_isolable_field_to_default(mocker):
    """A FIELD-level validation error is isolated: only the bad field is reset to its
    default, the good fields survive, and the item re-validates.

    NB: ``int`` produces a field-scoped pydantic error (loc=('count',)) — unlike
    ``ys.Price()`` which raises a *model*-level error (loc=()), exercised separately
    below. This is the path that actually drops-and-recovers.
    """
    stub = _make_pipeline_stub(mocker, _CountContract)
    result = Pipeline._validate_single_item(stub, {'title': 'Book', 'count': 'not-a-number'}, url='')
    assert result == {'title': 'Book', 'count': 0}  # count -> its default, title preserved


def test_validate_items_summarizes_defaulted_fields(mocker):
    stub = _make_pipeline_stub(mocker, _CountContract)
    result = Pipeline._validate_items(
        stub,
        [{'title': 'Book', 'count': 'not-a-number'}, {'title': 'Pen', 'count': 'still-not-a-number'}],
        url='',
    )
    assert result == [{'title': 'Book', 'count': 0}, {'title': 'Pen', 'count': 0}]
    printed = ' '.join(str(c) for c in stub.console.print.call_args_list)
    assert 'Contract validation defaulted invalid field' in printed
    assert 'count' in printed
    assert '2 items' in printed


def test_validate_items_deduplicates_framework_copies_after_coercion(mocker):
    stub = _make_pipeline_stub(mocker, _PriceContract)
    result = Pipeline._validate_items(
        stub,
        [
            {'title': 'Standard Iron Pickaxe', 'price': '14.50 GS'},
            {'title': 'Standard Iron Pickaxe', 'price': '14.50  GS'},
            {'title': 'Masterwork Steel Pickaxe', 'price': '45.00 GS'},
        ],
        url='',
    )
    assert result == [
        {'title': 'Standard Iron Pickaxe', 'price': 14.5},
        {'title': 'Masterwork Steel Pickaxe', 'price': 45.0},
    ]
    printed = ' '.join(str(c) for c in stub.console.print.call_args_list)
    assert 'Dropped 1 duplicate item' in printed


def test_validate_single_item_returns_raw_when_default_also_invalid(mocker):
    """If the dropped field's default STILL fails validation, the raw item is returned untouched."""
    stub = _make_pipeline_stub(mocker, _CountContract)
    mocker.patch.object(stub.contract, 'field_default', return_value='still-not-an-int')
    raw = {'title': 'Book', 'count': 'not-a-number'}
    result = Pipeline._validate_single_item(stub, raw, url='')
    assert result is raw  # identity — nothing salvageable, returned as-is


def test_validate_single_item_returns_raw_when_error_unisolable(mocker):
    """A MODEL-level error (pydantic loc=()) can't be pinned to one field, so we don't
    guess which to drop — the raw item is returned intact."""
    stub = _make_pipeline_stub(mocker, _PriceContract)
    raw = {'title': 'Book', 'price': 'NaN'}  # ys.Price() rejects with loc=()
    result = Pipeline._validate_single_item(stub, raw, url='')
    assert result is raw


def test_validate_single_item_handles_value_error(mocker):
    """A non-pydantic ValueError from model_validate falls through to the raw-return guard."""
    stub = _make_pipeline_stub(mocker, _PriceContract)
    mocker.patch.object(stub.contract, 'model_validate', side_effect=ValueError('boom'))
    raw = {'title': 'Book', 'price': '9.99'}
    result = Pipeline._validate_single_item(stub, raw, url='')
    assert result is raw


# ---------------------------------------------------------------------------
# Coverage: _try_cached skip_verification / file_fields branch in pipeline.cache
# ---------------------------------------------------------------------------


async def test_try_cached_skip_verification_branch(mocker):
    """When skip_verification=True, _try_cached takes the fast path without re-fetching."""
    from datetime import datetime, timezone

    from yosoi.models.snapshot import SelectorSnapshot

    stub = _make_pipeline_stub(mocker)
    now = datetime.now(timezone.utc)
    stub.storage.load_snapshots.return_value = {
        'title': SelectorSnapshot(primary={'type': 'css', 'value': 'h1'}, discovered_at=now),
    }

    mock_fetcher = mocker.MagicMock()
    # _extract_with_cached returns (items, True) — cache valid
    mocker.patch.object(stub, '_extract_with_cached', return_value=([{'title': 'T'}], True))

    # _yield_cached_items is a generator — return a simple async gen
    async def _fake_yield(*a, **kw):
        yield {'title': 'T'}

    mocker.patch.object(stub, '_yield_cached_items', side_effect=_fake_yield)

    result = await Pipeline._try_cached(stub, 'https://x.com', 'x.com', mock_fetcher, True, ['json'])
    # Result is the async generator returned by _yield_cached_items
    assert result is not None


async def test_try_cached_skip_verification_cache_invalid_returns_none(mocker):
    """When skip_verification=True but cache is invalid, _try_cached returns None."""
    from datetime import datetime, timezone

    from yosoi.models.snapshot import SelectorSnapshot

    stub = _make_pipeline_stub(mocker)
    now = datetime.now(timezone.utc)
    stub.storage.load_snapshots.return_value = {
        'title': SelectorSnapshot(primary={'type': 'css', 'value': 'h1'}, discovered_at=now),
    }

    mock_fetcher = mocker.MagicMock()
    mocker.patch.object(stub, '_extract_with_cached', return_value=(None, False))

    result = await Pipeline._try_cached(stub, 'https://x.com', 'x.com', mock_fetcher, True, ['json'])
    assert result is None


# ---------------------------------------------------------------------------
# Coverage: _fetch error branches in pipeline.extraction
# ---------------------------------------------------------------------------


async def test_fetch_prints_error_when_html_is_none_after_fetch(mocker):
    """When fetcher returns a result with html=None (not blocked), an exception is raised internally."""
    stub = _make_pipeline_stub(mocker)
    # Return a result with html=None but is_blocked=False — hits the 'No HTML content received' branch
    mock_fetcher = mocker.MagicMock()
    result_no_html = mocker.MagicMock()
    result_no_html.html = None
    result_no_html.success = False
    result_no_html.url = 'https://x.com'
    mock_fetcher.fetch = mocker.AsyncMock(return_value=result_no_html)

    from tenacity import AsyncRetrying, stop_after_attempt, wait_none

    mocker.patch(
        'yosoi.core.pipeline.extraction.get_async_retryer',
        return_value=AsyncRetrying(stop=stop_after_attempt(1), wait=wait_none(), reraise=False),
    )

    result = await Pipeline._fetch(stub, 'https://x.com', mock_fetcher, max_retries=1)
    # After all retries exhausted with no HTML, returns None
    assert result is None


async def test_fetch_returns_none_on_unexpected_os_error(mocker):
    """OSError during fetch is caught and returns None rather than propagating."""
    stub = _make_pipeline_stub(mocker)
    mock_fetcher = mocker.MagicMock()
    mock_fetcher.fetch = mocker.AsyncMock(side_effect=OSError('connection refused'))

    from tenacity import AsyncRetrying, stop_after_attempt, wait_none

    mocker.patch(
        'yosoi.core.pipeline.extraction.get_async_retryer',
        return_value=AsyncRetrying(stop=stop_after_attempt(1), wait=wait_none(), reraise=False),
    )

    result = await Pipeline._fetch(stub, 'https://x.com', mock_fetcher, max_retries=1)
    assert result is None


# ---------------------------------------------------------------------------
# Coverage: _resolve_js_scripts and _discover_js_actions in pipeline.discovery
# ---------------------------------------------------------------------------


async def test_resolve_js_scripts_returns_hand_authored_scripts(mocker):
    """_resolve_js_scripts returns hand-authored scripts when no cached ones exist."""
    stub = _make_pipeline_stub(mocker)
    stub.js_storage = mocker.MagicMock()
    stub.js_storage.get_scripts = mocker.AsyncMock(return_value={})
    mocker.patch.object(stub, '_js_action_scripts', return_value=[('click_btn', 'return true;')])
    mocker.patch.object(stub.contract, 'undiscovered_action_fields', return_value={})

    result = await Pipeline._resolve_js_scripts(stub, 'example.com')
    assert result == {'click_btn': 'return true;'}


async def test_resolve_js_scripts_merges_cached_scripts(mocker):
    """_resolve_js_scripts merges cached JS scripts with hand-authored ones."""
    stub = _make_pipeline_stub(mocker)
    stub.js_storage = mocker.MagicMock()
    stub.js_storage.get_scripts = mocker.AsyncMock(return_value={'auto_field': 'return 42;'})
    mocker.patch.object(stub, '_js_action_scripts', return_value=[])
    mocker.patch.object(stub.contract, 'undiscovered_action_fields', return_value={'auto_field': {}})

    result = await Pipeline._resolve_js_scripts(stub, 'example.com')
    assert result == {'auto_field': 'return 42;'}


async def test_discover_js_actions_no_op_when_no_undiscovered(mocker):
    """_discover_js_actions returns immediately when all JS fields already have scripts."""
    stub = _make_pipeline_stub(mocker)
    mocker.patch.object(stub.contract, 'undiscovered_action_fields', return_value={})
    mock_fetcher = mocker.MagicMock()

    # Should return without calling js_storage at all
    await Pipeline._discover_js_actions(stub, 'https://x.com', 'x.com', mock_fetcher)
    # No exception = pass


async def test_discover_js_actions_skips_when_no_browser_support(mocker):
    """_discover_js_actions prints warning and returns when fetcher lacks browser support."""
    stub = _make_pipeline_stub(mocker)
    stub.js_storage = mocker.MagicMock()
    stub.js_storage.get_scripts = mocker.AsyncMock(return_value={})
    mocker.patch.object(stub.contract, 'undiscovered_action_fields', return_value={'btn': {'selector': '.btn'}})

    mock_fetcher = mocker.MagicMock()
    mock_fetcher.supports_browse = False

    await Pipeline._discover_js_actions(stub, 'https://x.com', 'x.com', mock_fetcher)
    stub.console.print.assert_called()
    printed = ' '.join(str(c) for c in stub.console.print.call_args_list)
    assert 'JS discovery skipped' in printed or 'warning' in printed.lower()


async def test_discover_via_mcp_success(mocker):
    """_discover_via_mcp delegates to MCP orchestrator and returns selectors."""
    stub = _make_pipeline_stub(mocker)
    stub.contract.get_selector_overrides = mocker.MagicMock(return_value={})
    mcp = mocker.MagicMock()
    mcp.discover_selectors = mocker.AsyncMock(return_value={'title': {'primary': 'h1'}})
    mocker.patch.object(stub, '_ensure_mcp_discovery', return_value=mcp)

    selectors, used_llm = await Pipeline._discover_via_mcp(stub, 'https://x.com', '<html/>')
    assert selectors == {'title': {'primary': 'h1'}}
    assert used_llm is True


async def test_discover_via_mcp_returns_none_on_exception(mocker):
    """_discover_via_mcp catches MCP failures and returns (None, True)."""
    stub = _make_pipeline_stub(mocker)
    stub.contract.get_selector_overrides = mocker.MagicMock(return_value={})
    mcp = mocker.MagicMock()
    mcp.discover_selectors = mocker.AsyncMock(side_effect=RuntimeError('timeout'))
    mocker.patch.object(stub, '_ensure_mcp_discovery', return_value=mcp)
    mocker.patch('yosoi.core.pipeline.discovery.observability')

    selectors, used_llm = await Pipeline._discover_via_mcp(stub, 'https://x.com', '<html/>')
    assert selectors is None
    assert used_llm is True


async def test_discover_js_actions_no_op_when_all_cached(mocker):
    """_discover_js_actions returns early when all undiscovered fields are already cached."""
    stub = _make_pipeline_stub(mocker)
    stub.js_storage = mocker.MagicMock()
    # All fields come back from cache — missing dict is empty → early return
    stub.js_storage.get_scripts = mocker.AsyncMock(return_value={'btn': 'return true;'})
    mocker.patch.object(stub.contract, 'undiscovered_action_fields', return_value={'btn': {'selector': '.btn'}})

    mock_fetcher = mocker.MagicMock()
    mock_fetcher.supports_browse = True

    await Pipeline._discover_js_actions(stub, 'https://x.com', 'x.com', mock_fetcher)
    # No orchestrator created, no discovery call
    assert not hasattr(stub, '_js_discovery_orchestrator') or stub._js_discovery_orchestrator is None


async def test_discover_js_actions_skips_when_fetcher_lacks_browse_method(mocker):
    """_discover_js_actions logs debug and returns when fetcher has no browse() method."""
    stub = _make_pipeline_stub(mocker)
    stub.js_storage = mocker.MagicMock()
    stub.js_storage.get_scripts = mocker.AsyncMock(return_value={})
    mocker.patch.object(stub.contract, 'undiscovered_action_fields', return_value={'btn': {'selector': '.btn'}})
    mock_logger = mocker.patch('yosoi.core.pipeline.discovery.logger')

    # supports_browse=True but no browse attribute → hits the hasattr branch
    mock_fetcher = mocker.MagicMock(spec=[])  # empty spec: no attributes at all
    mock_fetcher.supports_browse = True

    await Pipeline._discover_js_actions(stub, 'https://x.com', 'x.com', mock_fetcher)
    mock_logger.debug.assert_called()


async def test_discover_js_actions_runs_orchestrator_on_happy_path(mocker):
    """_discover_js_actions creates JsDiscoveryOrchestrator and calls discover() when all conditions met."""
    stub = _make_pipeline_stub(mocker)
    stub.js_storage = mocker.MagicMock()
    stub.js_storage.get_scripts = mocker.AsyncMock(return_value={})
    stub._js_discovery_orchestrator = None
    stub._llm_config = mocker.MagicMock()
    mocker.patch.object(stub.contract, 'undiscovered_action_fields', return_value={'btn': {'selector': '.btn'}})
    mocker.patch.object(stub.contract, 'coerce_field', return_value=None)

    # Fetcher that supports browse AND has a browse attribute
    mock_fetcher = mocker.MagicMock()
    mock_fetcher.supports_browse = True
    mock_fetcher.browse = mocker.MagicMock()

    # JsDiscoveryOrchestrator is imported locally inside _discover_js_actions:
    #   from yosoi.core.discovery.js_orchestrator import JsDiscoveryOrchestrator
    # For a local import we must patch the name in the source module.
    mock_orch = mocker.MagicMock()
    mock_orch.discover = mocker.AsyncMock()
    mocker.patch(
        'yosoi.core.discovery.js_orchestrator.JsDiscoveryOrchestrator',
        return_value=mock_orch,
    )
    mocker.patch('yosoi.core.pipeline.discovery.observability')

    await Pipeline._discover_js_actions(stub, 'https://x.com', 'x.com', mock_fetcher)

    # Orchestrator was instantiated and discover() was called
    mock_orch.discover.assert_awaited_once()
    call_kwargs = mock_orch.discover.call_args.kwargs
    assert call_kwargs['url'] == 'https://x.com'
    assert call_kwargs['domain'] == 'x.com'
    assert 'btn' in call_kwargs['fields']


# ---------------------------------------------------------------------------
# Coverage: discovery mixin — nested required fields, semantic-helper guards,
# escalation branches, and the AI retry callback (pipeline.discovery)
# ---------------------------------------------------------------------------


class _NestedPrice(ys.Contract):
    amount: float = ys.Price()
    currency: str = ys.Field(description='Currency symbol')


class _NestedContract(ys.Contract):
    name: str = ys.Title()
    price: _NestedPrice = ys.Field(description='Price info')  # type: ignore[assignment]


def test_required_discovery_fields_expands_nested_contract(mocker):
    """Nested Contract fields contribute flattened required child names."""
    stub = _make_pipeline_stub(mocker, _NestedContract)
    assert stub._required_discovery_fields() == {'name', 'price_amount', 'price_currency'}


def test_semantic_issues_empty_for_all_blank_items(mocker):
    """_semantic_issues short-circuits to [] when no extracted list item is truthy."""
    stub = _make_pipeline_stub(mocker)
    assert Pipeline._semantic_issues(stub, [{}, {}]) == []


def test_unsatisfied_required_empty_when_all_overridden(mocker):
    """Required fields fully subtracted by overrides → set() (the no-required guard)."""
    stub = _make_pipeline_stub(mocker)
    mocker.patch.object(
        stub.contract,
        'get_selector_overrides',
        return_value={'title': {'primary': '.t'}, 'price': {'primary': '.p'}},
    )
    assert Pipeline._unsatisfied_required(stub, {}) == set()


async def test_discover_via_mcp_returns_none_when_mcp_empty(mocker):
    """MCP returns no selectors → (None, True) without applying overrides."""
    stub = _make_pipeline_stub(mocker)
    mocker.patch.object(stub.contract, 'get_selector_overrides', return_value={'title': {}})
    mcp = mocker.MagicMock()
    mcp.discover_selectors = mocker.AsyncMock(return_value=None)
    mocker.patch.object(stub, '_ensure_mcp_discovery', return_value=mcp)
    selectors, used_llm = await Pipeline._discover_via_mcp(stub, 'https://x.com', '<html/>')
    assert selectors is None
    assert used_llm is True


async def test_escalate_to_mcp_returns_when_no_fresh_selectors(mocker):
    """No fresh selectors from MCP → unchanged tuple, not improved."""
    stub = _make_pipeline_stub(mocker)
    mcp = mocker.MagicMock()
    mcp.discover_selectors = mocker.AsyncMock(return_value={})
    mocker.patch.object(stub, '_ensure_mcp_discovery', return_value=mcp)
    verified = {'title': {'primary': 'h1'}}
    extracted, new_verified, root, improved = await Pipeline._escalate_to_mcp(
        stub, 'https://x.com', '<c/>', '<r/>', verified, 'old-root', {'k': 1}, {'title': 'Book'}, {'price'}
    )
    assert new_verified == verified
    assert extracted == {'title': 'Book'}
    assert root == {'k': 1}
    assert improved is False


async def test_escalate_to_mcp_adopts_mcp_root(mocker):
    """A resolvable MCP root replaces root_entry/container before re-extraction."""
    stub = _make_pipeline_stub(mocker)
    mcp = mocker.MagicMock()
    mcp.discover_selectors = mocker.AsyncMock(return_value={'price': {'primary': '.price'}})
    mocker.patch.object(stub, '_ensure_mcp_discovery', return_value=mcp)
    mocker.patch.object(stub, '_resolve_root', return_value={'primary': '.card'})
    mocker.patch.object(stub, '_root_value', return_value='.card')
    mocker.patch.object(stub, '_verify', return_value={'price': {'primary': '.price'}})
    mocker.patch.object(stub, '_extract', return_value={'title': 'Book', 'price': '9.99'})
    _extracted, _verified, root, improved = await Pipeline._escalate_to_mcp(
        stub, 'https://x.com', '<c/>', '<r/>', {'title': {}}, None, None, {'title': 'Book'}, {'price'}
    )
    assert root == {'primary': '.card'}
    assert improved is True


async def test_escalate_to_mcp_rejects_candidate_that_collapses_item_count(mocker):
    """MCP escalation must not replace a good multi-item extraction with a broad body row."""
    stub = _make_pipeline_stub(mocker)
    mcp = mocker.MagicMock()
    mcp.discover_selectors = mocker.AsyncMock(
        return_value={'root': {'primary': 'body'}, 'title': {'primary': 'body'}, 'price': {'primary': '.price'}}
    )
    mocker.patch.object(stub, '_ensure_mcp_discovery', return_value=mcp)
    mocker.patch.object(stub, '_resolve_root', return_value={'primary': 'body'})
    mocker.patch.object(stub, '_root_value', return_value='body')
    mocker.patch.object(stub, '_verify', return_value={'title': {'primary': 'body'}, 'price': {'primary': '.price'}})
    mocker.patch.object(
        stub,
        '_unsatisfied_required',
        side_effect=[{'title'}, set()],
    )
    original = [{'title': 'Book', 'price': '9.99'}, {'title': 'Pen', 'price': '1.99'}]
    candidate = {'title': 'Whole page text', 'price': '9.99'}
    mocker.patch.object(stub, '_extract', return_value=candidate)
    verified = {'title': {'primary': '.name'}, 'price': {'primary': '.price'}}

    extracted, new_verified, root, improved = await Pipeline._escalate_to_mcp(
        stub, 'https://x.com', '<c/>', '<r/>', verified, '.card', {'primary': '.card'}, original, {'title'}
    )

    assert extracted is original
    assert new_verified is verified
    assert root == {'primary': '.card'}
    assert improved is False


async def test_maybe_escalate_noop_when_all_required_met(mocker):
    """No unmet required field → early return, MCP escalation never invoked."""
    stub = _make_pipeline_stub(mocker)
    esc = mocker.patch.object(stub, '_escalate_to_mcp')
    current = {'title': 'Book', 'price': '9.99'}
    out = await Pipeline._maybe_escalate(
        stub, 'https://x.com', 'x.com', '<c/>', '<r/>', {'title': {}}, None, None, current
    )
    assert out == (current, {'title': {}}, None, None, False)
    esc.assert_not_called()


async def test_maybe_escalate_saves_strategy_on_improvement(mocker):
    """When escalation improves extraction, the 'mcp' strategy is persisted for the domain."""
    stub = _make_pipeline_stub(mocker)
    mocker.patch.object(
        stub,
        '_escalate_to_mcp',
        return_value=({'title': 'Book', 'price': '9.99'}, {'price': {}}, {'primary': '.card'}, True),
    )
    mocker.patch.object(stub, '_root_value', return_value='.card')
    mocker.patch('yosoi.core.pipeline.discovery.observability')
    _cur, _ver, _root, _container, improved = await Pipeline._maybe_escalate(
        stub, 'https://x.com', 'x.com', '<c/>', '<r/>', {'title': {}}, None, None, {'title': 'Book'}
    )
    assert improved is True
    stub._discovery_strategy.save.assert_awaited_once_with('x.com', stub._contract_sig, 'mcp')


async def test_discover_logs_retry_then_succeeds_on_second_attempt(mocker):
    """First AI attempt fails → retry callback fires → second attempt succeeds."""
    from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_none

    stub = _make_pipeline_stub(mocker)
    mocker.patch.object(stub.contract, 'get_selector_overrides', return_value={})
    mocker.patch.object(stub.contract, 'field_descriptions', return_value={'title': 'The title'})
    stub.discovery.discover_selectors = mocker.AsyncMock(side_effect=[None, {'title': {'primary': 'h1'}}])

    def _fake_retryer(*, max_attempts, wait_min, wait_max, exceptions, log_callback, reraise):
        # Faithful to get_async_retryer but with no wait — keeps before_sleep wired
        # so the in-method retry-log callback is exercised.
        return AsyncRetrying(
            stop=stop_after_attempt(max_attempts),
            wait=wait_none(),
            retry=retry_if_exception_type(exceptions),
            before_sleep=log_callback,
            reraise=reraise,
        )

    mocker.patch('yosoi.core.pipeline.discovery.get_async_retryer', side_effect=_fake_retryer)
    mocker.patch('yosoi.core.pipeline.discovery.observability')

    selectors, used_llm = await Pipeline._discover(stub, 'https://x.com', '<html/>', max_retries=2)
    assert selectors == {'title': {'primary': 'h1'}}
    assert used_llm is True
    assert any('retry' in str(c).lower() for c in stub.console.print.call_args_list)


async def test_pipeline_async_context_manager_closes_client(mocker):
    """__aenter__ returns self; __aexit__ closes the HTTP client and finalizes downloads."""
    stub = _make_pipeline_stub(mocker)
    stub._client = mocker.AsyncMock()
    finalize = mocker.patch.object(stub, '_finalize_downloads')

    entered = await Pipeline.__aenter__(stub)
    assert entered is stub
    await Pipeline.__aexit__(stub, None, None, None)

    stub._client.aclose.assert_awaited_once()
    finalize.assert_called_once()


async def test_process_urls_with_live_drives_status_callbacks(mocker):
    """_process_urls_with_live wires per-URL on_start/on_complete into the Live table."""
    from rich.console import Console

    stub = _make_pipeline_stub(mocker)
    stub.console = Console(quiet=True)  # real console so the Rich Live context works

    seen: dict[str, object] = {}

    async def _fake_concurrent(urls, **kwargs):
        # Exercise both status callbacks (Running → Done / Failed transitions).
        await kwargs['on_start'](urls[0])
        await kwargs['on_complete'](urls[0], True, 1.5)
        await kwargs['on_complete'](urls[1], False, 2.0)
        seen['workers'] = kwargs['max_workers']
        return {'successful': [urls[0]], 'failed': [urls[1]], 'skipped': []}

    mocker.patch.object(stub, '_process_urls_concurrent', side_effect=_fake_concurrent)

    result = await Pipeline._process_urls_with_live(
        stub,
        ['https://a.com', 'https://b.com'],
        force=False,
        skip_verification=False,
        fetcher_type='simple',
        max_fetch_retries=2,
        max_discovery_retries=3,
        output_format=['json'],
        effective_workers=2,
    )

    assert seen['workers'] == 2
    assert result == {'successful': ['https://a.com'], 'failed': ['https://b.com'], 'skipped': []}


# ---------------------------------------------------------------------------
# Coverage: real-behavior tests for selector/root helpers, download merging,
# cached-fetch error handling, and verification reporting across the mixins.
# Each asserts an observable outcome, not merely that a line executed.
# ---------------------------------------------------------------------------


def test_root_value_reads_typed_selector_and_guards_empties():
    """_root_value pulls the value from a typed {primary:{value}} entry, and returns
    None for empty/non-string primaries rather than leaking a bad selector."""
    assert Pipeline._root_value({'primary': '.card'}) == '.card'
    assert Pipeline._root_value({'primary': {'value': '.card'}}) == '.card'
    assert Pipeline._root_value({'primary': {'value': ''}}) is None
    assert Pipeline._root_value({'primary': None}) is None  # final guard: not str, not dict


def test_pop_root_handles_nested_primary_and_pops_in_place():
    """_pop_root removes the root entry and accepts a nested {primary:{value}} form."""
    sels = {'root': {'primary': {'value': '.card'}}, 'title': {'primary': 'h1'}}
    entry = Pipeline._pop_root(sels)
    assert entry == {'primary': {'value': '.card'}}
    assert 'root' not in sels  # removed in place
    assert Pipeline._pop_root({'root': {'primary': {'value': ''}}}) is None  # empty value → no root


def test_selectors_with_root_reattaches_root_entry():
    """_selectors_with_root re-attaches the root entry for persistence without mutating input."""
    verified = {'title': {'primary': 'h1'}}
    out = Pipeline._selectors_with_root(verified, {'primary': '.card'})
    assert out == {'title': {'primary': 'h1'}, 'root': {'primary': '.card'}}
    assert 'root' not in verified  # original untouched
    # no root entry → unchanged copy
    assert Pipeline._selectors_with_root(verified, None) == verified


def test_merge_downloads_injects_file_values_into_each_shape(mocker):
    """_merge_downloads folds ys.File() results into dict, list, and None extractions."""
    dl = mocker.MagicMock()
    dl.value = '/files/report.pdf'
    downloads = {'report': dl}
    # no downloads → extraction returned as-is
    assert Pipeline._merge_downloads({'a': 1}, None) == {'a': 1}
    # extraction is None → fresh dict of download values
    assert Pipeline._merge_downloads(None, downloads) == {'report': '/files/report.pdf'}
    # single dict → merged
    assert Pipeline._merge_downloads({'a': 1}, downloads) == {'a': 1, 'report': '/files/report.pdf'}
    # list → merged into every item
    assert Pipeline._merge_downloads([{'a': 1}, {'a': 2}], downloads) == [
        {'a': 1, 'report': '/files/report.pdf'},
        {'a': 2, 'report': '/files/report.pdf'},
    ]


def test_extract_returns_none_when_container_yields_no_items(mocker):
    """Multi-item extraction with a container selector returns None (not []) when the
    extractor finds nothing — the caller treats None as 'extraction failed'."""
    stub = _make_pipeline_stub(mocker)
    stub.extractor.extract_items = mocker.MagicMock(return_value=[])
    result = Pipeline._extract(stub, 'https://x.com', '<html/>', {'title': {'primary': 'h1'}}, '.card')
    assert result is None
    stub.extractor.extract_items.assert_called_once()


async def test_fetch_and_clean_for_cache_returns_none_on_fetch_error(mocker):
    """A generic fetch error during cache verification is swallowed into None (skip),
    so a cache hit degrades gracefully instead of crashing the run."""
    stub = _make_pipeline_stub(mocker)
    mocker.patch.object(stub, '_fetch', side_effect=RuntimeError('network down'))
    mocker.patch('yosoi.core.pipeline.cache.observability')
    result = await Pipeline._fetch_and_clean_for_cache(stub, 'https://x.com', mocker.MagicMock())
    assert result is None


async def test_fetch_and_clean_for_cache_propagates_bot_detection(mocker):
    """BotDetectionError is NOT swallowed during cache verification — it must surface
    so the caller can rotate proxy/profile (fail loud, per the project rules)."""
    stub = _make_pipeline_stub(mocker)
    mocker.patch.object(stub, '_fetch', side_effect=BotDetectionError('https://x.com', 403, ['captcha']))
    mocker.patch('yosoi.core.pipeline.cache.observability')
    with pytest.raises(BotDetectionError):
        await Pipeline._fetch_and_clean_for_cache(stub, 'https://x.com', mocker.MagicMock())


async def test_record_fetch_strategy_noop_without_level_distribution(mocker):
    """With no recorded level distribution, the JSFetcher's selector level is left
    untouched — we never persist an empty/guessed level."""
    from yosoi.core.fetcher.waterfall import JSFetcher

    stub = _make_pipeline_stub(mocker)
    stub._last_level_distribution = {}  # nothing verified yet
    fetcher = mocker.Mock(spec=JSFetcher)
    await Pipeline._record_fetch_strategy_selector_level(stub, fetcher, 'example.com')
    fetcher.update_selector_level.assert_not_called()


def test_print_verification_failure_lists_every_failed_selector(mocker):
    """_print_verification_failure surfaces each field and each tried selector with its
    level and reason — so a human can see exactly what was attempted."""
    stub = _make_pipeline_stub(mocker)
    failure = mocker.MagicMock(level='css', selector='h1.title', reason='no_match')
    field_result = mocker.MagicMock(failed_selectors=[failure])
    result = mocker.MagicMock(results={'title': field_result})
    Pipeline._print_verification_failure(stub, result)
    printed = ' '.join(str(c) for c in stub.console.print.call_args_list)
    assert 'title' in printed
    assert 'h1.title' in printed
    assert 'no_match' in printed


async def test_discover_fails_closed_when_retryer_cannot_be_built(mocker):
    """If the retryer itself raises a transient error, _discover returns (None, False) —
    it fails closed rather than propagating, consistent with fail-fast/no-fallback."""
    stub = _make_pipeline_stub(mocker)
    mocker.patch.object(stub.contract, 'get_selector_overrides', return_value={})
    mocker.patch.object(stub.contract, 'field_descriptions', return_value={'title': 'The title'})
    mocker.patch('yosoi.core.pipeline.discovery.get_async_retryer', side_effect=ValueError('bad retry config'))
    mocker.patch('yosoi.core.pipeline.discovery.observability')
    selectors, used_llm = await Pipeline._discover(stub, 'https://x.com', '<html/>', max_retries=2)
    assert selectors is None
    assert used_llm is False


async def test_semantic_refine_stops_when_reextraction_goes_empty(mocker):
    """If a re-discovered, re-verified selector set extracts nothing, _semantic_refine
    breaks out and returns the prior extraction rather than overwriting it with empty."""
    stub = _make_pipeline_stub(mocker)
    # First semantic pass: one issue; second call (post-loop): none left to report.
    issue = mocker.MagicMock(field='price')
    issue.as_feedback.return_value = 'price looks wrong'
    mocker.patch.object(stub, '_semantic_issues', side_effect=[[issue], []])
    stub.discovery.discover_selectors = mocker.AsyncMock(return_value={'price': {'primary': '.p'}})
    mocker.patch.object(stub, '_verify', return_value={'price': {'primary': '.p'}})
    mocker.patch.object(stub, '_extract', return_value=None)  # re-extraction yields nothing
    mocker.patch.object(stub, '_selector_values', return_value=())

    original = {'title': 'Book', 'price': '$5'}
    extracted, _verified = await Pipeline._semantic_refine(
        stub, 'https://x.com', '<clean/>', '<raw/>', {'price': {}}, '.card', original, max_retries=3
    )
    assert extracted is original  # prior extraction preserved, not clobbered by the empty re-extract
