"""Unit tests for SelectorVerifier."""

import pytest
from parsel import Selector
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
    sel = Selector(text=simple_html)
    success, reason = verifier._test_selector(sel, 'h1.title')
    assert success is True
    assert reason == 'found'


def test_test_selector_no_match(verifier, simple_html):
    sel = Selector(text=simple_html)
    success, reason = verifier._test_selector(sel, '.nonexistent')
    assert success is False
    assert reason == 'no_elements_found'


def test_test_selector_na_returns_false(verifier, simple_html):
    sel = Selector(text=simple_html)
    success, reason = verifier._test_selector(sel, 'NA')
    assert success is False
    assert reason == 'na_selector'


def test_test_selector_empty_string_returns_false(verifier, simple_html):
    sel = Selector(text=simple_html)
    success, reason = verifier._test_selector(sel, '')
    assert success is False
    assert reason == 'na_selector'


def test_test_selector_invalid_css_returns_false(verifier, simple_html):
    sel = Selector(text=simple_html)
    success, reason = verifier._test_selector(sel, '>>>[invalid<<<')
    assert success is False
    assert 'invalid_syntax' in reason


def test_test_selector_id_selector(verifier, simple_html):
    sel = Selector(text=simple_html)
    success, _reason = verifier._test_selector(sel, '#description')
    assert success is True


# ---------------------------------------------------------------------------
# _verify_field
# ---------------------------------------------------------------------------


def test_verify_field_primary_works(verifier, simple_html):
    sel = Selector(text=simple_html)
    result = verifier._verify_field(sel, 'title', {'primary': 'h1.title', 'fallback': None})
    assert result.status == 'verified'
    assert result.working_level == 'primary'
    assert result.selector == 'h1.title'


