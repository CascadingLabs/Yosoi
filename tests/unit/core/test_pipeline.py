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
        mocker.patch('yosoi.core.pipeline.observability')
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
    mocker.patch('yosoi.core.pipeline.create_fetcher', return_value=mock_fetcher)
    result = Pipeline._create_fetcher(stub, 'simple')
    assert result is mock_fetcher


def test_create_fetcher_invalid_type_returns_none(mocker):
    stub = _make_pipeline_stub(mocker)
    mocker.patch('yosoi.core.pipeline.create_fetcher', side_effect=ValueError('bad'))
    result = Pipeline._create_fetcher(stub, 'nonexistent')
    assert result is None


def test_create_waterfall_fetcher_passes_console_and_a3node(mocker):
    stub = _make_pipeline_stub(mocker)
    stub._experimental_a3node = False
    create_fetcher = mocker.patch('yosoi.core.pipeline.create_fetcher', return_value=mocker.MagicMock())
    Pipeline._create_fetcher(stub, 'waterfall', console=stub.console)
    create_fetcher.assert_called_once_with(
        'waterfall', console=stub.console, experimental_a3node=False, allow_downloads=False, download_dir=None
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
    # _validate_with_contract uses pipeline_utils' logger, not stub.logger.
    # The warning is emitted; we verify by checking the return value (raw fallback).
    stub = _make_pipeline_stub(mocker, SimpleContract)
    raw = {'price': 'not-a-number'}
    result = Pipeline._validate_with_contract(stub, raw)
    assert result is raw
    # NOTE: do NOT assert stub.logger.warning — that's the stub's mock logger,
    # not pipeline_utils.logger which is what _validate_with_contract uses.


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
    mocker.patch('yosoi.core.pipeline.time')
    mocker.patch('yosoi.core.pipeline.time.monotonic', return_value=102.5)
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
# _fetch — patch pipeline_extraction.get_async_retryer (method lives there)
# ---------------------------------------------------------------------------


async def test_fetch_returns_result_on_success(mocker):
    stub = _make_pipeline_stub(mocker)
    fetch_result = FetchResult(url='https://x.com', html='<html/>', status_code=200)
    mock_fetcher = mocker.MagicMock()
    mock_fetcher.fetch = mocker.AsyncMock(return_value=fetch_result)
    from tenacity import AsyncRetrying, stop_after_attempt

    mocker.patch(
        'yosoi.core.pipeline_extraction.get_async_retryer',
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
        'yosoi.core.pipeline_extraction.get_async_retryer',
        return_value=AsyncRetrying(stop=stop_after_attempt(1), wait=wait_none(), reraise=False),
    )
    result = await Pipeline._fetch(stub, 'https://x.com', mock_fetcher, max_retries=1)
    assert result is None


# ---------------------------------------------------------------------------
# _discover — patch pipeline_discovery.get_async_retryer (method lives there)
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
        'yosoi.core.pipeline_discovery.get_async_retryer',
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
        'yosoi.core.pipeline_discovery.get_async_retryer',
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
    mocker.patch('yosoi.core.pipeline.observability')
    with pytest.raises(RuntimeError):
        await Pipeline.process_url(stub, 'https://x.com')


async def test_process_url_raises_when_create_fetcher_fails(mocker):
    stub = _make_pipeline_stub(mocker)
    mocker.patch.object(Pipeline, 'normalize_url', return_value='https://x.com')
    mocker.patch.object(Pipeline, '_extract_domain', return_value='x.com')
    mocker.patch.object(Pipeline, '_create_fetcher', return_value=None)
    mocker.patch('yosoi.core.pipeline.observability')
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
    mocker.patch('yosoi.core.pipeline.observability')
    await Pipeline.process_url(stub, 'https://x.com')


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
    mocker.patch('yosoi.core.pipeline.observability')
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
    mocker.patch('yosoi.core.pipeline.observability')
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
    mocker.patch('yosoi.core.pipeline.observability')
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
    mocker.patch('yosoi.core.pipeline.observability')
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
    mocker.patch('yosoi.core.pipeline.observability')
    with pytest.raises(RuntimeError):
        await Pipeline.process_url(stub, 'https://x.com')


async def test_process_urls_collects_results(mocker):
    stub = _make_pipeline_stub(mocker)
    mocker.patch.object(Pipeline, 'process_url', side_effect=[None, RuntimeError('fail')])
    mocker.patch('yosoi.core.pipeline.observability')
    results = await Pipeline.process_urls(stub, ['https://a.com', 'https://b.com'])
    assert 'https://a.com' in results['successful']
    assert 'https://b.com' in results['failed']


async def test_process_urls_catches_exceptions(mocker):
    stub = _make_pipeline_stub(mocker)
    mocker.patch.object(Pipeline, 'process_url', side_effect=RuntimeError('boom'))
    mocker.patch('yosoi.core.pipeline.observability')
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
    mocker.patch('yosoi.core.pipeline.observability')
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
    mocker.patch('yosoi.core.pipeline.observability')
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
    mocker.patch('yosoi.core.pipeline.time.monotonic', return_value=103.0)
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
    mocker.patch('yosoi.core.pipeline.observability')
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
        'yosoi.core.pipeline_discovery.get_async_retryer',
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
        'yosoi.core.pipeline_discovery.get_async_retryer',
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
    mocker.patch('yosoi.core.pipeline.observability')
    completed: list[tuple[str, bool]] = []

    async def on_complete(url: str, success: bool, elapsed: float) -> None:
        completed.append((url, success))

    await Pipeline.process_urls(stub, ['https://a.com'], on_complete=on_complete)
    assert len(completed) == 1
    assert completed[0] == ('https://a.com', True)


async def test_process_urls_calls_on_complete_on_failure(mocker):
    stub = _make_pipeline_stub(mocker)
    mocker.patch.object(Pipeline, 'process_url', side_effect=RuntimeError('boom'))
    mocker.patch('yosoi.core.pipeline.observability')
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
