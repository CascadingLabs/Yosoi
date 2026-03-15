"""Unit tests for ContentExtractor."""

import pytest
from parsel import Selector
from rich.console import Console

import yosoi as ys
from yosoi.core.extraction.extractor import ContentExtractor
from yosoi.models.contract import Contract


def _make_extractor(contract=None) -> ContentExtractor:
    return ContentExtractor(console=Console(quiet=True), contract=contract)


# ---------------------------------------------------------------------------
# _extract_with_selector - body_text
# ---------------------------------------------------------------------------


def test_body_text_adjacent_spans_have_spaces():
    extractor = _make_extractor()
    html = '<p><span>Hello</span><span>World</span></p>'
    sel = Selector(text=html)
    result = extractor._extract_with_selector(sel, 'p', 'body_text')
    assert result == 'Hello World'


def test_body_text_multiple_paragraphs_joined_with_newlines():
    extractor = _make_extractor()
    html = '<div><p>First paragraph.</p><p>Second paragraph.</p></div>'
    sel = Selector(text=html)
    result = extractor._extract_with_selector(sel, 'p', 'body_text')
    assert result == 'First paragraph.\n\nSecond paragraph.'


def test_body_text_skips_empty_elements():
    extractor = _make_extractor()
    html = '<div><p>Content</p><p>   </p><p>More</p></div>'
    sel = Selector(text=html)
    result = extractor._extract_with_selector(sel, 'p', 'body_text')
    assert result is not None
    assert '\n\n\n\n' not in result
    assert 'Content' in result
    assert 'More' in result


def test_body_text_returns_none_when_no_elements():
    extractor = _make_extractor()
    html = '<div></div>'
    sel = Selector(text=html)
    result = extractor._extract_with_selector(sel, '.nonexistent', 'body_text')
    assert result is None


# ---------------------------------------------------------------------------
# _extract_with_selector - related_content
# ---------------------------------------------------------------------------


def test_related_content_extracts_links_with_href():
    extractor = _make_extractor()
    html = '<ul><li><a href="/article1">Article One</a></li><li><a href="/article2">Article Two</a></li></ul>'
    sel = Selector(text=html)
    result = extractor._extract_with_selector(sel, 'a', 'related_content')
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0] == {'text': 'Article One', 'href': '/article1'}


def test_related_content_handles_links_without_href():
    extractor = _make_extractor()
    html = '<span>Just text</span><span>More text</span>'
    sel = Selector(text=html)
    result = extractor._extract_with_selector(sel, 'span', 'related_content')
    # No href so returns strings, not dicts
    assert isinstance(result, list)
    assert 'Just text' in result


def test_related_content_returns_none_when_no_elements():
    extractor = _make_extractor()
    html = '<div></div>'
    sel = Selector(text=html)
    result = extractor._extract_with_selector(sel, '.missing', 'related_content')
    assert result is None


# ---------------------------------------------------------------------------
# _extract_with_selector - default field (first element)
# ---------------------------------------------------------------------------


def test_default_field_returns_first_match():
    extractor = _make_extractor()
    html = '<h1>First Title</h1><h1>Second Title</h1>'
    sel = Selector(text=html)
    result = extractor._extract_with_selector(sel, 'h1', 'title')
    assert result == 'First Title'


def test_default_field_returns_none_when_empty():
    extractor = _make_extractor()
    html = '<h1></h1>'
    sel = Selector(text=html)
    result = extractor._extract_with_selector(sel, 'h1', 'title')
    assert result is None


def test_default_field_returns_none_for_missing_selector():
    extractor = _make_extractor()
    html = '<p>content</p>'
    sel = Selector(text=html)
    result = extractor._extract_with_selector(sel, '.nonexistent', 'title')
    assert result is None


def test_invalid_selector_returns_none_gracefully():
    extractor = _make_extractor()
    html = '<p>content</p>'
    sel = Selector(text=html)
    result = extractor._extract_with_selector(sel, '>>>invalid<<<', 'title')
    assert result is None