def test_verify_field_falls_back_to_fallback(verifier, simple_html):
    sel = Selector(text=simple_html)
    result = verifier._verify_field(
        sel,
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
    sel = Selector(text=simple_html)
    result = verifier._verify_field(
        sel,
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
    sel = Selector(text=simple_html)
    result = verifier._verify_field(
        sel,
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
    sel = Selector(text=simple_html)
    result = verifier._verify_field(
        sel,
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
    sel = Selector(text=simple_html)
    result = verifier._verify_field(
        sel,
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


def test_test_selector_non_na_nonempty_tries_to_match(verifier, simple_html):
    sel = Selector(text=simple_html)
    success, _reason = verifier._test_selector(sel, 'h1')
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
    sel = Selector(text=simple_html)
    result = verifier._verify_field(sel, 'field', {'primary': '.p', 'fallback': '.f', 'tertiary': '.t'})
    assert result.status == 'failed'
    assert len(result.failed_selectors) == 3


def test_verify_field_failed_selectors_have_correct_levels(verifier, simple_html):
    sel = Selector(text=simple_html)
    result = verifier._verify_field(sel, 'field', {'primary': '.p', 'fallback': '.f', 'tertiary': '.t'})
    levels = [f.level for f in result.failed_selectors]
    assert 'primary' in levels
    assert 'fallback' in levels
    assert 'tertiary' in levels


def test_verify_field_failed_selectors_have_reasons(verifier, simple_html):
    sel = Selector(text=simple_html)
    result = verifier._verify_field(sel, 'field', {'primary': '.missing'})
    assert len(result.failed_selectors) == 1
    assert result.failed_selectors[0].reason == 'no_elements_found'


def test_test_selector_found_reason_is_exact(verifier, simple_html):
    sel = Selector(text=simple_html)
    _success, reason = verifier._test_selector(sel, 'h1.title')
    assert reason == 'found'


def test_test_selector_not_found_reason_is_exact(verifier, simple_html):
    sel = Selector(text=simple_html)
    _success, reason = verifier._test_selector(sel, '.nonexistent')
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
    sel = Selector(text=simple_html)
    result = verifier._verify_field(sel, 'my_field', {'primary': 'h1.title'})
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


def test_verify_uses_parsel_selector(verifier, simple_html):
    """verify must use Parsel Selector (not BeautifulSoup)."""
    # Parsel handles complex HTML correctly with lxml backend
    result = verifier.verify(simple_html, {'title': {'primary': 'h1.title'}})
    assert result.verified_count == 1


def test_verify_field_status_verified_sets_working_level(verifier, simple_html):
    """When selector works, working_level must be set correctly."""
    sel = Selector(text=simple_html)
    result = verifier._verify_field(sel, 'title', {'primary': 'h1.title'})
    assert result.working_level == 'primary'


def test_verify_field_status_failed_working_level_is_none(verifier, simple_html):
    """When all fail, working_level must be None."""
    sel = Selector(text=simple_html)
    result = verifier._verify_field(sel, 'missing', {'primary': '.gone'})
    assert result.status == 'failed'
    assert result.working_level is None


def test_test_selector_empty_string_is_treated_as_na(verifier, simple_html):
    """Empty string selector must return False with 'na_selector' reason."""
    sel = Selector(text=simple_html)
    success, reason = verifier._test_selector(sel, '')
    assert success is False
    assert reason == 'na_selector'


def test_verify_field_none_selectors_skipped_not_failed(verifier, simple_html):
    """None selectors must be skipped, not counted as failures."""
    sel = Selector(text=simple_html)
    result = verifier._verify_field(sel, 'title', {'primary': None, 'fallback': 'h1.title', 'tertiary': None})
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
    sel = Selector(text=simple_html)
    success, reason = verifier._test_selector(sel, 'h1.title')
    assert success is True
    assert reason == 'found'


def test_verify_selector_no_match_reason_is_no_elements_found(verifier, simple_html):
    """_test_selector must return reason='no_elements_found' when no match."""
    sel = Selector(text=simple_html)
    success, reason = verifier._test_selector(sel, '.nonexistent-xyz')
    assert success is False
    assert reason == 'no_elements_found'


def test_invalid_css_selector_returns_false_not_exception(verifier, simple_html):
    """Invalid CSS must not raise an exception — must return (False, 'invalid_syntax:...')."""
    sel = Selector(text=simple_html)
    # Should not raise
    success, reason = verifier._test_selector(sel, '>>>[invalid<<<')
    assert success is False
    assert reason.startswith('invalid_syntax')


# ---------------------------------------------------------------------------
# Phase 3: Level-aware dispatch
# ---------------------------------------------------------------------------


def test_test_selector_dispatches_xpath(verifier, simple_html):
    from yosoi.models.selectors import SelectorEntry

    sel = Selector(text=simple_html)
    entry = SelectorEntry(type='xpath', value='//h1')
    success, reason = verifier._test_selector(sel, entry)
    assert success is True
    assert reason == 'found'


def test_test_selector_regex_returns_unsupported(verifier, simple_html):
    from yosoi.models.selectors import SelectorEntry

    sel = Selector(text=simple_html)
    entry = SelectorEntry(type='regex', value=r'\d+\.\d+')
    success, reason = verifier._test_selector(sel, entry)
    assert success is False
    assert reason == 'unsupported_strategy'


def test_test_selector_jsonld_returns_unsupported(verifier, simple_html):
    from yosoi.models.selectors import SelectorEntry

    sel = Selector(text=simple_html)
    entry = SelectorEntry(type='jsonld', value='$.price')
    success, reason = verifier._test_selector(sel, entry)
    assert success is False
    assert reason == 'unsupported_strategy'


def test_verify_field_skips_regex_entry(verifier, simple_html):
    from yosoi.models.selectors import FieldSelectors, SelectorEntry, SelectorLevel

    sel = Selector(text=simple_html)
    regex_entry = SelectorEntry(type='regex', value=r'\d+')
    fs = FieldSelectors(primary=regex_entry)
    result = verifier._verify_field(sel, 'price', fs, max_level=SelectorLevel.REGEX)
    assert result.status == 'failed'
    assert result.failed_selectors[0].reason == 'unsupported_strategy'


def test_verify_skips_entry_above_max_level(verifier, simple_html):
    from yosoi.models.selectors import FieldSelectors, SelectorEntry, SelectorLevel

    # XPath entry but max_level=CSS → should be skipped, field fails
    sel = Selector(text=simple_html)
    xpath_entry = SelectorEntry(type='xpath', value='//h1[@class="title"]')
    fs = FieldSelectors(primary=xpath_entry)
    result = verifier._verify_field(sel, 'title', fs, max_level=SelectorLevel.CSS)
    assert result.status == 'failed'


def test_verify_uses_xpath_when_level_allows(verifier, simple_html):
    from yosoi.models.selectors import FieldSelectors, SelectorEntry, SelectorLevel

    sel = Selector(text=simple_html)
    xpath_entry = SelectorEntry(type='xpath', value='//h1')
    fs = FieldSelectors(primary=xpath_entry)
    result = verifier._verify_field(sel, 'title', fs, max_level=SelectorLevel.XPATH)
    assert result.status == 'verified'


def test_verify_max_level_propagated(verifier, simple_html):
    from yosoi.models.selectors import SelectorLevel

    # XPath-only selectors in dict form; verify() with CSS ceiling → all fail
    selectors = {'title': {'primary': '//h1'}}  # looks like xpath but stored as string → css
    result = verifier.verify(simple_html, selectors, max_level=SelectorLevel.CSS)
    # '//h1' as a CSS selector won't match, so it should fail
    assert result.results['title'].status == 'failed'


# ---------------------------------------------------------------------------
# Coverage: lines 19, 24 — _coerce_entry for dict and str inputs
# ---------------------------------------------------------------------------


def test_coerce_entry_dict_creates_selector_entry():
    """_coerce_entry with a dict returns SelectorEntry."""
    from yosoi.models.selectors import SelectorEntry
    from yosoi.models.selectors import coerce_selector_entry as _coerce_entry

    result = _coerce_entry({'value': 'h1', 'type': 'css'})
    assert isinstance(result, SelectorEntry)
    assert result.value == 'h1'


def test_coerce_entry_str_creates_selector_entry():
    """_coerce_entry with a string returns SelectorEntry."""
    from yosoi.models.selectors import SelectorEntry
    from yosoi.models.selectors import coerce_selector_entry as _coerce_entry

    result = _coerce_entry('.price')
    assert isinstance(result, SelectorEntry)
    assert result.value == '.price'


def test_coerce_entry_returns_none_for_int():
    """_coerce_entry with unsupported type returns None."""
    from yosoi.models.selectors import coerce_selector_entry as _coerce_entry

    assert _coerce_entry(123) is None


def test_coerce_entry_passthrough_selector_entry():
    """_coerce_entry with SelectorEntry passes through."""
    from yosoi.models.selectors import SelectorEntry
    from yosoi.models.selectors import coerce_selector_entry as _coerce_entry

    entry = SelectorEntry(value='h1')
    assert _coerce_entry(entry) is entry


# ---------------------------------------------------------------------------
# Coverage: line 177 — _print_field_result returns early when console is None
# ---------------------------------------------------------------------------


def test_print_field_result_returns_early_when_no_console():
    """_print_field_result returns early without error when console is None."""
    from yosoi.models import FieldVerificationResult

    v = SelectorVerifier(console=None)
    result = FieldVerificationResult(field_name='title', status='verified', working_level='primary', selector='h1')
    # Should not raise
    v._print_field_result(result)


# ---------------------------------------------------------------------------
# Coverage: line 183 — printing fallback/tertiary working selector
# ---------------------------------------------------------------------------


def test_print_field_result_fallback_selector(simple_html):
    """_print_field_result prints 'using fallback' for non-primary working levels."""
    v = SelectorVerifier(console=Console(quiet=True))
    sel = Selector(text=simple_html)
    result = v._verify_field(
        sel,
        'price',
        {'primary': '.missing', 'fallback': '.price'},
    )
    assert result.status == 'verified'
    assert result.working_level == 'fallback'
    # Should not raise when printing
    v._print_field_result(result)


def test_print_field_result_tertiary_selector(simple_html):
    """_print_field_result prints 'using tertiary' for tertiary working level."""
    v = SelectorVerifier(console=Console(quiet=True))
    sel = Selector(text=simple_html)
    result = v._verify_field(
        sel,
        'desc',
        {'primary': '.gone', 'fallback': '.also-gone', 'tertiary': '#description'},
    )
    assert result.status == 'verified'
    assert result.working_level == 'tertiary'
    v._print_field_result(result)


# ---------------------------------------------------------------------------
# Coverage: lines 200-212 — quick_test async method
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quick_test_success(mocker):
    """quick_test returns True when selector finds element with text."""
    v = SelectorVerifier()
    mock_response = mocker.MagicMock()
    mock_response.text = '<html><body><h1>Hello World</h1></body></html>'

    mock_client = mocker.AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = mocker.AsyncMock(return_value=False)
    mocker.patch('httpx.AsyncClient', return_value=mock_client)

    result = await v.quick_test('https://example.com', 'h1')
    assert result is True


@pytest.mark.asyncio
async def test_quick_test_no_match(mocker):
    """quick_test returns False when selector finds no elements."""
    v = SelectorVerifier()
    mock_response = mocker.MagicMock()
    mock_response.text = '<html><body><p>No heading</p></body></html>'

    mock_client = mocker.AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = mocker.AsyncMock(return_value=False)
    mocker.patch('httpx.AsyncClient', return_value=mock_client)

    result = await v.quick_test('https://example.com', 'h1')
    assert result is False


@pytest.mark.asyncio
async def test_quick_test_http_error(mocker):
    """quick_test returns False on HTTP error."""
    import httpx

    v = SelectorVerifier()
    mock_client = mocker.AsyncMock()
    mock_client.get.side_effect = httpx.ConnectError('failed')
    mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = mocker.AsyncMock(return_value=False)
    mocker.patch('httpx.AsyncClient', return_value=mock_client)

    result = await v.quick_test('https://example.com', 'h1')
    assert result is False


def test_pipeline_accepts_selector_level(mocker, tmp_path):
    from yosoi.core.pipeline import Pipeline
    from yosoi.models.defaults import NewsArticle
    from yosoi.models.selectors import SelectorLevel

    mocker.patch('yosoi.storage.persistence.init_yosoi', side_effect=[tmp_path / 'sel', tmp_path / 'content'])
    mocker.patch('yosoi.storage.tracking.get_tracking_path', return_value=tmp_path / 'tracking.json')
    mocker.patch('yosoi.utils.files.is_initialized', return_value=True)
    mocker.patch('yosoi.utils.logging.setup_local_logging', return_value=str(tmp_path / 'test.log'))
    mocker.patch('yosoi.core.discovery.agent.Agent')
    mocker.patch('yosoi.core.discovery.agent.create_model')

    from yosoi.core.discovery.config import LLMConfig

    cfg = LLMConfig(provider='test', model_name='test-model', api_key='fake')
    pipeline = Pipeline(cfg, contract=NewsArticle, selector_level=SelectorLevel.XPATH)
    assert pipeline.selector_level == SelectorLevel.XPATH
