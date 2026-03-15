"""Unit tests for Pipeline methods."""

import yosoi as ys
from yosoi.core.pipeline import Pipeline
from yosoi.models.contract import Contract
from yosoi.models.results import FetchResult, FieldVerificationResult, VerificationResult
from yosoi.utils.exceptions import BotDetectionError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class SimpleContract(Contract):
    title: str = ys.Title()
    price: float = ys.Price()


def _make_pipeline_stub(mocker, contract=None):
    """Create a minimal Pipeline instance without calling __init__."""
    stub = Pipeline.__new__(Pipeline)
    stub.contract = contract or SimpleContract
    stub.console = mocker.MagicMock()
    stub.logger = mocker.MagicMock()
    stub.cleaner = mocker.MagicMock()
    stub.discovery = mocker.MagicMock()
    stub.discovery.discover_selectors = mocker.AsyncMock()
    stub.verifier = mocker.MagicMock()
    stub.extractor = mocker.MagicMock()
    stub.storage = mocker.MagicMock()
    stub.storage.load_snapshots.return_value = None
    stub.tracker = mocker.MagicMock()
    stub.debug = mocker.MagicMock()
    stub.debug_mode = False
    stub.output_formats = ['json']
    stub.force = False
    from yosoi.models.selectors import SelectorLevel

    stub.selector_level = SelectorLevel.CSS
    return stub


def _mock_async_client(mocker, *, raise_on_head=None):
    """Patch httpx.AsyncClient for normalize_url tests.

    Returns a mock client whose `.head()` either succeeds or raises.
    """
    mock_client = mocker.AsyncMock()
    if raise_on_head is not None:
        mock_client.__aenter__.return_value.head.side_effect = raise_on_head
    mocker.patch('yosoi.core.pipeline.httpx.AsyncClient', return_value=mock_client)
    return mock_client


# ---------------------------------------------------------------------------
# normalize_url
# ---------------------------------------------------------------------------


async def test_normalize_url_already_https(mocker):
    stub = _make_pipeline_stub(mocker)
    assert await Pipeline.normalize_url(stub, 'https://example.com') == 'https://example.com'


async def test_normalize_url_already_http(mocker):
    stub = _make_pipeline_stub(mocker)
    assert await Pipeline.normalize_url(stub, 'http://example.com') == 'http://example.com'


async def test_normalize_url_adds_https_on_success(mocker):
    stub = _make_pipeline_stub(mocker)
    _mock_async_client(mocker)  # head() succeeds
    result = await Pipeline.normalize_url(stub, 'example.com')
    assert result == 'https://example.com'


async def test_normalize_url_falls_back_to_http_on_error(mocker):
    import httpx

    stub = _make_pipeline_stub(mocker)
    _mock_async_client(mocker, raise_on_head=httpx.HTTPError('fail'))
    result = await Pipeline.normalize_url(stub, 'example.com')
    assert result == 'http://example.com'


# ---------------------------------------------------------------------------
# _extract_domain
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Pipeline __init__ accepts string
# ---------------------------------------------------------------------------


def test_pipeline_accepts_model_string(mocker):
    """Pipeline(llm_config='groq:llama', ...) auto-resolves the string."""
    mocker.patch('yosoi.storage.persistence.init_yosoi')
    mocker.patch('yosoi.storage.tracking.get_tracking_path', return_value='/tmp/tracking.json')
    mocker.patch('yosoi.utils.files.is_initialized', return_value=True)
    mocker.patch('yosoi.utils.logging.setup_local_logging', return_value='/tmp/test.log')
    mocker.patch('yosoi.core.discovery.field_agent.Agent')
    mocker.patch('yosoi.core.discovery.field_agent.create_model')

    p = Pipeline(llm_config='groq:llama-3.3-70b-versatile', contract=SimpleContract)
    assert p.discovery is not None


# ---------------------------------------------------------------------------
# _create_fetcher
# ---------------------------------------------------------------------------


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
    stub.console.print.assert_called()


# ---------------------------------------------------------------------------
# _clean
# ---------------------------------------------------------------------------


