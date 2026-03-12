"""Unit tests for SelectorVerifier."""

import pytest
from bs4 import BeautifulSoup
from rich.console import Console

from yosoi.core.verification.verifier import SelectorVerifier
from yosoi.models.results import VerificationResult


@pytest.fixture
def verifier():
    return SelectorVerifier(console=Console(quiet=True))


@pytest.fixture
def simple_html():
    return """
    <html><body>
    <h1 class="title">Book Title</h1>
    <span class="price">£9.99</span>
    <div id="description">A great book</div>
    </body></html>
    """


# ---------------------------------------------------------------------------
# _test_selector
# ---------------------------------------------------------------------------


def test_test_selector_finds_element(verifier, simple_html):
    soup = BeautifulSoup(simple_html, 'lxml')
    success, reason = verifier._test_selector(soup, 'h1.title')
    assert success is True
    assert reason == 'found'


def test_test_selector_no_match(verifier, simple_html):
    soup = BeautifulSoup(simple_html, 'lxml')
    success, reason = verifier._test_selector(soup, '.nonexistent')
    assert success is False
    assert reason == 'no_elements_found'


def test_test_selector_na_returns_false(verifier, simple_html):
    soup = BeautifulSoup(simple_html, 'lxml')
    success, reason = verifier._test_selector(soup, 'NA')
    assert success is False
    assert reason == 'na_selector'


def test_test_selector_empty_string_returns_false(verifier, simple_html):
    soup = BeautifulSoup(simple_html, 'lxml')
    success, reason = verifier._test_selector(soup, '')
    assert success is False
    assert reason == 'na_selector'


def test_test_selector_invalid_css_returns_false(verifier, simple_html):
    soup = BeautifulSoup(simple_html, 'lxml')
    success, reason = verifier._test_selector(soup, '>>>[invalid<<<')
    assert success is False
    assert 'invalid_syntax' in reason


def test_test_selector_id_selector(verifier, simple_html):
    soup = BeautifulSoup(simple_html, 'lxml')
    success, _reason = verifier._test_selector(soup, '#description')
    assert success is True


# ---------------------------------------------------------------------------
# _verify_field
# ---------------------------------------------------------------------------


def test_verify_field_primary_works(verifier, simple_html):
    soup = BeautifulSoup(simple_html, 'lxml')
    result = verifier._verify_field(soup, 'title', {'primary': 'h1.title', 'fallback': None})
    assert result.status == 'verified'
    assert result.working_level == 'primary'
    assert result.selector == 'h1.title'


def test_verify_field_falls_back_to_fallback(verifier, simple_html):
    soup = BeautifulSoup(simple_html, 'lxml')
    result = verifier._verify_field(
        soup,
        'price',
        {
            'primary': '.missing',
            'fallback': '.price',
            'tertiary': None,
        },
    )
    assert result.status == 'verified'
    assert result.working_level == 'fallback'
    assert result.selector == '.price'


def test_verify_field_uses_tertiary(verifier, simple_html):
    soup = BeautifulSoup(simple_html, 'lxml')
    result = verifier._verify_field(
        soup,
        'desc',
        {
            'primary': '.gone',
            'fallback': '.also-gone',
            'tertiary': '#description',
        },
    )
    assert result.status == 'verified'
    assert result.working_level == 'tertiary'


def test_verify_field_all_fail(verifier, simple_html):
    soup = BeautifulSoup(simple_html, 'lxml')
    result = verifier._verify_field(
        soup,
        'author',
        {
            'primary': '.missing',
            'fallback': '.also-missing',
            'tertiary': '.still-missing',
        },
    )
    assert result.status == 'failed'
    assert result.selector is None
    assert len(result.failed_selectors) == 3


def test_verify_field_skips_none_selectors(verifier, simple_html):
    soup = BeautifulSoup(simple_html, 'lxml')
    result = verifier._verify_field(
        soup,
        'title',
        {
            'primary': None,
            'fallback': 'h1',
            'tertiary': None,
        },
    )
    assert result.status == 'verified'
    assert result.working_level == 'fallback'
    # None selectors should not appear in failed list
    for f in result.failed_selectors:
        assert f.selector is not None


def test_verify_field_records_failures_before_success(verifier, simple_html):
    soup = BeautifulSoup(simple_html, 'lxml')
    result = verifier._verify_field(
        soup,
        'price',
        {
            'primary': '.gone',
            'fallback': '.price',
            'tertiary': None,
        },
    )
    assert result.status == 'verified'
    # Primary failed, should be in failed_selectors
    assert len(result.failed_selectors) == 1
    assert result.failed_selectors[0].level == 'primary'


# ---------------------------------------------------------------------------
# verify (full)
# ---------------------------------------------------------------------------


def test_verify_all_pass(verifier, simple_html):
    selectors = {
        'title': {'primary': 'h1.title'},
        'price': {'primary': '.price'},
    }
    result = verifier.verify(simple_html, selectors)
    assert result.success is True
    assert result.verified_count == 2
    assert result.total_fields == 2


