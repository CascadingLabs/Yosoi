"""Unit tests for bot detection logic in HTMLFetcher and related components.

Covers every decision branch in:
  - HTMLFetcher._check_for_bot_detection  (base.py)
  - SimpleFetcher.fetch  — logger.warning emitted on detection  (simple.py)
  - Pipeline._handle_bot_detection  — logger.warning + logfire emitted  (pipeline.py)
"""

import pytest

from yosoi.core.fetcher.base import HTMLFetcher
from yosoi.core.fetcher.simple import SimpleFetcher
from yosoi.core.pipeline import Pipeline
from yosoi.utils.exceptions import BotDetectionError

# ---------------------------------------------------------------------------
# Minimal concrete HTMLFetcher so we can call the mixin method directly
# ---------------------------------------------------------------------------

VALID_HTML = '<html><body>' + 'x' * 200 + '</body></html>'


class _ConcreteHTMLFetcher(HTMLFetcher):
    async def fetch(self, url: str):  # type: ignore[override]
        raise NotImplementedError


@pytest.fixture
def fetcher() -> _ConcreteHTMLFetcher:
    return _ConcreteHTMLFetcher()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pipeline_stub(mocker):
    stub = Pipeline.__new__(Pipeline)
    stub.console = mocker.MagicMock()
    stub.logger = mocker.MagicMock()
    return stub


# ===========================================================================
# _check_for_bot_detection — HTML-too-short guard
# ===========================================================================


def test_short_html_is_blocked(fetcher):
    blocked, indicators = fetcher._check_for_bot_detection('<html/>', 200)
    assert blocked is True
    assert indicators == ['HTML too short']


def test_empty_html_is_blocked(fetcher):
    blocked, indicators = fetcher._check_for_bot_detection('', 200)
    assert blocked is True
    assert indicators == ['HTML too short']


def test_exactly_99_chars_is_blocked(fetcher):
    blocked, _ = fetcher._check_for_bot_detection('x' * 99, 200)
    assert blocked is True


def test_exactly_100_chars_is_not_short_blocked(fetcher):
    # 100-char body with no bad patterns → not blocked on 200
    blocked, _ = fetcher._check_for_bot_detection('x' * 100, 200)
    assert blocked is False


# ===========================================================================
# _check_for_bot_detection — hard-block status codes (403 / 429 / 503)
# ===========================================================================


@pytest.mark.parametrize('status_code', [403, 429, 503])
def test_hard_block_status_codes_always_block(fetcher, status_code):
    blocked, indicators = fetcher._check_for_bot_detection(VALID_HTML, status_code)
    assert blocked is True
    assert f'HTTP {status_code}' in indicators


@pytest.mark.parametrize('status_code', [403, 429, 503])
def test_hard_block_enriched_with_retry_after(fetcher, status_code):
    headers = {'Retry-After': '30'}
    _, indicators = fetcher._check_for_bot_detection(VALID_HTML, status_code, headers)
    assert 'Retry-After: 30' in indicators


@pytest.mark.parametrize('status_code', [403, 429, 503])
def test_hard_block_enriched_with_cloudflare_server(fetcher, status_code):
    headers = {'Server': 'cloudflare'}
    _, indicators = fetcher._check_for_bot_detection(VALID_HTML, status_code, headers)
    assert 'Cloudflare server' in indicators


@pytest.mark.parametrize('status_code', [403, 429, 503])
def test_hard_block_enriched_with_cf_ray(fetcher, status_code):
    headers = {'CF-Ray': 'abc123-LHR'}
    _, indicators = fetcher._check_for_bot_detection(VALID_HTML, status_code, headers)
    assert 'CF-Ray: abc123-LHR' in indicators


@pytest.mark.parametrize('status_code', [403, 429, 503])
def test_hard_block_enriched_with_all_cf_headers(fetcher, status_code):
    headers = {'Retry-After': '5', 'Server': 'cloudflare', 'CF-Ray': 'xyz-AMS'}
    _, indicators = fetcher._check_for_bot_detection(VALID_HTML, status_code, headers)
    assert 'Retry-After: 5' in indicators
    assert 'Cloudflare server' in indicators
    assert 'CF-Ray: xyz-AMS' in indicators


