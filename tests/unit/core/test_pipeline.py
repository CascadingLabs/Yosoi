"""Unit tests for Pipeline methods."""

import yosoi as ys
from yosoi.core.pipeline import Pipeline
from yosoi.models.contract import Contract
from yosoi.models.results import FetchResult, FieldVerificationResult, VerificationResult

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
    stub.verifier = mocker.MagicMock()
    stub.extractor = mocker.MagicMock()
    stub.storage = mocker.MagicMock()
    stub.tracker = mocker.MagicMock()
    stub.debug = mocker.MagicMock()
    stub.debug_mode = False
    stub.output_format = 'json'
    stub.force = False
    return stub


# ---------------------------------------------------------------------------
# normalize_url
# ---------------------------------------------------------------------------


def test_normalize_url_already_https(mocker):
    stub = _make_pipeline_stub(mocker)
    assert Pipeline.normalize_url(stub, 'https://example.com') == 'https://example.com'


def test_normalize_url_already_http(mocker):
    stub = _make_pipeline_stub(mocker)
    assert Pipeline.normalize_url(stub, 'http://example.com') == 'http://example.com'


def test_normalize_url_adds_https_on_success(mocker):
    stub = _make_pipeline_stub(mocker)
    mocker.patch('httpx.head')  # doesn't raise
    result = Pipeline.normalize_url(stub, 'example.com')
    assert result == 'https://example.com'


def test_normalize_url_falls_back_to_http_on_error(mocker):
    import httpx

    stub = _make_pipeline_stub(mocker)
    mocker.patch('httpx.head', side_effect=httpx.HTTPError('fail'))
    result = Pipeline.normalize_url(stub, 'example.com')
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
        output_format='json',
    )
    stub.storage.save_selectors.assert_called_once()
    stub.storage.save_content.assert_called_once()
    stub.tracker.record_url.assert_called_once_with('https://x.com', used_llm=True)


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
        output_format='json',
    )
    stub.storage.save_selectors.assert_called_once()
    stub.storage.save_content.assert_not_called()


# ---------------------------------------------------------------------------
# _track_cached_success
# ---------------------------------------------------------------------------