def test_clean_returns_cleaned_html(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.cleaner.clean_html.return_value = '<html><body>Clean</body></html>'
    result_obj = FetchResult(url='https://x.com', html='<html>Dirty</html>')
    result = Pipeline._clean(stub, 'https://x.com', result_obj)
    assert result == '<html><body>Clean</body></html>'
    stub.debug.save_debug_html.assert_called_once()


def test_clean_returns_none_when_cleaner_returns_empty(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.cleaner.clean_html.return_value = ''
    result_obj = FetchResult(url='https://x.com', html='<html>x</html>')
    result = Pipeline._clean(stub, 'https://x.com', result_obj)
    assert result is None


# ---------------------------------------------------------------------------
# _verify
# ---------------------------------------------------------------------------


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
    # title verified, price failed
    results = {
        'title': FieldVerificationResult(field_name='title', status='verified', working_level='primary', selector='h1'),
        'price': FieldVerificationResult(field_name='price', status='failed', working_level=None, selector=None),
    }
    vr = VerificationResult(total_fields=2, verified_count=1, results=results)
    stub.verifier.verify.return_value = vr
    selectors = {'title': {'primary': 'h1'}, 'price': {'primary': '.p'}}
    Pipeline._verify(stub, 'https://x.com', '<html/>', selectors, skip_verification=False)
    # _print_partial_failure should be called (1 failure)
    stub.console.print.assert_called()


# ---------------------------------------------------------------------------
# _extract
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# _validate_with_contract
# ---------------------------------------------------------------------------


def test_pipeline_validate_with_contract_success(mocker):
    stub = _make_pipeline_stub(mocker, SimpleContract)
    result = Pipeline._validate_with_contract(stub, {'title': '  Book  ', 'price': '£9.99'})
    assert result['title'] == 'Book'
    assert result['price'] == 9.99


def test_pipeline_validate_with_contract_fallback_on_error(mocker):
    stub = _make_pipeline_stub(mocker, SimpleContract)
    raw = {'price': 'not-a-number'}
    result = Pipeline._validate_with_contract(stub, raw)
    assert result is raw
    stub.logger.warning.assert_called_once()


def test_validate_with_contract_injects_source_url(mocker):
    class UrlContract(Contract):
        title: str = ys.Title()

    stub = _make_pipeline_stub(mocker, UrlContract)
    result = Pipeline._validate_with_contract(stub, {'title': 'hello'}, url='https://example.com')
    assert result['title'] == 'hello'


# ---------------------------------------------------------------------------
# _save_and_track
# ---------------------------------------------------------------------------


def test_save_and_track_saves_selectors_and_content(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.tracker.record_url.return_value = {'llm_calls': 1, 'url_count': 1}
    Pipeline._save_and_track(
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


def test_save_and_track_skips_content_when_none(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.tracker.record_url.return_value = {'llm_calls': 1, 'url_count': 1}
    Pipeline._save_and_track(
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


def test_save_and_track_passes_elapsed_to_record_url(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.tracker.record_url.return_value = {'llm_calls': 1, 'url_count': 1}
    Pipeline._save_and_track(
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


# ---------------------------------------------------------------------------
# _track_cached_success
# ---------------------------------------------------------------------------


def test_track_cached_success_calls_record_url(mocker):
    stub = _make_pipeline_stub(mocker)
    stub._url_start = 100.0
    mocker.patch('yosoi.core.pipeline.time')
    mocker.patch('yosoi.core.pipeline.time.monotonic', return_value=102.5)
    stub.tracker.record_url.return_value = {'llm_calls': 0, 'url_count': 3}
    Pipeline._track_cached_success(stub, 'https://x.com', 'x.com')
    call_args = stub.tracker.record_url.call_args
    assert call_args[0] == ('https://x.com',)
    assert call_args[1]['used_llm'] is False
    assert call_args[1]['level_distribution'] is None
    assert call_args[1]['elapsed'] is not None


# ---------------------------------------------------------------------------
# _print_tracking_stats
# ---------------------------------------------------------------------------


def test_print_tracking_stats_shows_efficiency(mocker):
    stub = _make_pipeline_stub(mocker)
    Pipeline._print_tracking_stats(stub, 'example.com', {'llm_calls': 2, 'url_count': 10})
    calls = [str(c) for c in stub.console.print.call_args_list]
    joined = ' '.join(calls)
    assert 'llm_calls' in joined.lower() or '2' in joined or 'LLM' in joined


def test_print_tracking_stats_no_efficiency_when_zero_llm(mocker):
    stub = _make_pipeline_stub(mocker)
    Pipeline._print_tracking_stats(stub, 'example.com', {'llm_calls': 0, 'url_count': 5})
    # Should not divide by zero - just check it runs without error
    stub.console.print.assert_called()


# ---------------------------------------------------------------------------
# _handle_bot_detection
# ---------------------------------------------------------------------------


def test_handle_bot_detection_prints_info(mocker):
    from yosoi.utils.exceptions import BotDetectionError

    stub = _make_pipeline_stub(mocker)
    err = BotDetectionError(url='https://x.com', status_code=403, indicators=['captcha'])
    Pipeline._handle_bot_detection(stub, err, attempt=1, max_retries=2)
    stub.console.print.assert_called()


def test_handle_bot_detection_prints_abort_when_exhausted(mocker):
    from yosoi.utils.exceptions import BotDetectionError

    stub = _make_pipeline_stub(mocker)
    err = BotDetectionError(url='https://x.com', status_code=403, indicators=['cloudflare'])
    Pipeline._handle_bot_detection(stub, err, attempt=2, max_retries=2)
    calls = [str(c) for c in stub.console.print.call_args_list]
    assert any('ABORTING' in c or 'playwright' in c.lower() for c in calls)


# ---------------------------------------------------------------------------
# _extract_with_cached
# ---------------------------------------------------------------------------


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
    """Stale container selector must return cache_valid=False, not silently fail."""
    stub = _make_pipeline_stub(mocker)
    stub.cleaner.clean_html.return_value = '<html><body><h1>Title</h1></body></html>'
    stub.verifier._test_selector = mocker.MagicMock(return_value=(False, 'no_elements_found'))

    mock_fetcher = mocker.MagicMock()
    mock_fetcher.fetch = mocker.AsyncMock(
        return_value=FetchResult(url='https://x.com', html='<html><body><h1>Title</h1></body></html>')
    )

    # Patch _resolve_root to return a non-None stale container string
    mocker.patch.object(stub, '_resolve_root', return_value='article.product_pod')

    items, cache_valid = await Pipeline._extract_with_cached(
        stub, 'https://x.com', mock_fetcher, {'title': {'primary': 'h1'}}, False
    )

    assert cache_valid is False
    assert items is None


# ---------------------------------------------------------------------------
# _fetch
# ---------------------------------------------------------------------------


async def test_fetch_returns_result_on_success(mocker):
    stub = _make_pipeline_stub(mocker)
    fetch_result = FetchResult(url='https://x.com', html='<html/>', status_code=200)
    mock_fetcher = mocker.MagicMock()
    mock_fetcher.fetch = mocker.AsyncMock(return_value=fetch_result)
    # Use a real async retryer to test the flow properly
    from tenacity import AsyncRetrying, stop_after_attempt

    mocker.patch(
        'yosoi.core.pipeline.get_async_retryer',
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
        'yosoi.core.pipeline.get_async_retryer',
        return_value=AsyncRetrying(stop=stop_after_attempt(1), wait=wait_none(), reraise=False),
    )
    result = await Pipeline._fetch(stub, 'https://x.com', mock_fetcher, max_retries=1)
    assert result is None


# ---------------------------------------------------------------------------
# _discover
# ---------------------------------------------------------------------------


async def test_discover_returns_overrides_when_no_fields_need_discovery(mocker):
    stub = _make_pipeline_stub(mocker)

    class OverrideContract(Contract):
        title: str = ys.Field(selector='.title')  # type: ignore[assignment]

    stub.contract = OverrideContract
    stub.contract.get_selector_overrides = mocker.MagicMock(return_value={'title': {'primary': '.title'}})
    stub.contract.field_descriptions = mocker.MagicMock(return_value={})
    stub.debug.save_debug_selectors = mocker.MagicMock()

    selectors, used_llm = await Pipeline._discover(stub, 'https://x.com', '<html/>', max_retries=1)
    assert selectors == {'title': {'primary': '.title'}}
    assert used_llm is False
    stub.discovery.discover_selectors.assert_not_called()


async def test_discover_returns_selectors_on_ai_success(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.contract.get_selector_overrides = mocker.MagicMock(return_value={})
    stub.contract.field_descriptions = mocker.MagicMock(return_value={'title': 'The title'})
    stub.discovery.discover_selectors = mocker.AsyncMock(return_value={'title': {'primary': 'h1'}})
    stub.debug.save_debug_selectors = mocker.MagicMock()

    from tenacity import AsyncRetrying, stop_after_attempt, wait_none

    mocker.patch(
        'yosoi.core.pipeline.get_async_retryer',
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
        'yosoi.core.pipeline.get_async_retryer',
        return_value=AsyncRetrying(stop=stop_after_attempt(1), wait=wait_none(), reraise=False),
    )

    selectors, used_llm = await Pipeline._discover(stub, 'https://x.com', '<html/>', max_retries=1)
    assert selectors is None
    assert used_llm is False


# ---------------------------------------------------------------------------
# _discover_with_escalation
# ---------------------------------------------------------------------------


async def test_discover_with_escalation_succeeds_at_css(mocker):
    """When _discover succeeds at CSS, no escalation occurs."""
    stub = _make_pipeline_stub(mocker)
    mocker.patch.object(Pipeline, '_discover', return_value=({'title': {'primary': 'h1'}}, True))
    selectors, used_llm = await Pipeline._discover_with_escalation(stub, 'https://x.com', '<html/>')
    assert selectors == {'title': {'primary': 'h1'}}
    assert used_llm is True
    # _discover called once only (CSS level)
    Pipeline._discover.assert_called_once()


async def test_discover_with_escalation_delegates_to_discover(mocker):
    """_discover_with_escalation now delegates to _discover once.

    Per-field escalation (CSS→XPath→…) is handled inside DiscoveryOrchestrator,
    not in the pipeline-level loop.
    """
    from yosoi.models.selectors import SelectorLevel

    stub = _make_pipeline_stub(mocker)
    stub.selector_level = SelectorLevel.XPATH
    mocker.patch.object(
        Pipeline,
        '_discover',
        return_value=({'title': {'primary': '//h1'}}, True),
    )
    selectors, used_llm = await Pipeline._discover_with_escalation(stub, 'https://x.com', '<html/>')
    assert selectors is not None
    assert used_llm is True
    # Only one call — orchestrator handles the per-field level loop internally
    Pipeline._discover.assert_called_once()


async def test_discover_with_escalation_does_not_retry_beyond_max_level(mocker):
    """Does not escalate past self.selector_level even if all attempts fail."""
    from yosoi.models.selectors import SelectorLevel

    stub = _make_pipeline_stub(mocker)
    stub.selector_level = SelectorLevel.CSS  # only CSS allowed
    mocker.patch.object(Pipeline, '_discover', return_value=(None, False))
    selectors, _used_llm = await Pipeline._discover_with_escalation(stub, 'https://x.com', '<html/>')
    assert selectors is None
    Pipeline._discover.assert_called_once()  # no escalation beyond CSS


async def test_discover_with_escalation_returns_none_when_all_levels_fail(mocker):
    """Returns None when every level fails."""
    from yosoi.models.selectors import SelectorLevel

    stub = _make_pipeline_stub(mocker)
    stub.selector_level = SelectorLevel.XPATH
    mocker.patch.object(Pipeline, '_discover', return_value=(None, False))
    selectors, used_llm = await Pipeline._discover_with_escalation(stub, 'https://x.com', '<html/>')
    assert selectors is None
    assert used_llm is False


# ---------------------------------------------------------------------------
# process_url
# ---------------------------------------------------------------------------


async def test_process_url_raises_when_fetch_fails(mocker):
    import pytest

    stub = _make_pipeline_stub(mocker)
    mocker.patch.object(Pipeline, 'normalize_url', return_value='https://x.com')
    mocker.patch.object(Pipeline, '_extract_domain', return_value='x.com')
    mocker.patch.object(Pipeline, '_create_fetcher', return_value=mocker.MagicMock())
    stub.storage.load_selectors.return_value = None
    mocker.patch.object(Pipeline, '_fetch', return_value=None)
    mocker.patch('yosoi.core.pipeline.logfire')
    with pytest.raises(RuntimeError):
        await Pipeline.process_url(stub, 'https://x.com')


async def test_process_url_raises_when_create_fetcher_fails(mocker):
    import pytest

    stub = _make_pipeline_stub(mocker)
    mocker.patch.object(Pipeline, 'normalize_url', return_value='https://x.com')
    mocker.patch.object(Pipeline, '_extract_domain', return_value='x.com')
    mocker.patch.object(Pipeline, '_create_fetcher', return_value=None)
    mocker.patch('yosoi.core.pipeline.logfire')
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
    stub.tracker.record_url.return_value = {
        'llm_calls': 0,
        'url_count': 1,
        'level_distribution': {},
        'total_elapsed': 0.0,
        'partial_rediscovery_count': 0,
    }
    mocker.patch('yosoi.core.pipeline.logfire')
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
    mocker.patch('yosoi.core.pipeline.logfire')
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
    mocker.patch('yosoi.core.pipeline.logfire')
    await Pipeline.process_url(stub, 'https://x.com')


async def test_process_url_raises_when_clean_fails(mocker):
    import pytest

    stub = _make_pipeline_stub(mocker)
    fetch_result = FetchResult(url='https://x.com', html='<html/>', status_code=200)
    mocker.patch.object(Pipeline, 'normalize_url', return_value='https://x.com')
    mocker.patch.object(Pipeline, '_extract_domain', return_value='x.com')
    mocker.patch.object(Pipeline, '_create_fetcher', return_value=mocker.MagicMock())
    stub.storage.load_selectors.return_value = None
    mocker.patch.object(Pipeline, '_fetch', return_value=fetch_result)
    mocker.patch.object(Pipeline, '_clean', return_value=None)
    mocker.patch('yosoi.core.pipeline.logfire')
    with pytest.raises(RuntimeError):
        await Pipeline.process_url(stub, 'https://x.com')


async def test_process_url_raises_when_discover_fails(mocker):
    import pytest

    stub = _make_pipeline_stub(mocker)
    fetch_result = FetchResult(url='https://x.com', html='<html/>', status_code=200)
    mocker.patch.object(Pipeline, 'normalize_url', return_value='https://x.com')
    mocker.patch.object(Pipeline, '_extract_domain', return_value='x.com')
    mocker.patch.object(Pipeline, '_create_fetcher', return_value=mocker.MagicMock())
    stub.storage.load_selectors.return_value = None
    mocker.patch.object(Pipeline, '_fetch', return_value=fetch_result)
    mocker.patch.object(Pipeline, '_clean', return_value='<clean/>')
    mocker.patch.object(Pipeline, '_discover', return_value=(None, False))
    mocker.patch('yosoi.core.pipeline.logfire')
    with pytest.raises(RuntimeError):
        await Pipeline.process_url(stub, 'https://x.com')


async def test_process_url_raises_when_verify_fails(mocker):
    import pytest

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
    mocker.patch('yosoi.core.pipeline.logfire')
    with pytest.raises(RuntimeError):
        await Pipeline.process_url(stub, 'https://x.com')


# ---------------------------------------------------------------------------
# process_urls
# ---------------------------------------------------------------------------


async def test_process_urls_collects_results(mocker):
    stub = _make_pipeline_stub(mocker)
    mocker.patch.object(Pipeline, 'process_url', side_effect=[None, RuntimeError('fail')])
    mocker.patch('yosoi.core.pipeline.logfire')
    results = await Pipeline.process_urls(stub, ['https://a.com', 'https://b.com'])
    assert 'https://a.com' in results['successful']
    assert 'https://b.com' in results['failed']


async def test_process_urls_catches_exceptions(mocker):
    stub = _make_pipeline_stub(mocker)
    mocker.patch.object(Pipeline, 'process_url', side_effect=RuntimeError('boom'))
    mocker.patch('yosoi.core.pipeline.logfire')
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
    mocker.patch('yosoi.core.pipeline.logfire')
    await Pipeline.process_urls(stub, ['https://a.com'])
    # process_urls passes force_flag = self.force
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# show_summary
# ---------------------------------------------------------------------------


def test_show_summary_prints_warning_when_no_domains(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.storage.list_domains.return_value = []
    Pipeline.show_summary(stub)
    stub.console.print.assert_called()


def test_show_summary_prints_table_with_domains(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.storage.list_domains.return_value = ['example.com']
    stub.storage.load_selectors.return_value = {'title': {'primary': 'h1'}}
    Pipeline.show_summary(stub)
    stub.console.print.assert_called()


# ---------------------------------------------------------------------------
# show_llm_stats
# ---------------------------------------------------------------------------


def test_show_llm_stats_with_data(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.tracker.get_all_stats.return_value = {'example.com': {'llm_calls': 2, 'url_count': 10}}
    Pipeline.show_llm_stats(stub)
    stub.console.print.assert_called()


def test_show_llm_stats_no_calls(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.tracker.get_all_stats.return_value = {}
    Pipeline.show_llm_stats(stub)
    stub.console.print.assert_called()


# ---------------------------------------------------------------------------
# force flag propagation
# ---------------------------------------------------------------------------


async def test_process_url_respects_explicit_force_override(mocker):
    """Explicit force=True overrides pipeline's self.force=False."""
    import pytest

    stub = _make_pipeline_stub(mocker)
    stub.force = False
    mocker.patch.object(Pipeline, 'normalize_url', return_value='https://x.com')
    mocker.patch.object(Pipeline, '_extract_domain', return_value='x.com')
    mock_fetcher = mocker.MagicMock()
    mocker.patch.object(Pipeline, '_create_fetcher', return_value=mock_fetcher)
    stub.storage.load_selectors.return_value = {'title': {'primary': 'h1'}}
    mocker.patch.object(Pipeline, '_fetch', return_value=None)
    mocker.patch('yosoi.core.pipeline.logfire')
    with pytest.raises(RuntimeError):
        await Pipeline.process_url(stub, 'https://x.com', force=True)
    # load_selectors should NOT be called because force=True bypasses cache
    stub.storage.load_selectors.assert_not_called()


# ---------------------------------------------------------------------------
# normalize_url - additional targeted tests
# ---------------------------------------------------------------------------


async def test_normalize_url_http_url_returned_unchanged(mocker):
    """http:// URLs must be returned as-is without modification."""
    stub = _make_pipeline_stub(mocker)
    url = 'http://example.com/path?q=1'
    assert await Pipeline.normalize_url(stub, url) == url


async def test_normalize_url_https_url_returned_unchanged(mocker):
    """https:// URLs must be returned as-is without modification."""
    stub = _make_pipeline_stub(mocker)
    url = 'https://example.com/path'
    assert await Pipeline.normalize_url(stub, url) == url


async def test_normalize_url_prepends_https_exactly(mocker):
    """Without protocol, must prepend 'https://' (not 'http://')."""
    stub = _make_pipeline_stub(mocker)
    _mock_async_client(mocker)  # head() succeeds
    result = await Pipeline.normalize_url(stub, 'www.example.com')
    assert result == 'https://www.example.com'


async def test_normalize_url_prepends_http_on_https_failure(mocker):
    """On HTTPS failure, must prepend 'http://' (not 'ftp://')."""
    import httpx

    stub = _make_pipeline_stub(mocker)
    _mock_async_client(mocker, raise_on_head=httpx.HTTPError('fail'))
    result = await Pipeline.normalize_url(stub, 'example.com')
    assert result == 'http://example.com'


# ---------------------------------------------------------------------------
# _extract_domain - additional targeted tests
# ---------------------------------------------------------------------------


def test_extract_domain_exactly_removes_www_prefix(mocker):
    """'www.' must be removed from start but not from elsewhere."""
    stub = _make_pipeline_stub(mocker)
    assert Pipeline._extract_domain(stub, 'https://www.example.com') == 'example.com'


def test_extract_domain_does_not_modify_subdomain(mocker):
    """Non-www subdomains must not be modified."""
    stub = _make_pipeline_stub(mocker)
    assert Pipeline._extract_domain(stub, 'https://api.example.com') == 'api.example.com'


# ---------------------------------------------------------------------------
# _verify - more targeted assertions
# ---------------------------------------------------------------------------


def test_verify_calls_verifier_with_correct_args(mocker):
    """_verify must call verifier.verify with html and selectors."""
    stub = _make_pipeline_stub(mocker)
    selectors = {'title': {'primary': 'h1'}}
    vr = _make_verification_result(True, ['title'])
    stub.verifier.verify.return_value = vr
    Pipeline._verify(stub, 'https://x.com', '<html>test</html>', selectors, skip_verification=False)
    from yosoi.models.selectors import SelectorLevel

    stub.verifier.verify.assert_called_once_with('<html>test</html>', selectors, max_level=SelectorLevel.CSS)


def test_verify_returns_only_verified_fields(mocker):
    """_verify must return only fields with status='verified'."""
    stub = _make_pipeline_stub(mocker)
    # title verified, price failed
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
    """When all fail, _print_verification_failure must be called."""
    stub = _make_pipeline_stub(mocker)
    selectors = {'title': {'primary': 'h1'}}
    vr = _make_verification_result(False, ['title'])
    stub.verifier.verify.return_value = vr
    print_fail_mock = mocker.patch.object(Pipeline, '_print_verification_failure')
    Pipeline._verify(stub, 'https://x.com', '<html/>', selectors, skip_verification=False)
    print_fail_mock.assert_called_once_with(vr)


# ---------------------------------------------------------------------------
# _save_and_track - more targeted assertions
# ---------------------------------------------------------------------------


def test_save_and_track_calls_record_url_with_used_llm_true(mocker):
    """_save_and_track must pass used_llm=True when called with used_llm=True."""
    stub = _make_pipeline_stub(mocker)
    stub.tracker.record_url.return_value = {'llm_calls': 1, 'url_count': 1}
    Pipeline._save_and_track(
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


def test_save_and_track_calls_record_url_with_used_llm_false(mocker):
    """_save_and_track must pass used_llm=False when called with used_llm=False."""
    stub = _make_pipeline_stub(mocker)
    stub.tracker.record_url.return_value = {'llm_calls': 0, 'url_count': 1}
    Pipeline._save_and_track(
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


def test_save_and_track_saves_content_with_output_format(mocker):
    """save_content must be called with the correct output_format."""
    stub = _make_pipeline_stub(mocker)
    stub.tracker.record_url.return_value = {'llm_calls': 1, 'url_count': 1}
    Pipeline._save_and_track(
        stub,
        url='https://x.com',
        domain='x.com',
        verified={'title': {'primary': 'h1'}},
        extracted={'title': 'Book'},
        used_llm=True,
        output_format=['markdown'],
    )
    stub.storage.save_content.assert_called_once_with('https://x.com', {'title': 'Book'}, 'markdown')


# ---------------------------------------------------------------------------
# _track_cached_success - targeted
# ---------------------------------------------------------------------------


def test_track_cached_success_calls_record_url_used_llm_false(mocker):
    """_track_cached_success must call record_url with used_llm=False and elapsed."""
    stub = _make_pipeline_stub(mocker)
    stub._url_start = 100.0
    mocker.patch('yosoi.core.pipeline.time.monotonic', return_value=103.0)
    stub.tracker.record_url.return_value = {'llm_calls': 0, 'url_count': 1}
    Pipeline._track_cached_success(stub, 'https://example.com', 'example.com')
    call_args = stub.tracker.record_url.call_args
    assert call_args[0] == ('https://example.com',)
    assert call_args[1]['used_llm'] is False
    assert call_args[1]['level_distribution'] is None
    assert call_args[1]['elapsed'] == 3.0


# ---------------------------------------------------------------------------
# _print_tracking_stats - targeted
# ---------------------------------------------------------------------------


def test_print_tracking_stats_shows_llm_call_count(mocker):
    """_print_tracking_stats must display llm_calls value."""
    stub = _make_pipeline_stub(mocker)
    Pipeline._print_tracking_stats(stub, 'x.com', {'llm_calls': 5, 'url_count': 10})
    call_args = ' '.join(str(c) for c in stub.console.print.call_args_list)
    assert '5' in call_args


def test_print_tracking_stats_shows_url_count(mocker):
    """_print_tracking_stats must display url_count value."""
    stub = _make_pipeline_stub(mocker)
    Pipeline._print_tracking_stats(stub, 'x.com', {'llm_calls': 1, 'url_count': 7})
    call_args = ' '.join(str(c) for c in stub.console.print.call_args_list)
    assert '7' in call_args


def test_print_tracking_stats_efficiency_calculation(mocker):
    """Efficiency must be url_count / llm_calls."""
    stub = _make_pipeline_stub(mocker)
    Pipeline._print_tracking_stats(stub, 'x.com', {'llm_calls': 2, 'url_count': 10})
    call_args = ' '.join(str(c) for c in stub.console.print.call_args_list)
    # 10/2=5.0 efficiency
    assert '5.0' in call_args


def test_print_tracking_stats_no_efficiency_when_llm_zero(mocker):
    """When llm_calls=0, efficiency section should not appear (no ZeroDivisionError)."""
    stub = _make_pipeline_stub(mocker)
    # Should not raise
    Pipeline._print_tracking_stats(stub, 'x.com', {'llm_calls': 0, 'url_count': 3})
    # console.print was called at least once
    stub.console.print.assert_called()


def test_print_tracking_stats_shows_total_elapsed(mocker):
    """_print_tracking_stats must display total_elapsed when present."""
    stub = _make_pipeline_stub(mocker)
    Pipeline._print_tracking_stats(stub, 'x.com', {'llm_calls': 1, 'url_count': 2, 'total_elapsed': 5.3})
    call_args = ' '.join(str(c) for c in stub.console.print.call_args_list)
    assert '5.3' in call_args


# ---------------------------------------------------------------------------
# _handle_bot_detection - targeted
# ---------------------------------------------------------------------------


def test_handle_bot_detection_shows_url(mocker):
    """_handle_bot_detection must show the error URL."""
    stub = _make_pipeline_stub(mocker)
    err = BotDetectionError(url='https://blocked.com', status_code=403, indicators=['captcha'])
    Pipeline._handle_bot_detection(stub, err, attempt=1, max_retries=3)
    call_args = ' '.join(str(c) for c in stub.console.print.call_args_list)
    assert 'blocked.com' in call_args or 'https://blocked.com' in call_args


def test_handle_bot_detection_shows_status_code(mocker):
    """_handle_bot_detection must show the HTTP status code."""
    stub = _make_pipeline_stub(mocker)
    err = BotDetectionError(url='https://x.com', status_code=429, indicators=['rate-limit'])
    Pipeline._handle_bot_detection(stub, err, attempt=1, max_retries=3)
    call_args = ' '.join(str(c) for c in stub.console.print.call_args_list)
    assert '429' in call_args


def test_handle_bot_detection_abort_only_when_exhausted(mocker):
    """Abort message must only appear when attempt >= max_retries."""
    stub = _make_pipeline_stub(mocker)
    err = BotDetectionError(url='https://x.com', status_code=403, indicators=['cf'])
    # attempt < max_retries — no abort
    Pipeline._handle_bot_detection(stub, err, attempt=1, max_retries=3)
    call_args = ' '.join(str(c) for c in stub.console.print.call_args_list)
    assert 'ABORTING' not in call_args


def test_handle_bot_detection_abort_when_exactly_at_max_retries(mocker):
    """Abort message must appear when attempt == max_retries."""
    stub = _make_pipeline_stub(mocker)
    err = BotDetectionError(url='https://x.com', status_code=403, indicators=['cf'])
    Pipeline._handle_bot_detection(stub, err, attempt=3, max_retries=3)
    call_args = ' '.join(str(c) for c in stub.console.print.call_args_list)
    assert 'ABORTING' in call_args


# ---------------------------------------------------------------------------
# _extract_with_cached - targeted
# ---------------------------------------------------------------------------


async def test_extract_with_cached_returns_items_on_success(mocker):
    """_extract_with_cached returns (items, True) when extraction succeeds."""
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
    """_extract_with_cached returns (None, True) on unexpected exception (fail-open)."""
    stub = _make_pipeline_stub(mocker)
    mock_fetcher = mocker.MagicMock()
    mock_fetcher.fetch = mocker.AsyncMock(side_effect=RuntimeError('network error'))
    items, cache_valid = await Pipeline._extract_with_cached(
        stub, 'https://x.com', mock_fetcher, {'title': {'primary': 'h1'}}, False
    )
    assert cache_valid is True
    assert items is None


async def test_extract_with_cached_missing_contract_field_triggers_rediscovery(mocker):
    """Missing non-overridden contract field in verified selectors forces re-discovery."""

    class TwoFieldContract(Contract):
        title: str = ys.Title()
        price: float = ys.Price()

    stub = _make_pipeline_stub(mocker, contract=TwoFieldContract)
    mock_fetcher = mocker.MagicMock()
    mock_fetcher.fetch = mocker.AsyncMock(return_value=FetchResult(url='https://x.com', html='<html/>'))
    stub.cleaner.clean_html.return_value = '<html/>'
    # Verification only passes for 'title'; 'price' is absent from verified selectors
    vr = _make_verification_result(True, ['title'])
    stub.verifier.verify.return_value = vr

    items, cache_valid = await Pipeline._extract_with_cached(
        stub, 'https://x.com', mock_fetcher, {'title': {'primary': 'h1'}}, False
    )

    assert cache_valid is False
    assert items is None


async def test_extract_with_cached_missing_overridden_field_does_not_trigger_rediscovery(mocker):
    """Missing field that has a selector override does not trigger re-discovery."""
    import yosoi as ys
    from yosoi.types.field import Field as YsField

    class OverriddenContract(Contract):
        title: str = ys.Title()
        price: float = YsField(description='Price', selector='p.price')  # type: ignore[assignment]

    stub = _make_pipeline_stub(mocker, contract=OverriddenContract)
    mock_fetcher = mocker.MagicMock()
    mock_fetcher.fetch = mocker.AsyncMock(return_value=FetchResult(url='https://x.com', html='<html/>'))
    stub.cleaner.clean_html.return_value = '<html/>'
    # Only 'title' verified; 'price' is absent but it's an override — should NOT re-discover
    vr = _make_verification_result(True, ['title'])
    stub.verifier.verify.return_value = vr
    stub.extractor.extract_content_with_html.return_value = {'title': 'Book'}

    items, cache_valid = await Pipeline._extract_with_cached(
        stub, 'https://x.com', mock_fetcher, {'title': {'primary': 'h1'}}, False
    )

    assert cache_valid is True
    assert items == [{'title': 'Book'}]


# ---------------------------------------------------------------------------
# _extract - targeted
# ---------------------------------------------------------------------------


def test_extract_calls_extractor_with_correct_args(mocker):
    """_extract must call extractor.extract_content_with_html with url, html, selectors."""
    stub = _make_pipeline_stub(mocker)
    stub.extractor.extract_content_with_html.return_value = {'title': 'Book'}
    Pipeline._extract(stub, 'https://x.com', '<html>content</html>', {'title': {'primary': 'h1'}})
    from yosoi.models.selectors import SelectorLevel

    stub.extractor.extract_content_with_html.assert_called_once_with(
        'https://x.com', '<html>content</html>', {'title': {'primary': 'h1'}}, max_level=SelectorLevel.CSS
    )


# ---------------------------------------------------------------------------
# _print_verification_failure - targeted
# ---------------------------------------------------------------------------


def test_print_verification_failure_calls_console_print(mocker):
    """_print_verification_failure must call console.print at least once."""
    stub = _make_pipeline_stub(mocker)
    results = {
        'title': FieldVerificationResult(field_name='title', status='failed'),
    }
    vr = VerificationResult(total_fields=1, verified_count=0, results=results)
    Pipeline._print_verification_failure(stub, vr)
    stub.console.print.assert_called()


def test_print_partial_failure_shows_failed_field_names(mocker):
    """_print_partial_failure must show failed field names."""
    stub = _make_pipeline_stub(mocker)
    results = {
        'title': FieldVerificationResult(field_name='title', status='verified', working_level='primary', selector='h1'),
        'price': FieldVerificationResult(field_name='price', status='failed'),
    }
    vr = VerificationResult(total_fields=2, verified_count=1, results=results)
    Pipeline._print_partial_failure(stub, vr)
    call_args = ' '.join(str(c) for c in stub.console.print.call_args_list)
    assert 'price' in call_args


# ---------------------------------------------------------------------------
# process_url - additional force flag tests
# ---------------------------------------------------------------------------


async def test_process_url_uses_pipeline_format_when_output_format_none(mocker):
    """When output_format=None, process_url passes it through to scrape which resolves pipeline's output_format."""
    import pytest

    stub = _make_pipeline_stub(mocker)
    stub.output_formats = ['markdown']
    mocker.patch.object(Pipeline, 'normalize_url', return_value='https://x.com')
    mocker.patch.object(Pipeline, '_extract_domain', return_value='x.com')
    mocker.patch.object(Pipeline, '_create_fetcher', return_value=mocker.MagicMock())
    stub.storage.load_selectors.return_value = None
    mock_fetch = mocker.patch.object(Pipeline, '_fetch', return_value=None)
    mocker.patch('yosoi.core.pipeline.logfire')
    with pytest.raises(RuntimeError):
        await Pipeline.process_url(stub, 'https://x.com', output_format=None)
    # _fetch was called, meaning the pipeline reached the fetch step
    mock_fetch.assert_called_once()


# ---------------------------------------------------------------------------
# show_summary - targeted
# ---------------------------------------------------------------------------


def test_show_summary_shows_domain_count(mocker):
    """show_summary must print total domain count."""
    stub = _make_pipeline_stub(mocker)
    stub.storage.list_domains.return_value = ['a.com', 'b.com']
    stub.storage.load_selectors.return_value = {'title': {'primary': 'h1'}}
    Pipeline.show_summary(stub)
    call_args = ' '.join(str(c) for c in stub.console.print.call_args_list)
    assert '2' in call_args


# ---------------------------------------------------------------------------
# show_llm_stats - targeted
# ---------------------------------------------------------------------------


def test_show_llm_stats_shows_efficiency_when_llm_calls_nonzero(mocker):
    """show_llm_stats must show efficiency when there are LLM calls."""
    stub = _make_pipeline_stub(mocker)
    stub.tracker.get_all_stats.return_value = {'x.com': {'llm_calls': 4, 'url_count': 20}}
    Pipeline.show_llm_stats(stub)
    call_args = ' '.join(str(c) for c in stub.console.print.call_args_list)
    # 20/4 = 5.0 efficiency
    assert '5.0' in call_args


def test_show_llm_stats_sums_all_domains(mocker):
    """show_llm_stats must aggregate stats across all domains."""
    stub = _make_pipeline_stub(mocker)
    stub.tracker.get_all_stats.return_value = {
        'a.com': {'llm_calls': 2, 'url_count': 10},
        'b.com': {'llm_calls': 3, 'url_count': 15},
    }
    Pipeline.show_llm_stats(stub)
    call_args = ' '.join(str(c) for c in stub.console.print.call_args_list)
    # Total: llm_calls=5, url_count=25
    assert '5' in call_args
    assert '25' in call_args


# ---------------------------------------------------------------------------
# _clean - targeted
# ---------------------------------------------------------------------------


def test_clean_calls_cleaner_with_html(mocker):
    """_clean must call cleaner.clean_html with result.html."""
    stub = _make_pipeline_stub(mocker)
    stub.cleaner.clean_html.return_value = '<clean/>'
    result_obj = FetchResult(url='https://x.com', html='<dirty/>')
    Pipeline._clean(stub, 'https://x.com', result_obj)
    stub.cleaner.clean_html.assert_called_once_with('<dirty/>')


def test_clean_saves_debug_html(mocker):
    """_clean must call debug.save_debug_html with url and cleaned html."""
    stub = _make_pipeline_stub(mocker)
    stub.cleaner.clean_html.return_value = '<clean/>'
    result_obj = FetchResult(url='https://x.com', html='<dirty/>')
    Pipeline._clean(stub, 'https://x.com', result_obj)
    stub.debug.save_debug_html.assert_called_once_with('https://x.com', '<clean/>')


# ---------------------------------------------------------------------------
# _discover - targeted
# ---------------------------------------------------------------------------


async def test_discover_merges_overrides_with_ai_selectors(mocker):
    """AI selectors must be updated with override selectors."""
    stub = _make_pipeline_stub(mocker)
    stub.contract.get_selector_overrides = mocker.MagicMock(return_value={'author': {'primary': '.author'}})
    stub.contract.field_descriptions = mocker.MagicMock(return_value={'title': 'The title'})
    stub.discovery.discover_selectors = mocker.AsyncMock(return_value={'title': {'primary': 'h1'}})
    stub.debug.save_debug_selectors = mocker.MagicMock()

    from tenacity import AsyncRetrying, stop_after_attempt, wait_none

    mocker.patch(
        'yosoi.core.pipeline.get_async_retryer',
        return_value=AsyncRetrying(stop=stop_after_attempt(1), wait=wait_none(), reraise=False),
    )

    _selectors, _used_llm = await Pipeline._discover(stub, 'https://x.com', '<html/>', max_retries=1)
    # Both AI selectors and overrides should be present
    assert _selectors is not None
    assert 'title' in _selectors
    assert 'author' in _selectors


async def test_discover_all_override_returns_false_for_used_llm(mocker):
    """When all fields are overridden, used_llm must be False."""
    stub = _make_pipeline_stub(mocker)
    stub.contract.get_selector_overrides = mocker.MagicMock(return_value={'title': {'primary': '.t'}})
    stub.contract.field_descriptions = mocker.MagicMock(return_value={})
    stub.debug.save_debug_selectors = mocker.MagicMock()

    _selectors, used_llm = await Pipeline._discover(stub, 'https://x.com', '<html/>', max_retries=1)
    assert used_llm is False


async def test_discover_ai_success_returns_true_for_used_llm(mocker):
    """When AI succeeds, used_llm must be True."""
    stub = _make_pipeline_stub(mocker)
    stub.contract.get_selector_overrides = mocker.MagicMock(return_value={})
    stub.contract.field_descriptions = mocker.MagicMock(return_value={'title': 'The title'})
    stub.discovery.discover_selectors = mocker.AsyncMock(return_value={'title': {'primary': 'h1'}})
    stub.debug.save_debug_selectors = mocker.MagicMock()

    from tenacity import AsyncRetrying, stop_after_attempt, wait_none

    mocker.patch(
        'yosoi.core.pipeline.get_async_retryer',
        return_value=AsyncRetrying(stop=stop_after_attempt(1), wait=wait_none(), reraise=False),
    )

    _, used_llm = await Pipeline._discover(stub, 'https://x.com', '<html/>', max_retries=1)
    assert used_llm is True