# ===========================================================================
# _check_for_bot_detection — cf-mitigated header (any status)
# ===========================================================================


@pytest.mark.parametrize('status_code', [200, 301, 404, 500])
def test_cf_mitigated_header_blocks_on_any_status(fetcher, status_code):
    headers = {'cf-mitigated': 'challenge'}
    blocked, indicators = fetcher._check_for_bot_detection(VALID_HTML, status_code, headers)
    assert blocked is True
    assert 'Cloudflare mitigation active' in indicators


def test_cf_mitigated_also_enriched_with_cf_ray(fetcher):
    headers = {'cf-mitigated': 'challenge', 'CF-Ray': 'ray42-CDG'}
    _, indicators = fetcher._check_for_bot_detection(VALID_HTML, 200, headers)
    assert 'Cloudflare mitigation active' in indicators
    assert 'CF-Ray: ray42-CDG' in indicators


# ===========================================================================
# _check_for_bot_detection — retry-after header on >=400 (non-hard-block)
# ===========================================================================


def test_retry_after_on_400_adds_rate_limit_indicator(fetcher):
    headers = {'Retry-After': '60'}
    _, indicators = fetcher._check_for_bot_detection(VALID_HTML, 400, headers)
    assert 'Rate limited (Retry-After header)' in indicators


def test_retry_after_on_200_does_not_add_rate_limit_indicator(fetcher):
    headers = {'Retry-After': '60'}
    _, indicators = fetcher._check_for_bot_detection(VALID_HTML, 200, headers)
    assert 'Rate limited (Retry-After header)' not in indicators


# ===========================================================================
# _check_for_bot_detection — 200 OK body patterns (Cloudflare + CAPTCHA)
# ===========================================================================


@pytest.mark.parametrize(
    ('snippet', 'expected_message'),
    [
        ('challenge-platform', 'Cloudflare challenge platform'),
        ('cf-browser-verification', 'Cloudflare browser verification'),
        ('__cf_chl_jschl_tk__', 'Cloudflare JS challenge token'),
        ('cf-captcha-container', 'Cloudflare CAPTCHA container'),
        ('just a moment...', 'Cloudflare "Just a moment" page'),
        ('checking your browser', 'Cloudflare browser check'),
        ('attention required! | cloudflare', 'Cloudflare attention page'),
        ('g-recaptcha', 'Google reCAPTCHA'),
        ('h-captcha', 'hCaptcha'),
        ('cf-turnstile', 'Cloudflare Turnstile'),
        ('access denied</title>', 'Access denied page'),
        ('you have been blocked', 'Explicit block message'),
    ],
)
def test_200_blocked_on_body_pattern(fetcher, snippet, expected_message):
    html = VALID_HTML[:50] + snippet + VALID_HTML[50:]
    blocked, indicators = fetcher._check_for_bot_detection(html, 200)
    assert blocked is True
    assert expected_message in indicators


def test_200_clean_page_not_blocked(fetcher):
    blocked, indicators = fetcher._check_for_bot_detection(VALID_HTML, 200)
    assert blocked is False
    assert indicators == []


def test_200_patterns_are_case_insensitive(fetcher):
    html = VALID_HTML[:50] + 'JUST A MOMENT...' + VALID_HTML[50:]
    blocked, indicators = fetcher._check_for_bot_detection(html, 200)
    assert blocked is True
    assert 'Cloudflare "Just a moment" page' in indicators


def test_200_pattern_only_checked_in_first_3000_chars(fetcher):
    # Pattern buried well past 3000 chars should NOT trigger
    html = 'x' * 100 + 'x' * 3000 + 'challenge-platform'
    blocked, _ = fetcher._check_for_bot_detection(html, 200)
    assert blocked is False


def test_200_multiple_patterns_all_reported(fetcher):
    html = VALID_HTML[:50] + 'g-recaptcha cf-turnstile' + VALID_HTML[50:]
    _, indicators = fetcher._check_for_bot_detection(html, 200)
    assert 'Google reCAPTCHA' in indicators
    assert 'Cloudflare Turnstile' in indicators


# ===========================================================================
# _check_for_bot_detection — >=400 body patterns (legacy + shared)
# ===========================================================================


