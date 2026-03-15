"""Tests for FetchResult and VerificationResult models."""

from yosoi.models.results import ContentMetadata, FetchResult, FieldVerificationResult, VerificationResult

# ---------------------------------------------------------------------------
# FetchResult
# ---------------------------------------------------------------------------


def test_fetch_result_success_when_html_present():
    r = FetchResult(url='http://example.com', html='<html></html>', status_code=200)
    assert r.success is True


def test_fetch_result_not_success_when_no_html():
    r = FetchResult(url='http://example.com', html=None, status_code=200)
    assert r.success is False


def test_fetch_result_not_success_when_blocked():
    r = FetchResult(url='http://example.com', html='<html></html>', is_blocked=True)
    assert r.success is False


def test_fetch_result_is_rss_delegates_to_metadata():
    r = FetchResult(url='http://example.com', metadata=ContentMetadata(is_rss=True))
    assert r.is_rss is True


def test_fetch_result_is_rss_false_by_default():
    r = FetchResult(url='http://example.com')
    assert r.is_rss is False


def test_fetch_result_requires_js_delegates_to_metadata():
    r = FetchResult(url='http://example.com', metadata=ContentMetadata(requires_js=True))
    assert r.requires_js is True


def test_fetch_result_should_use_heuristics_when_rss():
    r = FetchResult(url='http://example.com', metadata=ContentMetadata(is_rss=True))
    assert r.should_use_heuristics is True


def test_fetch_result_should_use_heuristics_when_requires_js():
    r = FetchResult(url='http://example.com', metadata=ContentMetadata(requires_js=True))
    assert r.should_use_heuristics is True


def test_fetch_result_should_not_use_heuristics_for_plain_html():
    r = FetchResult(url='http://example.com', html='<html></html>')
    assert r.should_use_heuristics is False


# ---------------------------------------------------------------------------
# VerificationResult
# ---------------------------------------------------------------------------


def test_verification_result_success_when_one_verified():
    result = VerificationResult(
        total_fields=2,
        verified_count=1,
        results={
            'title': FieldVerificationResult(field_name='title', status='verified', selector='h1'),
            'price': FieldVerificationResult(field_name='price', status='failed'),
        },
    )
    assert result.success is True


def test_verification_result_not_success_when_none_verified():
    result = VerificationResult(total_fields=1, verified_count=0)
    assert result.success is False


def test_verification_result_verified_fields_returns_passing_names():
    result = VerificationResult(
        total_fields=2,
        verified_count=1,
        results={
            'title': FieldVerificationResult(field_name='title', status='verified', selector='h1'),
            'price': FieldVerificationResult(field_name='price', status='failed'),
        },
    )
    assert result.verified_fields == ['title']


def test_verification_result_verified_fields_empty_when_all_fail():
    result = VerificationResult(
        total_fields=1,
        verified_count=0,
        results={
            'title': FieldVerificationResult(field_name='title', status='failed'),
        },
    )
    assert result.verified_fields == []


# ---------------------------------------------------------------------------
# FieldVerificationResult.selector_level
# ---------------------------------------------------------------------------


def test_field_verification_result_selector_level_defaults_to_none():
    r = FieldVerificationResult(field_name='title', status='failed')
    assert r.selector_level is None


def test_field_verification_result_stores_selector_level():
    r = FieldVerificationResult(field_name='title', status='verified', selector='h1', selector_level='css')
    assert r.selector_level == 'css'


def test_field_verification_result_stores_xpath_level():
    r = FieldVerificationResult(field_name='title', status='verified', selector='//h1', selector_level='xpath')
    assert r.selector_level == 'xpath'


# ---------------------------------------------------------------------------
# VerificationResult.level_distribution
# ---------------------------------------------------------------------------


def test_level_distribution_counts_by_strategy():
    result = VerificationResult(
        total_fields=3,
        verified_count=3,
        results={
            'title': FieldVerificationResult(
                field_name='title', status='verified', selector='h1', selector_level='css'
            ),
            'author': FieldVerificationResult(
                field_name='author', status='verified', selector='//span', selector_level='xpath'
            ),
            'date': FieldVerificationResult(
                field_name='date', status='verified', selector='time', selector_level='css'
            ),
        },
    )
    dist = result.level_distribution
    assert dist == {'css': 2, 'xpath': 1}


def test_level_distribution_only_counts_verified_fields():
    result = VerificationResult(
        total_fields=2,
        verified_count=1,
        results={
            'title': FieldVerificationResult(
                field_name='title', status='verified', selector='h1', selector_level='css'
            ),
            'price': FieldVerificationResult(field_name='price', status='failed'),
        },
    )
    assert result.level_distribution == {'css': 1}


def test_level_distribution_empty_when_no_selector_levels_set():
    result = VerificationResult(
        total_fields=1,
        verified_count=1,
        results={
            'title': FieldVerificationResult(field_name='title', status='verified', selector='h1'),
        },
    )
    assert result.level_distribution == {}