# ---------------------------------------------------------------------------
# extract_content_with_html
# ---------------------------------------------------------------------------


def test_extract_content_with_html_returns_dict():
    class MyContract(Contract):
        title: str = ys.Title()

    extractor = _make_extractor(MyContract)
    html = '<html><body><h1 class="title">My Book</h1></body></html>'
    selectors = {'title': {'primary': 'h1.title'}}
    result = extractor.extract_content_with_html('https://x.com', html, selectors)
    assert result is not None
    assert result['title'] == 'My Book'


def test_extract_content_with_html_returns_none_when_nothing_extracted():
    class MyContract(Contract):
        title: str = ys.Title()

    extractor = _make_extractor(MyContract)
    html = '<html><body><p>No matches here</p></body></html>'
    selectors = {'title': {'primary': '.nonexistent'}}
    result = extractor.extract_content_with_html('https://x.com', html, selectors)
    assert result is None


def test_extract_content_uses_fallback_selector():
    class MyContract(Contract):
        title: str = ys.Title()

    extractor = _make_extractor(MyContract)
    html = '<html><body><div class="fallback-title">Fallback Title</div></body></html>'
    selectors = {'title': {'primary': '.primary-missing', 'fallback': '.fallback-title'}}
    result = extractor.extract_content_with_html('https://x.com', html, selectors)
    assert result is not None
    assert result['title'] == 'Fallback Title'


def test_extract_content_uses_tertiary_selector():
    class MyContract(Contract):
        title: str = ys.Title()

    extractor = _make_extractor(MyContract)
    html = '<html><body><span class="tertiary-title">Tertiary Title</span></body></html>'
    selectors = {'title': {'primary': '.p', 'fallback': '.f', 'tertiary': '.tertiary-title'}}
    result = extractor.extract_content_with_html('https://x.com', html, selectors)
    assert result is not None
    assert result['title'] == 'Tertiary Title'


def test_extract_content_skips_field_with_no_selector():
    class MyContract(Contract):
        title: str = ys.Title()
        price: float = ys.Price()

    extractor = _make_extractor(MyContract)
    html = '<html><body><h1>Title Here</h1></body></html>'
    # Only title has a selector
    selectors = {'title': {'primary': 'h1'}}
    result = extractor.extract_content_with_html('https://x.com', html, selectors)
    assert result is not None
    assert 'title' in result
    assert 'price' not in result


def test_extract_content_multiple_fields():
    class MyContract(Contract):
        title: str = ys.Title()
        price: float = ys.Price()

    extractor = _make_extractor(MyContract)
    html = '<html><body><h1>Great Book</h1><span class="price">$12.99</span></body></html>'
    selectors = {
        'title': {'primary': 'h1'},
        'price': {'primary': '.price'},
    }
    result = extractor.extract_content_with_html('https://x.com', html, selectors)
    assert result is not None
    assert result['title'] == 'Great Book'
    assert result['price'] == '$12.99'


# ---------------------------------------------------------------------------
# ContentExtractor - targeted mutant-killing tests
# ---------------------------------------------------------------------------


def test_extractor_without_contract_has_no_expected_fields():
    extractor = _make_extractor()
    assert extractor.expected_fields == ()


def test_extractor_with_contract_has_expected_fields():
    class MyContract(Contract):
        title: str = ys.Title()
        price: float = ys.Price()

    extractor = _make_extractor(MyContract)
    assert 'title' in extractor.expected_fields
    assert 'price' in extractor.expected_fields


def test_body_text_uses_double_newline_separator():
    extractor = _make_extractor()
    html = '<div><p>Para one.</p><p>Para two.</p></div>'
    sel = Selector(text=html)
    result = extractor._extract_with_selector(sel, 'p', 'body_text')
    assert isinstance(result, str)
    assert '\n\n' in result