@pytest.mark.parametrize(
    ('snippet', 'expected_message'),
    [
        ('captcha', 'CAPTCHA required'),
        ('rate limit', 'Rate limited'),
        ('too many requests', 'Too many requests'),
        ('forbidden', 'Forbidden'),
    ],
)
def test_400_blocked_on_legacy_body_pattern(fetcher, snippet, expected_message):
    html = VALID_HTML[:50] + snippet + VALID_HTML[50:]
    blocked, indicators = fetcher._check_for_bot_detection(html, 400)
    assert blocked is True
    assert expected_message in indicators


def test_400_clean_html_is_not_blocked(fetcher):
    blocked, indicators = fetcher._check_for_bot_detection(VALID_HTML, 400)
    assert blocked is False
    assert indicators == []


def test_non_hard_block_500_with_body_pattern_blocked(fetcher):
    html = VALID_HTML[:50] + 'captcha' + VALID_HTML[50:]
    blocked, _ = fetcher._check_for_bot_detection(html, 500)
    assert blocked is True


# ===========================================================================
# _check_for_bot_detection — 2xx/3xx non-200 statuses without body patterns
# ===========================================================================


@pytest.mark.parametrize('status_code', [201, 204, 301, 302])
def test_non_200_success_or_redirect_not_blocked(fetcher, status_code):
    blocked, indicators = fetcher._check_for_bot_detection(VALID_HTML, status_code)
    assert blocked is False
    assert indicators == []


# ===========================================================================
# _check_for_bot_detection — headers=None is backwards-compatible
# ===========================================================================


def test_no_headers_argument_does_not_crash(fetcher):
    blocked, _ = fetcher._check_for_bot_detection(VALID_HTML, 200)
    assert blocked is False


def test_empty_headers_dict_does_not_crash(fetcher):
    blocked, _ = fetcher._check_for_bot_detection(VALID_HTML, 200, {})
    assert blocked is False


# ===========================================================================
# SimpleFetcher.fetch — logger.warning emitted on bot detection
# ===========================================================================


@pytest.mark.asyncio
async def test_simple_fetcher_logs_warning_on_bot_detection(mocker):
    fetcher_instance = SimpleFetcher(use_session=False)
    fetcher_instance.logger = mocker.MagicMock()

    # Craft a response that triggers bot detection (403)
    mock_response = mocker.MagicMock()
    mock_response.status_code = 403
    mock_response.text = VALID_HTML
    mock_response.headers = {'CF-Ray': 'test-ray'}
    mock_response.content = VALID_HTML.encode()

    mocker.patch('httpx.AsyncClient.get', return_value=mock_response)
    mocker.patch.object(fetcher_instance, '_apply_request_delay', return_value=None)

    with pytest.raises(BotDetectionError):
        await fetcher_instance.fetch('https://example.com')

    fetcher_instance.logger.warning.assert_called_once()
    call_args = fetcher_instance.logger.warning.call_args
    assert 'https://example.com' in str(call_args)
    assert '403' in str(call_args)


@pytest.mark.asyncio
async def test_simple_fetcher_passes_response_headers_to_check(mocker):
    fetcher_instance = SimpleFetcher(use_session=False)
    fetcher_instance.logger = mocker.MagicMock()

    mock_response = mocker.MagicMock()
    mock_response.status_code = 200
    mock_response.text = VALID_HTML
    mock_response.headers = {'cf-mitigated': 'challenge'}
    mock_response.content = VALID_HTML.encode()

    mocker.patch('httpx.AsyncClient.get', return_value=mock_response)
    mocker.patch.object(fetcher_instance, '_apply_request_delay', return_value=None)

    with pytest.raises(BotDetectionError) as exc_info:
        await fetcher_instance.fetch('https://example.com')

    assert 'Cloudflare mitigation active' in exc_info.value.indicators


@pytest.mark.asyncio
async def test_simple_fetcher_no_warning_on_clean_200(mocker):
    fetcher_instance = SimpleFetcher(use_session=False)
    fetcher_instance.logger = mocker.MagicMock()

    mock_response = mocker.MagicMock()
    mock_response.status_code = 200
    mock_response.text = VALID_HTML
    mock_response.headers = {}
    mock_response.content = VALID_HTML.encode()

    mocker.patch('httpx.AsyncClient.get', return_value=mock_response)
    mocker.patch.object(fetcher_instance, '_apply_request_delay', return_value=None)
    mocker.patch('yosoi.core.fetcher.simple.ContentAnalyzer.analyze', return_value=mocker.MagicMock())

    result = await fetcher_instance.fetch('https://example.com')

    fetcher_instance.logger.warning.assert_not_called()
    assert result.is_blocked is False