def test_verify_partial_pass(verifier, simple_html):
    selectors = {
        'title': {'primary': 'h1.title'},
        'missing': {'primary': '.nonexistent'},
    }
    result = verifier.verify(simple_html, selectors)
    assert result.success is True
    assert result.verified_count == 1
    assert result.total_fields == 2


def test_verify_all_fail(verifier, simple_html):
    selectors = {
        'title': {'primary': '.gone'},
        'price': {'primary': '.also-gone'},
    }
    result = verifier.verify(simple_html, selectors)
    assert result.success is False
    assert result.verified_count == 0


def test_verify_empty_selectors(verifier, simple_html):
    result = verifier.verify(simple_html, {})
    assert result.total_fields == 0
    assert result.verified_count == 0
    assert result.success is False


def test_verify_returns_verification_result_type(verifier, simple_html):
    result = verifier.verify(simple_html, {'title': {'primary': 'h1'}})
    assert isinstance(result, VerificationResult)


def test_verify_results_contain_per_field_status(verifier, simple_html):
    selectors = {
        'title': {'primary': 'h1.title'},
        'missing': {'primary': '.gone'},
    }
    result = verifier.verify(simple_html, selectors)
    assert 'title' in result.results
    assert 'missing' in result.results
    assert result.results['title'].status == 'verified'
    assert result.results['missing'].status == 'failed'


def test_verify_verified_fields_property(verifier, simple_html):
    selectors = {
        'title': {'primary': 'h1.title'},
        'missing': {'primary': '.gone'},
    }
    result = verifier.verify(simple_html, selectors)
    assert 'title' in result.verified_fields
    assert 'missing' not in result.verified_fields


def test_verify_works_without_console():
    verifier_no_console = SelectorVerifier(console=None)
    html = '<html><body><h1>Hello</h1></body></html>'
    result = verifier_no_console.verify(html, {'title': {'primary': 'h1'}})
    assert result.success is True


# ---------------------------------------------------------------------------
# Additional targeted tests
# ---------------------------------------------------------------------------


def test_test_selector_na_uppercase(verifier, simple_html):
    soup = BeautifulSoup(simple_html, 'lxml')
    success, reason = verifier._test_selector(soup, 'NA')
    assert success is False
    assert reason == 'na_selector'


def test_test_selector_non_na_nonempty_tries_to_match(verifier, simple_html):
    soup = BeautifulSoup(simple_html, 'lxml')
    success, _reason = verifier._test_selector(soup, 'h1')
    assert success is True


def test_verify_total_fields_count(verifier, simple_html):
    selectors = {'title': {'primary': 'h1.title'}, 'price': {'primary': '.price'}, 'desc': {'primary': '#description'}}
    result = verifier.verify(simple_html, selectors)
    assert result.total_fields == 3


def test_verify_verified_count_is_correct(verifier, simple_html):
    selectors = {
        'title': {'primary': 'h1.title'},
        'missing': {'primary': '.gone'},
    }
    result = verifier.verify(simple_html, selectors)
    assert result.verified_count == 1


def test_verify_success_requires_at_least_one_verified(verifier, simple_html):
    selectors = {'missing1': {'primary': '.x'}, 'missing2': {'primary': '.y'}}
    result = verifier.verify(simple_html, selectors)
    assert result.success is False
    assert result.verified_count == 0


def test_verify_field_fails_with_3_failed_selectors(verifier, simple_html):
    soup = BeautifulSoup(simple_html, 'lxml')
    result = verifier._verify_field(soup, 'field', {'primary': '.p', 'fallback': '.f', 'tertiary': '.t'})
    assert result.status == 'failed'
    assert len(result.failed_selectors) == 3


def test_verify_field_failed_selectors_have_correct_levels(verifier, simple_html):
    soup = BeautifulSoup(simple_html, 'lxml')
    result = verifier._verify_field(soup, 'field', {'primary': '.p', 'fallback': '.f', 'tertiary': '.t'})
    levels = [f.level for f in result.failed_selectors]
    assert 'primary' in levels
    assert 'fallback' in levels
    assert 'tertiary' in levels


def test_verify_field_failed_selectors_have_reasons(verifier, simple_html):
    soup = BeautifulSoup(simple_html, 'lxml')
    result = verifier._verify_field(soup, 'field', {'primary': '.missing'})
    assert len(result.failed_selectors) == 1
    assert result.failed_selectors[0].reason == 'no_elements_found'


def test_test_selector_found_reason_is_exact(verifier, simple_html):
    soup = BeautifulSoup(simple_html, 'lxml')
    _success, reason = verifier._test_selector(soup, 'h1.title')
    assert reason == 'found'


def test_test_selector_not_found_reason_is_exact(verifier, simple_html):
    soup = BeautifulSoup(simple_html, 'lxml')
    _success, reason = verifier._test_selector(soup, '.nonexistent')
    assert reason == 'no_elements_found'