def test_body_text_only_one_paragraph_no_double_newline():
    extractor = _make_extractor()
    html = '<div><p>Single para.</p></div>'
    sel = Selector(text=html)
    result = extractor._extract_with_selector(sel, 'p', 'body_text')
    assert isinstance(result, str)
    assert result == 'Single para.'
    assert '\n\n' not in result


def test_related_content_with_href_returns_dict_with_text_and_href():
    extractor = _make_extractor()
    html = '<a href="/link">Article</a>'
    sel = Selector(text=html)
    result = extractor._extract_with_selector(sel, 'a', 'related_content')
    assert isinstance(result, list)
    assert result[0] == {'text': 'Article', 'href': '/link'}


def test_related_content_without_href_returns_plain_text():
    extractor = _make_extractor()
    html = '<span>Text Only</span>'
    sel = Selector(text=html)
    result = extractor._extract_with_selector(sel, 'span', 'related_content')
    assert isinstance(result, list)
    assert 'Text Only' in result
    # No href, so plain string not dict
    assert isinstance(result[0], str)


def test_extract_content_uses_primary_when_available():
    class MyContract(Contract):
        title: str = ys.Title()

    extractor = _make_extractor(MyContract)
    html = '<html><body><h1 class="primary">Primary Title</h1><h2 class="fallback">Fallback</h2></body></html>'
    selectors = {'title': {'primary': 'h1.primary', 'fallback': 'h2.fallback'}}
    result = extractor.extract_content_with_html('https://x.com', html, selectors)
    assert result is not None
    assert result['title'] == 'Primary Title'


def test_extract_content_returns_none_when_no_fields():
    class EmptyContract(Contract):
        pass

    extractor = _make_extractor(EmptyContract)
    html = '<html><body><h1>Title</h1></body></html>'
    selectors = {'title': {'primary': 'h1'}}
    # No expected fields, so nothing to extract → return None
    result = extractor.extract_content_with_html('https://x.com', html, selectors)
    assert result is None


def test_extractor_no_contract_overridden_fields_is_empty_frozenset():
    """Without contract, _overridden_fields must be empty frozenset."""
    extractor = _make_extractor()
    assert extractor._overridden_fields == frozenset()


def test_extractor_with_contract_expected_fields_is_tuple():
    """expected_fields must be a tuple, not list or other."""

    class MyContract(Contract):
        title: str = ys.Title()

    extractor = _make_extractor(MyContract)
    assert isinstance(extractor.expected_fields, tuple)


def test_extractor_expected_fields_exact_names():
    """expected_fields must contain exact field names from contract."""

    class MyContract(Contract):
        title: str = ys.Title()
        price: float = ys.Price()

    extractor = _make_extractor(MyContract)
    assert set(extractor.expected_fields) == {'title', 'price'}


def test_body_text_separator_is_double_newline():
    """body_text paragraphs must be joined with '\\n\\n', not single newline."""
    extractor = _make_extractor()
    html = '<div><p>Para one.</p><p>Para two.</p><p>Para three.</p></div>'
    sel = Selector(text=html)
    result = extractor._extract_with_selector(sel, 'p', 'body_text')
    assert isinstance(result, str)
    assert result == 'Para one.\n\nPara two.\n\nPara three.'


def test_extract_selector_returns_none_when_empty_elements():
    """When selector matches no elements, must return None."""
    extractor = _make_extractor()
    html = '<div><p>Some content</p></div>'
    sel = Selector(text=html)
    result = extractor._extract_with_selector(sel, '.no-such-class', 'title')
    assert result is None


def test_related_content_empty_text_skipped():
    """Elements with no text should not appear in related_content results."""
    extractor = _make_extractor()
    html = '<div><a href="/link1">Text</a><a href="/link2"></a></div>'
    sel = Selector(text=html)
    result = extractor._extract_with_selector(sel, 'a', 'related_content')
    assert isinstance(result, list)
    # Only one link has text, so result should have 1 item
    assert len(result) == 1


