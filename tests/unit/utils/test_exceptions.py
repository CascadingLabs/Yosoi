"""Tests for custom exception classes."""

from yosoi.utils.exceptions import BotDetectionError, SelectorError


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


def test_bot_detection_error_message_contains_url():
    err = BotDetectionError(url='https://example.com', status_code=403, indicators=['captcha'])
    assert 'https://example.com' in str(err)


def test_bot_detection_error_message_contains_status_code():
    err = BotDetectionError(url='https://example.com', status_code=403, indicators=['captcha'])
    assert '403' in str(err)


def test_selector_error_stores_field_name():
    err = SelectorError('title', [('primary', 'h1')], [('primary', 'no_elements_found')])
    assert err.field_name == 'title'


def test_selector_error_stores_selectors_tried():
    selectors_tried = [('primary', 'h1'), ('fallback', '.title')]
    err = SelectorError('price', selectors_tried, [('primary', 'no_elements_found')])
    assert err.selectors_tried == selectors_tried


def test_selector_error_message_contains_field_name():
    err = SelectorError('price', [('primary', '.price')], [('primary', 'no_elements_found')])
    assert 'price' in str(err)


def test_selector_error_message_contains_failure_reason():
    err = SelectorError('price', [('primary', '.price')], [('primary', 'no_elements_found')])
    assert 'no_elements_found' in str(err)