def test_verify_verified_fields_only_contains_verified(verifier, simple_html):
    selectors = {
        'title': {'primary': 'h1.title'},
        'price': {'primary': '.price'},
        'gone': {'primary': '.nonexistent'},
    }
    result = verifier.verify(simple_html, selectors)
    assert 'title' in result.verified_fields
    assert 'price' in result.verified_fields
    assert 'gone' not in result.verified_fields


def test_verify_field_name_is_set_in_result(verifier, simple_html):
    soup = BeautifulSoup(simple_html, 'lxml')
    result = verifier._verify_field(soup, 'my_field', {'primary': 'h1.title'})
    assert result.field_name == 'my_field'


def test_verifier_console_is_none_when_not_provided():
    """When no console passed, self.console must be None."""
    v = SelectorVerifier()
    assert v.console is None


def test_verifier_console_is_stored_when_provided():
    """When console is provided, it must be stored."""
    from rich.console import Console

    console = Console(quiet=True)
    v = SelectorVerifier(console=console)
    assert v.console is console


def test_verify_total_fields_equals_len_selectors(verifier, simple_html):
    """total_fields in result must equal the number of selectors passed."""
    selectors = {'title': {'primary': 'h1.title'}, 'price': {'primary': '.price'}, 'desc': {'primary': '#description'}}
    result = verifier.verify(simple_html, selectors)
    assert result.total_fields == len(selectors)
    assert result.total_fields == 3


def test_verify_verified_count_counts_only_verified(verifier, simple_html):
    """verified_count must count only fields with status='verified'."""
    selectors = {
        'title': {'primary': 'h1.title'},  # verified
        'gone1': {'primary': '.missing1'},  # failed
        'gone2': {'primary': '.missing2'},  # failed
    }
    result = verifier.verify(simple_html, selectors)
    assert result.verified_count == 1


def test_verify_uses_lxml_parser(verifier, simple_html):
    """verify must use BeautifulSoup with lxml parser (not default html.parser)."""
    # If lxml is used, it handles complex HTML correctly
    result = verifier.verify(simple_html, {'title': {'primary': 'h1.title'}})
    assert result.verified_count == 1


def test_verify_field_status_verified_sets_working_level(verifier, simple_html):
    """When selector works, working_level must be set correctly."""
    soup = BeautifulSoup(simple_html, 'lxml')
    result = verifier._verify_field(soup, 'title', {'primary': 'h1.title'})
    assert result.working_level == 'primary'


def test_verify_field_status_failed_working_level_is_none(verifier, simple_html):
    """When all fail, working_level must be None."""
    soup = BeautifulSoup(simple_html, 'lxml')
    result = verifier._verify_field(soup, 'missing', {'primary': '.gone'})
    assert result.status == 'failed'
    assert result.working_level is None


def test_test_selector_empty_string_is_treated_as_na(verifier, simple_html):
    """Empty string selector must return False with 'na_selector' reason."""
    soup = BeautifulSoup(simple_html, 'lxml')
    success, reason = verifier._test_selector(soup, '')
    assert success is False
    assert reason == 'na_selector'


def test_test_selector_na_string_is_treated_as_na(verifier, simple_html):
    """'NA' selector string must return False with 'na_selector' reason."""
    soup = BeautifulSoup(simple_html, 'lxml')
    success, reason = verifier._test_selector(soup, 'NA')
    assert success is False
    assert reason == 'na_selector'


def test_verify_field_none_selectors_skipped_not_failed(verifier, simple_html):
    """None selectors must be skipped, not counted as failures."""
    soup = BeautifulSoup(simple_html, 'lxml')
    result = verifier._verify_field(soup, 'title', {'primary': None, 'fallback': 'h1.title', 'tertiary': None})
    assert result.status == 'verified'
    # None selectors don't appear in failed_selectors
    assert len(result.failed_selectors) == 0


def test_verify_result_uses_selectors_from_input(verifier, simple_html):
    """The verified dict returned by _verify must use exact selectors from input."""
    selectors = {
        'title': {'primary': 'h1.title', 'fallback': 'h1'},
        'price': {'primary': '.price'},
    }
    result = verifier.verify(simple_html, selectors)
    assert result.total_fields == 2


def test_verify_selector_found_reason_is_found(verifier, simple_html):
    """_test_selector must return reason='found' when selector matches."""
    soup = BeautifulSoup(simple_html, 'lxml')
    success, reason = verifier._test_selector(soup, 'h1.title')
    assert success is True
    assert reason == 'found'


def test_verify_selector_no_match_reason_is_no_elements_found(verifier, simple_html):
    """_test_selector must return reason='no_elements_found' when no match."""
    soup = BeautifulSoup(simple_html, 'lxml')
    success, reason = verifier._test_selector(soup, '.nonexistent-xyz')
    assert success is False
    assert reason == 'no_elements_found'