def test_extract_uses_primary_not_fallback_when_primary_works():
    """When primary selector works, fallback must NOT be used."""

    class MyContract(Contract):
        title: str = ys.Title()

    extractor = _make_extractor(MyContract)
    html = '<html><body><h1 class="primary">Primary Title</h1><h2 class="fallback">Fallback Title</h2></body></html>'
    selectors = {'title': {'primary': 'h1.primary', 'fallback': 'h2.fallback'}}
    result = extractor.extract_content_with_html('https://x.com', html, selectors)
    assert result is not None
    # Must use primary, not fallback
    assert result['title'] == 'Primary Title'
    assert result['title'] != 'Fallback Title'


# ---------------------------------------------------------------------------
# Phase 1: New Parsel-specific tests
# ---------------------------------------------------------------------------


def test_extract_uses_parsel_selector():
    """ContentExtractor must use Parsel Selector, not BeautifulSoup."""
    extractor = _make_extractor()
    html = '<p>Hello</p>'
    sel = Selector(text=html)
    # _extract_with_selector accepts Selector instance
    result = extractor._extract_with_selector(sel, 'p', 'title')
    assert result == 'Hello'


def test_body_text_joins_all_text_nodes():
    """Nested spans must produce space-joined text via xpath .//text()."""
    extractor = _make_extractor()
    html = '<p><span>Hello</span><span>World</span></p>'
    sel = Selector(text=html)
    result = extractor._extract_with_selector(sel, 'p', 'body_text')
    # Both span texts must appear, joined with a space
    assert result is not None
    assert 'Hello' in result
    assert 'World' in result
    assert result == 'Hello World'


# ---------------------------------------------------------------------------
# Phase 3: Level-aware dispatch (_resolve)
# ---------------------------------------------------------------------------


def test_resolve_css_entry_extracts():
    from yosoi.models.selectors import SelectorEntry, SelectorLevel

    extractor = _make_extractor()
    html = '<h1>Title</h1>'
    sel = Selector(text=html)
    entry = SelectorEntry(type='css', value='h1')
    result = extractor._resolve(sel, entry, 'title', SelectorLevel.CSS)
    assert result == 'Title'


def test_resolve_skips_entry_above_max_level():
    from yosoi.models.selectors import SelectorEntry, SelectorLevel

    extractor = _make_extractor()
    html = '<h1>Title</h1>'
    sel = Selector(text=html)
    entry = SelectorEntry(type='xpath', value='//h1')
    result = extractor._resolve(sel, entry, 'title', SelectorLevel.CSS)
    assert result is None


def test_resolve_xpath_extracts_text():
    from yosoi.models.selectors import SelectorEntry, SelectorLevel

    extractor = _make_extractor()
    html = '<h1>XPath Title</h1>'
    sel = Selector(text=html)
    entry = SelectorEntry(type='xpath', value='//h1')
    result = extractor._resolve(sel, entry, 'title', SelectorLevel.XPATH)
    assert result == 'XPath Title'


def test_extract_content_respects_max_level():
    """XPath selectors above CSS ceiling must be skipped → field not extracted."""
    from yosoi.models.selectors import SelectorEntry, SelectorLevel

    class MyContract(Contract):
        title: str = ys.Title()

    extractor = _make_extractor(MyContract)
    html = '<html><body><h1>Title</h1></body></html>'
    # XPath entry should be skipped when max_level=CSS
    xpath_entry = SelectorEntry(type='xpath', value='//h1')
    selectors = {'title': {'primary': xpath_entry.model_dump()}}
    result = extractor.extract_content_with_html('https://x.com', html, selectors, max_level=SelectorLevel.CSS)
    assert result is None


# ---------------------------------------------------------------------------
# Coverage: lines 15, 20 — _coerce_entry returning None for unexpected types
# ---------------------------------------------------------------------------