# ===========================================================================
# Pipeline._handle_bot_detection — logger.warning + logfire emitted
# ===========================================================================


def test_handle_bot_detection_calls_logger_warning(mocker):
    stub = _make_pipeline_stub(mocker)
    mocker.patch('yosoi.core.pipeline.logfire')

    err = BotDetectionError(url='https://x.com', status_code=403, indicators=['HTTP 403', 'CF-Ray: abc'])
    Pipeline._handle_bot_detection(stub, err, attempt=1, max_retries=3)

    stub.logger.warning.assert_called_once()
    call_args = str(stub.logger.warning.call_args)
    assert 'https://x.com' in call_args
    assert '403' in call_args


def test_handle_bot_detection_logger_warning_includes_attempt_info(mocker):
    stub = _make_pipeline_stub(mocker)
    mocker.patch('yosoi.core.pipeline.logfire')

    err = BotDetectionError(url='https://x.com', status_code=429, indicators=['HTTP 429'])
    Pipeline._handle_bot_detection(stub, err, attempt=2, max_retries=3)

    call_args = str(stub.logger.warning.call_args)
    assert '2' in call_args
    assert '3' in call_args


def test_handle_bot_detection_calls_logfire_warn(mocker):
    stub = _make_pipeline_stub(mocker)
    mock_logfire = mocker.patch('yosoi.core.pipeline.logfire')

    err = BotDetectionError(url='https://x.com', status_code=503, indicators=['HTTP 503'])
    Pipeline._handle_bot_detection(stub, err, attempt=1, max_retries=2)

    mock_logfire.warning.assert_called_once()
    kwargs = mock_logfire.warning.call_args.kwargs
    assert kwargs['url'] == 'https://x.com'
    assert kwargs['status_code'] == 503
    assert kwargs['attempt'] == 1
    assert kwargs['max_retries'] == 2


def test_handle_bot_detection_logfire_includes_indicators(mocker):
    stub = _make_pipeline_stub(mocker)
    mock_logfire = mocker.patch('yosoi.core.pipeline.logfire')

    indicators = ['HTTP 403', 'Cloudflare server', 'CF-Ray: ray1-LHR']
    err = BotDetectionError(url='https://x.com', status_code=403, indicators=indicators)
    Pipeline._handle_bot_detection(stub, err, attempt=1, max_retries=2)

    kwargs = mock_logfire.warning.call_args.kwargs
    assert kwargs['indicators'] == indicators


def test_handle_bot_detection_still_prints_to_console(mocker):
    stub = _make_pipeline_stub(mocker)
    mocker.patch('yosoi.core.pipeline.logfire')

    err = BotDetectionError(url='https://x.com', status_code=403, indicators=['HTTP 403'])
    Pipeline._handle_bot_detection(stub, err, attempt=1, max_retries=2)

    stub.console.print.assert_called()


def test_handle_bot_detection_abort_message_when_exhausted(mocker):
    stub = _make_pipeline_stub(mocker)
    mocker.patch('yosoi.core.pipeline.logfire')

    err = BotDetectionError(url='https://x.com', status_code=403, indicators=['HTTP 403'])
    Pipeline._handle_bot_detection(stub, err, attempt=2, max_retries=2)

    all_prints = ' '.join(str(c) for c in stub.console.print.call_args_list)
    assert 'ABORTING' in all_prints


def test_handle_bot_detection_no_abort_message_when_retries_remain(mocker):
    stub = _make_pipeline_stub(mocker)
    mocker.patch('yosoi.core.pipeline.logfire')

    err = BotDetectionError(url='https://x.com', status_code=403, indicators=['HTTP 403'])
    Pipeline._handle_bot_detection(stub, err, attempt=1, max_retries=3)

    all_prints = ' '.join(str(c) for c in stub.console.print.call_args_list)
    assert 'ABORTING' not in all_prints