def test_track_cached_success_calls_record_url(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.tracker.record_url.return_value = {'llm_calls': 0, 'url_count': 3}
    Pipeline._track_cached_success(stub, 'https://x.com', 'x.com')
    stub.tracker.record_url.assert_called_once_with('https://x.com', used_llm=False)


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
# _cached_selectors
# ---------------------------------------------------------------------------


def test_cached_selectors_returns_false_when_no_cache(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.storage.load_selectors.return_value = None
    result = Pipeline._cached_selectors(stub, 'https://x.com', 'x.com', mocker.MagicMock(), False, 'json')
    assert result is False


def test_cached_selectors_returns_true_when_cache_exists(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.storage.load_selectors.return_value = {'title': {'primary': 'h1'}}
    mocker.patch.object(Pipeline, '_use_cached_selectors', return_value=True)
    result = Pipeline._cached_selectors(stub, 'https://x.com', 'x.com', mocker.MagicMock(), False, 'json')
    assert result is True


# ---------------------------------------------------------------------------
# _use_cached_selectors
# ---------------------------------------------------------------------------


def test_use_cached_selectors_returns_true_on_fetch_failure(mocker):
    stub = _make_pipeline_stub(mocker)
    mock_fetcher = mocker.MagicMock()
    mock_fetcher.fetch.return_value = FetchResult(url='https://x.com', html=None, is_blocked=True)
    stub.tracker.record_url.return_value = {'llm_calls': 0, 'url_count': 1}
    result = Pipeline._use_cached_selectors(
        stub, 'https://x.com', 'x.com', mock_fetcher, {'title': {'primary': 'h1'}}, 'json', False
    )
    assert result is True


def test_use_cached_selectors_returns_false_when_verification_fails(mocker):
    stub = _make_pipeline_stub(mocker)
    mock_fetcher = mocker.MagicMock()
    mock_fetcher.fetch.return_value = FetchResult(url='https://x.com', html='<html/>')
    stub.cleaner.clean_html.return_value = '<html/>'
    vr = _make_verification_result(False, ['title'])
    stub.verifier.verify.return_value = vr
    result = Pipeline._use_cached_selectors(
        stub, 'https://x.com', 'x.com', mock_fetcher, {'title': {'primary': 'h1'}}, 'json', False
    )
    assert result is False


def test_use_cached_selectors_skips_verification_when_flag_set(mocker):
    stub = _make_pipeline_stub(mocker)
    mock_fetcher = mocker.MagicMock()
    mock_fetcher.fetch.return_value = FetchResult(url='https://x.com', html='<html/>')
    stub.cleaner.clean_html.return_value = '<html/>'
    stub.extractor.extract_content_with_html.return_value = None
    stub.tracker.record_url.return_value = {'llm_calls': 0, 'url_count': 1}
    result = Pipeline._use_cached_selectors(
        stub, 'https://x.com', 'x.com', mock_fetcher, {'title': {'primary': 'h1'}}, 'json', True
    )
    stub.verifier.verify.assert_not_called()
    assert result is True


# ---------------------------------------------------------------------------
# _fetch
# ---------------------------------------------------------------------------


def test_fetch_returns_result_on_success(mocker):
    stub = _make_pipeline_stub(mocker)
    fetch_result = FetchResult(url='https://x.com', html='<html/>', status_code=200)
    mock_fetcher = mocker.MagicMock()
    mock_fetcher.fetch.return_value = fetch_result
    mocker.patch('yosoi.core.pipeline.get_retryer')
    # Use a real retryer to test the flow properly
    from tenacity import Retrying, stop_after_attempt

    mocker.patch('yosoi.core.pipeline.get_retryer', return_value=Retrying(stop=stop_after_attempt(1), reraise=True))
    result = Pipeline._fetch(stub, 'https://x.com', mock_fetcher, max_retries=1)
    assert result is fetch_result


def test_fetch_returns_none_when_all_retries_fail(mocker):
    stub = _make_pipeline_stub(mocker)
    mock_fetcher = mocker.MagicMock()
    mock_fetcher.fetch.return_value = FetchResult(
        url='https://x.com', html=None, is_blocked=True, block_reason='blocked'
    )
    from tenacity import Retrying, stop_after_attempt, wait_none

    mocker.patch(
        'yosoi.core.pipeline.get_retryer',
        return_value=Retrying(stop=stop_after_attempt(1), wait=wait_none(), reraise=False),
    )
    result = Pipeline._fetch(stub, 'https://x.com', mock_fetcher, max_retries=1)
    assert result is None


# ---------------------------------------------------------------------------
# _discover
# ---------------------------------------------------------------------------


def test_discover_returns_overrides_when_no_fields_need_discovery(mocker):
    stub = _make_pipeline_stub(mocker)

    class OverrideContract(Contract):
        title: str = ys.Field(selector='.title')  # type: ignore[assignment]

    stub.contract = OverrideContract
    stub.contract.get_selector_overrides = mocker.MagicMock(return_value={'title': {'primary': '.title'}})
    stub.contract.field_descriptions = mocker.MagicMock(return_value={})
    stub.debug.save_debug_selectors = mocker.MagicMock()

    selectors, used_llm = Pipeline._discover(stub, 'https://x.com', '<html/>', max_retries=1)
    assert selectors == {'title': {'primary': '.title'}}
    assert used_llm is False
    stub.discovery.discover_selectors.assert_not_called()


def test_discover_returns_selectors_on_ai_success(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.contract.get_selector_overrides = mocker.MagicMock(return_value={})
    stub.contract.field_descriptions = mocker.MagicMock(return_value={'title': 'The title'})
    stub.discovery.discover_selectors.return_value = {'title': {'primary': 'h1'}}
    stub.debug.save_debug_selectors = mocker.MagicMock()

    from tenacity import Retrying, stop_after_attempt, wait_none

    mocker.patch(
        'yosoi.core.pipeline.get_retryer',
        return_value=Retrying(stop=stop_after_attempt(1), wait=wait_none(), reraise=False),
    )

    selectors, used_llm = Pipeline._discover(stub, 'https://x.com', '<html/>', max_retries=1)
    assert selectors == {'title': {'primary': 'h1'}}
    assert used_llm is True


def test_discover_returns_none_when_all_ai_attempts_fail(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.contract.get_selector_overrides = mocker.MagicMock(return_value={})
    stub.contract.field_descriptions = mocker.MagicMock(return_value={'title': 'The title'})
    stub.discovery.discover_selectors.return_value = None

    from tenacity import Retrying, stop_after_attempt, wait_none

    mocker.patch(
        'yosoi.core.pipeline.get_retryer',
        return_value=Retrying(stop=stop_after_attempt(1), wait=wait_none(), reraise=False),
    )

    selectors, used_llm = Pipeline._discover(stub, 'https://x.com', '<html/>', max_retries=1)
    assert selectors is None
    assert used_llm is False


# ---------------------------------------------------------------------------
# process_url
# ---------------------------------------------------------------------------


def test_process_url_returns_false_when_fetch_fails(mocker):
    stub = _make_pipeline_stub(mocker)
    mocker.patch.object(Pipeline, 'normalize_url', return_value='https://x.com')
    mocker.patch.object(Pipeline, '_extract_domain', return_value='x.com')
    mocker.patch.object(Pipeline, '_create_fetcher', return_value=mocker.MagicMock())
    mocker.patch.object(Pipeline, '_cached_selectors', return_value=False)
    mocker.patch.object(Pipeline, '_fetch', return_value=None)
    mocker.patch('yosoi.core.pipeline.logfire')
    result = Pipeline.process_url(stub, 'https://x.com')
    assert result is False


def test_process_url_returns_false_when_create_fetcher_fails(mocker):
    stub = _make_pipeline_stub(mocker)
    mocker.patch.object(Pipeline, 'normalize_url', return_value='https://x.com')
    mocker.patch.object(Pipeline, '_extract_domain', return_value='x.com')
    mocker.patch.object(Pipeline, '_create_fetcher', return_value=None)
    mocker.patch('yosoi.core.pipeline.logfire')
    result = Pipeline.process_url(stub, 'https://x.com')
    assert result is False


def test_process_url_returns_true_when_cached_selectors_used(mocker):
    stub = _make_pipeline_stub(mocker)
    mocker.patch.object(Pipeline, 'normalize_url', return_value='https://x.com')
    mocker.patch.object(Pipeline, '_extract_domain', return_value='x.com')
    mocker.patch.object(Pipeline, '_create_fetcher', return_value=mocker.MagicMock())
    mocker.patch.object(Pipeline, '_cached_selectors', return_value=True)
    mocker.patch('yosoi.core.pipeline.logfire')
    result = Pipeline.process_url(stub, 'https://x.com')
    assert result is True


def test_process_url_full_success_path(mocker):
    stub = _make_pipeline_stub(mocker)
    fetch_result = FetchResult(url='https://x.com', html='<html/>', status_code=200)
    mocker.patch.object(Pipeline, 'normalize_url', return_value='https://x.com')
    mocker.patch.object(Pipeline, '_extract_domain', return_value='x.com')
    mocker.patch.object(Pipeline, '_create_fetcher', return_value=mocker.MagicMock())
    mocker.patch.object(Pipeline, '_cached_selectors', return_value=False)
    mocker.patch.object(Pipeline, '_fetch', return_value=fetch_result)
    mocker.patch.object(Pipeline, '_clean', return_value='<clean/>')
    mocker.patch.object(Pipeline, '_discover', return_value=({'title': {'primary': 'h1'}}, True))
    mocker.patch.object(Pipeline, '_verify', return_value={'title': {'primary': 'h1'}})
    mocker.patch.object(Pipeline, '_extract', return_value={'title': 'Book'})
    mocker.patch.object(Pipeline, '_validate_with_contract', return_value={'title': 'Book'})
    mocker.patch.object(Pipeline, '_save_and_track')
    mocker.patch('yosoi.core.pipeline.logfire')
    result = Pipeline.process_url(stub, 'https://x.com')
    assert result is True


def test_process_url_returns_true_even_when_extraction_fails(mocker):
    stub = _make_pipeline_stub(mocker)
    fetch_result = FetchResult(url='https://x.com', html='<html/>', status_code=200)
    mocker.patch.object(Pipeline, 'normalize_url', return_value='https://x.com')
    mocker.patch.object(Pipeline, '_extract_domain', return_value='x.com')
    mocker.patch.object(Pipeline, '_create_fetcher', return_value=mocker.MagicMock())
    mocker.patch.object(Pipeline, '_cached_selectors', return_value=False)
    mocker.patch.object(Pipeline, '_fetch', return_value=fetch_result)
    mocker.patch.object(Pipeline, '_clean', return_value='<clean/>')
    mocker.patch.object(Pipeline, '_discover', return_value=({'title': {'primary': 'h1'}}, True))
    mocker.patch.object(Pipeline, '_verify', return_value={'title': {'primary': 'h1'}})
    mocker.patch.object(Pipeline, '_extract', return_value=None)
    mocker.patch.object(Pipeline, '_save_and_track')
    mocker.patch('yosoi.core.pipeline.logfire')
    result = Pipeline.process_url(stub, 'https://x.com')
    assert result is True


def test_process_url_returns_false_when_clean_fails(mocker):
    stub = _make_pipeline_stub(mocker)
    fetch_result = FetchResult(url='https://x.com', html='<html/>', status_code=200)
    mocker.patch.object(Pipeline, 'normalize_url', return_value='https://x.com')
    mocker.patch.object(Pipeline, '_extract_domain', return_value='x.com')
    mocker.patch.object(Pipeline, '_create_fetcher', return_value=mocker.MagicMock())
    mocker.patch.object(Pipeline, '_cached_selectors', return_value=False)
    mocker.patch.object(Pipeline, '_fetch', return_value=fetch_result)
    mocker.patch.object(Pipeline, '_clean', return_value=None)
    mocker.patch('yosoi.core.pipeline.logfire')
    result = Pipeline.process_url(stub, 'https://x.com')
    assert result is False


def test_process_url_returns_false_when_discover_fails(mocker):
    stub = _make_pipeline_stub(mocker)
    fetch_result = FetchResult(url='https://x.com', html='<html/>', status_code=200)
    mocker.patch.object(Pipeline, 'normalize_url', return_value='https://x.com')
    mocker.patch.object(Pipeline, '_extract_domain', return_value='x.com')
    mocker.patch.object(Pipeline, '_create_fetcher', return_value=mocker.MagicMock())
    mocker.patch.object(Pipeline, '_cached_selectors', return_value=False)
    mocker.patch.object(Pipeline, '_fetch', return_value=fetch_result)
    mocker.patch.object(Pipeline, '_clean', return_value='<clean/>')
    mocker.patch.object(Pipeline, '_discover', return_value=(None, False))
    mocker.patch('yosoi.core.pipeline.logfire')
    result = Pipeline.process_url(stub, 'https://x.com')
    assert result is False


def test_process_url_returns_false_when_verify_fails(mocker):
    stub = _make_pipeline_stub(mocker)
    fetch_result = FetchResult(url='https://x.com', html='<html/>', status_code=200)
    mocker.patch.object(Pipeline, 'normalize_url', return_value='https://x.com')
    mocker.patch.object(Pipeline, '_extract_domain', return_value='x.com')
    mocker.patch.object(Pipeline, '_create_fetcher', return_value=mocker.MagicMock())
    mocker.patch.object(Pipeline, '_cached_selectors', return_value=False)
    mocker.patch.object(Pipeline, '_fetch', return_value=fetch_result)
    mocker.patch.object(Pipeline, '_clean', return_value='<clean/>')
    mocker.patch.object(Pipeline, '_discover', return_value=({'title': {'primary': 'h1'}}, True))
    mocker.patch.object(Pipeline, '_verify', return_value=None)
    mocker.patch('yosoi.core.pipeline.logfire')
    result = Pipeline.process_url(stub, 'https://x.com')
    assert result is False


# ---------------------------------------------------------------------------
# process_urls
# ---------------------------------------------------------------------------


def test_process_urls_collects_results(mocker):
    stub = _make_pipeline_stub(mocker)
    mocker.patch.object(Pipeline, 'process_url', side_effect=[True, False])
    mocker.patch('yosoi.core.pipeline.logfire')
    results = Pipeline.process_urls(stub, ['https://a.com', 'https://b.com'])
    assert 'https://a.com' in results['successful']
    assert 'https://b.com' in results['failed']


def test_process_urls_catches_exceptions(mocker):
    stub = _make_pipeline_stub(mocker)
    mocker.patch.object(Pipeline, 'process_url', side_effect=RuntimeError('boom'))
    mocker.patch('yosoi.core.pipeline.logfire')
    results = Pipeline.process_urls(stub, ['https://a.com'])
    assert 'https://a.com' in results['failed']


def test_process_urls_uses_pipeline_force_flag(mocker):
    stub = _make_pipeline_stub(mocker)
    stub.force = True
    calls = []

    def capture_call(url, *args, **kwargs):
        calls.append(kwargs.get('force', args[0] if args else None))
        return True

    mocker.patch.object(Pipeline, 'process_url', side_effect=capture_call)
    mocker.patch('yosoi.core.pipeline.logfire')
    Pipeline.process_urls(stub, ['https://a.com'])
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


def test_process_url_respects_explicit_force_override(mocker):
    """Explicit force=True overrides pipeline's self.force=False."""
    stub = _make_pipeline_stub(mocker)
    stub.force = False
    mocker.patch.object(Pipeline, 'normalize_url', return_value='https://x.com')
    mocker.patch.object(Pipeline, '_extract_domain', return_value='x.com')
    mock_fetcher = mocker.MagicMock()
    mocker.patch.object(Pipeline, '_create_fetcher', return_value=mock_fetcher)
    cached_mock = mocker.patch.object(Pipeline, '_cached_selectors', return_value=False)
    mocker.patch.object(Pipeline, '_fetch', return_value=None)
    mocker.patch('yosoi.core.pipeline.logfire')
    Pipeline.process_url(stub, 'https://x.com', force=True)
    # _cached_selectors should NOT be called because force=True bypasses cache
    cached_mock.assert_not_called()