def test_coerce_entry_returns_none_for_int():
    """_coerce_entry with a non-str/dict/SelectorEntry value returns None."""
    from yosoi.models.selectors import coerce_selector_entry as _coerce_entry

    assert _coerce_entry(42) is None


def test_coerce_entry_returns_none_for_list():
    """_coerce_entry with a list value returns None."""
    from yosoi.models.selectors import coerce_selector_entry as _coerce_entry

    assert _coerce_entry([1, 2, 3]) is None


def test_coerce_entry_returns_none_for_none():
    """_coerce_entry with None returns None."""
    from yosoi.models.selectors import coerce_selector_entry as _coerce_entry

    assert _coerce_entry(None) is None


def test_coerce_entry_returns_selector_entry_from_dict():
    """_coerce_entry with a dict returns SelectorEntry."""
    from yosoi.models.selectors import SelectorEntry
    from yosoi.models.selectors import coerce_selector_entry as _coerce_entry

    result = _coerce_entry({'value': 'h1.title', 'type': 'css'})
    assert isinstance(result, SelectorEntry)
    assert result.value == 'h1.title'


def test_coerce_entry_returns_selector_entry_from_string():
    """_coerce_entry with a non-empty string returns SelectorEntry."""
    from yosoi.models.selectors import SelectorEntry
    from yosoi.models.selectors import coerce_selector_entry as _coerce_entry

    result = _coerce_entry('h1.title')
    assert isinstance(result, SelectorEntry)
    assert result.value == 'h1.title'


def test_coerce_entry_returns_none_for_empty_string():
    """_coerce_entry with an empty string returns None."""
    from yosoi.models.selectors import coerce_selector_entry as _coerce_entry

    assert _coerce_entry('') is None


def test_coerce_entry_passthrough_selector_entry():
    """_coerce_entry with a SelectorEntry passes through."""
    from yosoi.models.selectors import SelectorEntry
    from yosoi.models.selectors import coerce_selector_entry as _coerce_entry

    entry = SelectorEntry(value='h1')
    assert _coerce_entry(entry) is entry


# ---------------------------------------------------------------------------
# Coverage: line 104 — overridden field prints different message
# ---------------------------------------------------------------------------


def test_extract_content_overridden_field_message():
    """When a field is in overridden_fields, a different message is printed."""
    from yosoi.types.field import Field as YsField

    class OverrideContract(Contract):
        title: str = YsField(description='Title', selector='h1.title')  # type: ignore[assignment]

    extractor = _make_extractor(OverrideContract)
    html = '<html><body><h1 class="title">My Title</h1></body></html>'
    selectors = {'title': {'primary': 'h1.title'}}
    result = extractor.extract_content_with_html('https://x.com', html, selectors)
    assert result is not None
    assert result['title'] == 'My Title'


# ---------------------------------------------------------------------------
# Coverage: line 140 — regex/jsonld strategies return None
# ---------------------------------------------------------------------------


def test_resolve_regex_strategy_returns_none():
    """Regex strategy is unsupported and returns None."""
    from yosoi.models.selectors import SelectorEntry, SelectorLevel

    extractor = _make_extractor()
    html = '<h1>Title</h1>'
    sel = Selector(text=html)
    entry = SelectorEntry(type='regex', value=r'\d+')
    result = extractor._resolve(sel, entry, 'title', SelectorLevel.REGEX)
    assert result is None


def test_resolve_jsonld_strategy_returns_none():
    """JSONLD strategy is unsupported and returns None."""
    from yosoi.models.selectors import SelectorEntry, SelectorLevel

    extractor = _make_extractor()
    html = '<h1>Title</h1>'
    sel = Selector(text=html)
    entry = SelectorEntry(type='jsonld', value='$.title')
    result = extractor._resolve(sel, entry, 'title', SelectorLevel.JSONLD)
    assert result is None


