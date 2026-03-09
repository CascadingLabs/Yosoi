"""Tests for custom exception classes."""

import pytest

from yosoi.utils.exceptions import BotDetectionError, LLMGenerationError, SelectorError, YosoiError


def test_bot_detection_error_stores_url():
    err = BotDetectionError(url='https://example.com', status_code=403, indicators=['captcha'])
    assert err.url == 'https://example.com'


def test_bot_detection_error_stores_status_code():
    err = BotDetectionError(url='https://example.com', status_code=429, indicators=['rate-limit'])
    assert err.status_code == 429


def test_bot_detection_error_stores_indicators():
    indicators = ['captcha', 'cloudflare']
    err = BotDetectionError(url='https://example.com', status_code=403, indicators=indicators)
    assert err.indicators == indicators


def test_bot_detection_error_indicators_exact_list():
    indicators = ['captcha', 'cloudflare']
    err = BotDetectionError(url='https://example.com', status_code=403, indicators=indicators)
    assert err.indicators[0] == 'captcha'
    assert err.indicators[1] == 'cloudflare'
    assert len(err.indicators) == 2


def test_bot_detection_error_message_contains_url():
    err = BotDetectionError(url='https://example.com', status_code=403, indicators=['captcha'])
    assert 'https://example.com' in str(err)


def test_bot_detection_error_message_contains_status_code():
    err = BotDetectionError(url='https://example.com', status_code=403, indicators=['captcha'])
    assert '403' in str(err)


def test_bot_detection_error_message_contains_all_indicators():
    err = BotDetectionError(url='https://example.com', status_code=403, indicators=['captcha', 'cloudflare'])
    msg = str(err)
    assert 'captcha' in msg
    assert 'cloudflare' in msg


def test_bot_detection_error_message_format_exact():
    err = BotDetectionError(url='https://x.com', status_code=403, indicators=['captcha'])
    msg = str(err)
    # Message should include status code in parentheses
    assert 'status=403' in msg
    assert 'https://x.com' in msg


def test_bot_detection_error_message_joins_indicators_with_comma():
    err = BotDetectionError(url='https://x.com', status_code=403, indicators=['a', 'b', 'c'])
    msg = str(err)
    assert 'a, b, c' in msg


def test_bot_detection_error_is_yosoi_error():
    err = BotDetectionError(url='https://x.com', status_code=403, indicators=[])
    assert isinstance(err, YosoiError)


def test_bot_detection_error_is_exception():
    err = BotDetectionError(url='https://x.com', status_code=403, indicators=[])
    assert isinstance(err, Exception)


def test_bot_detection_error_can_be_raised():
    with pytest.raises(BotDetectionError) as exc_info:
        raise BotDetectionError(url='https://x.com', status_code=429, indicators=['rate-limit'])
    assert exc_info.value.status_code == 429


def test_selector_error_stores_field_name():
    err = SelectorError('title', [('primary', 'h1')], [('primary', 'no_elements_found')])
    assert err.field_name == 'title'


def test_selector_error_stores_selectors_tried():
    selectors_tried = [('primary', 'h1'), ('fallback', '.title')]
    err = SelectorError('price', selectors_tried, [('primary', 'no_elements_found')])
    assert err.selectors_tried == selectors_tried


def test_selector_error_stores_failure_reasons():
    failure_reasons = [('primary', 'no_elements_found'), ('fallback', 'invalid_syntax')]
    err = SelectorError('title', [('primary', 'h1')], failure_reasons)
    assert err.failure_reasons == failure_reasons


def test_selector_error_message_contains_field_name():
    err = SelectorError('price', [('primary', '.price')], [('primary', 'no_elements_found')])
    assert 'price' in str(err)


def test_selector_error_message_contains_failure_reason():
    err = SelectorError('price', [('primary', '.price')], [('primary', 'no_elements_found')])
    assert 'no_elements_found' in str(err)


def test_selector_error_message_format_includes_field_name():
    err = SelectorError('headline', [('primary', 'h1')], [('primary', 'no_elements_found')])
    msg = str(err)
    assert "'headline'" in msg


def test_selector_error_message_includes_level_and_reason():
    err = SelectorError(
        'title', [('primary', 'h1')], [('primary', 'no_elements_found'), ('fallback', 'invalid_syntax')]
    )
    msg = str(err)
    assert 'primary' in msg
    assert 'fallback' in msg


def test_selector_error_is_yosoi_error():
    err = SelectorError('f', [], [])
    assert isinstance(err, YosoiError)


def test_selector_error_can_be_raised():
    with pytest.raises(SelectorError) as exc_info:
        raise SelectorError('title', [('primary', 'h1')], [('primary', 'no_elements_found')])
    assert exc_info.value.field_name == 'title'


def test_llm_generation_error_is_yosoi_error():
    err = LLMGenerationError('LLM failed')
    assert isinstance(err, YosoiError)


def test_yosoi_error_is_exception():
    err = YosoiError('base')
    assert isinstance(err, Exception)


def test_selector_error_message_exact_format():
    """Verify exact message format for SelectorError: field name in quotes, reasons joined by ', '."""
    err = SelectorError(
        'price',
        [('primary', '.price')],
        [('primary', 'no_elements_found'), ('fallback', 'invalid_syntax')],
    )
    msg = str(err)
    # Field name should be in single quotes
    assert "'price'" in msg
    # Reasons should be joined with colon
    assert 'primary: no_elements_found' in msg
    assert 'fallback: invalid_syntax' in msg


def test_selector_error_message_uses_colon_separator():
    """Level and reason must be separated by ': ' (colon-space)."""
    err = SelectorError('title', [('primary', 'h1')], [('primary', 'no_elements_found')])
    msg = str(err)
    assert 'primary: no_elements_found' in msg


def test_selector_error_message_multiple_reasons_comma_separated():
    """Multiple failure reasons should be comma-space separated."""
    err = SelectorError(
        'title',
        [('primary', 'h1'), ('fallback', 'h2')],
        [('primary', 'no_elements_found'), ('fallback', 'invalid_syntax')],
    )
    msg = str(err)
    # Both should appear, comma-separated
    assert ', ' in msg
    assert 'primary: no_elements_found' in msg
    assert 'fallback: invalid_syntax' in msg


def test_selector_error_field_name_exact():
    """field_name attribute must store exactly what was passed."""
    err = SelectorError('my_exact_field', [], [])
    assert err.field_name == 'my_exact_field'


def test_selector_error_selectors_tried_exact():
    """selectors_tried must store the exact list passed in."""
    tried = [('primary', 'h1.title'), ('fallback', '.heading')]
    err = SelectorError('title', tried, [])
    assert err.selectors_tried is tried
    assert err.selectors_tried[0] == ('primary', 'h1.title')
    assert err.selectors_tried[1] == ('fallback', '.heading')


def test_selector_error_failure_reasons_exact():
    """failure_reasons must store the exact list passed in."""
    reasons = [('primary', 'no_match'), ('fallback', 'error')]
    err = SelectorError('price', [], reasons)
    assert err.failure_reasons is reasons
    assert err.failure_reasons[0] == ('primary', 'no_match')
    assert err.failure_reasons[1] == ('fallback', 'error')