# ---------------------------------------------------------------------------
# Coverage: lines 190, 192-194 — xpath extraction exception handling
# ---------------------------------------------------------------------------


def test_extract_with_xpath_returns_none_for_no_match():
    """XPath selector that matches nothing returns None."""
    extractor = _make_extractor()
    html = '<p>content</p>'
    sel = Selector(text=html)
    result = extractor._extract_with_xpath_selector(sel, '//h1', 'title')
    assert result is None


def test_extract_with_xpath_returns_text():
    """XPath selector that matches returns extracted text."""
    extractor = _make_extractor()
    html = '<h1>XPath Title</h1>'
    sel = Selector(text=html)
    result = extractor._extract_with_xpath_selector(sel, '//h1', 'title')
    assert result == 'XPath Title'


def test_extract_with_xpath_exception_returns_none():
    """Invalid XPath expression returns None instead of raising."""
    extractor = _make_extractor()
    html = '<p>content</p>'
    sel = Selector(text=html)
    # Invalid xpath syntax
    result = extractor._extract_with_xpath_selector(sel, '///[[[invalid', 'title')
    assert result is None


# ---------------------------------------------------------------------------
# Coverage: lines 248-258 — quick_extract async method
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# list mode extraction
# ---------------------------------------------------------------------------


def test_list_mode_extracts_all_elements():
    """Multiple elements matching selector → list of all texts."""

    class AuthorContract(Contract):
        authors: list[str] = ys.Field(description='authors')

    extractor = _make_extractor(AuthorContract)
    html = (
        '<div><span class="author">Alice</span><span class="author">Bob</span><span class="author">Carol</span></div>'
    )
    sel = Selector(text=html)
    result = extractor._extract_with_selector(sel, 'span.author', 'authors')
    assert result == ['Alice', 'Bob', 'Carol']


def test_list_mode_single_element():
    """Single matching element → single-item list."""

    class AuthorContract(Contract):
        authors: list[str] = ys.Field(description='authors')

    extractor = _make_extractor(AuthorContract)
    html = '<div><span class="author">Alice</span></div>'
    sel = Selector(text=html)
    result = extractor._extract_with_selector(sel, 'span.author', 'authors')
    assert result == ['Alice']


def test_list_mode_empty_returns_none():
    """No matching elements → None."""

    class AuthorContract(Contract):
        authors: list[str] = ys.Field(description='authors')

    extractor = _make_extractor(AuthorContract)
    html = '<div></div>'
    sel = Selector(text=html)
    result = extractor._extract_with_selector(sel, 'span.author', 'authors')
    assert result is None


def test_list_mode_assigned_for_list_annotation():
    """list[str] field gets _field_modes[name] = 'list'."""

    class TagContract(Contract):
        tags: list[str] = ys.Field(description='tags')

    extractor = _make_extractor(TagContract)
    assert extractor._field_modes.get('tags') == 'list'


# ---------------------------------------------------------------------------
# quick_extract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quick_extract_success(mocker):
    """quick_extract fetches URL and extracts content."""
    extractor = _make_extractor()
    mock_response = mocker.MagicMock()
    mock_response.text = '<html><body><h1>Hello World</h1></body></html>'

    mock_client = mocker.AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = mocker.AsyncMock(return_value=False)
    mocker.patch('httpx.AsyncClient', return_value=mock_client)

    result = await extractor.quick_extract('https://example.com', 'h1', 'text')
    assert result == 'Hello World'


@pytest.mark.asyncio
async def test_quick_extract_returns_none_on_http_error(mocker):
    """quick_extract returns None when HTTP error occurs."""
    import httpx

    extractor = _make_extractor()
    mock_client = mocker.AsyncMock()
    mock_client.get.side_effect = httpx.ConnectError('failed')
    mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = mocker.AsyncMock(return_value=False)
    mocker.patch('httpx.AsyncClient', return_value=mock_client)

    result = await extractor.quick_extract('https://example.com', 'h1')
    assert result is None
