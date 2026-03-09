"""Unit tests for ContentExtractor."""

from bs4 import BeautifulSoup
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
    soup = BeautifulSoup(html, 'html.parser')
    result = extractor._extract_with_selector(soup, 'p', 'body_text')
    assert result == 'Hello World'


def test_body_text_multiple_paragraphs_joined_with_newlines():
    extractor = _make_extractor()
    html = '<div><p>First paragraph.</p><p>Second paragraph.</p></div>'
    soup = BeautifulSoup(html, 'html.parser')
    result = extractor._extract_with_selector(soup, 'p', 'body_text')
    assert result == 'First paragraph.\n\nSecond paragraph.'


def test_body_text_skips_empty_elements():
    extractor = _make_extractor()
    html = '<div><p>Content</p><p>   </p><p>More</p></div>'
    soup = BeautifulSoup(html, 'html.parser')
    result = extractor._extract_with_selector(soup, 'p', 'body_text')
    assert result is not None
    assert '\n\n\n\n' not in result
    assert 'Content' in result
    assert 'More' in result


def test_body_text_returns_none_when_no_elements():
    extractor = _make_extractor()
    html = '<div></div>'
    soup = BeautifulSoup(html, 'html.parser')
    result = extractor._extract_with_selector(soup, '.nonexistent', 'body_text')
    assert result is None


# ---------------------------------------------------------------------------
# _extract_with_selector - related_content
# ---------------------------------------------------------------------------


def test_related_content_extracts_links_with_href():
    extractor = _make_extractor()
    html = '<ul><li><a href="/article1">Article One</a></li><li><a href="/article2">Article Two</a></li></ul>'
    soup = BeautifulSoup(html, 'html.parser')
    result = extractor._extract_with_selector(soup, 'a', 'related_content')
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0] == {'text': 'Article One', 'href': '/article1'}


def test_related_content_handles_links_without_href():
    extractor = _make_extractor()
    html = '<span>Just text</span><span>More text</span>'
    soup = BeautifulSoup(html, 'html.parser')
    result = extractor._extract_with_selector(soup, 'span', 'related_content')
    # No href so returns strings, not dicts
    assert isinstance(result, list)
    assert 'Just text' in result


def test_related_content_returns_none_when_no_elements():
    extractor = _make_extractor()
    html = '<div></div>'
    soup = BeautifulSoup(html, 'html.parser')
    result = extractor._extract_with_selector(soup, '.missing', 'related_content')
    assert result is None


# ---------------------------------------------------------------------------
# _extract_with_selector - default field (first element)
# ---------------------------------------------------------------------------


def test_default_field_returns_first_match():
    extractor = _make_extractor()
    html = '<h1>First Title</h1><h1>Second Title</h1>'
    soup = BeautifulSoup(html, 'html.parser')
    result = extractor._extract_with_selector(soup, 'h1', 'title')
    assert result == 'First Title'


def test_default_field_returns_none_when_empty():
    extractor = _make_extractor()
    html = '<h1></h1>'
    soup = BeautifulSoup(html, 'html.parser')
    result = extractor._extract_with_selector(soup, 'h1', 'title')
    assert result is None


def test_default_field_returns_none_for_missing_selector():
    extractor = _make_extractor()
    html = '<p>content</p>'
    soup = BeautifulSoup(html, 'html.parser')
    result = extractor._extract_with_selector(soup, '.nonexistent', 'title')
    assert result is None


def test_invalid_selector_returns_none_gracefully():
    extractor = _make_extractor()
    html = '<p>content</p>'
    soup = BeautifulSoup(html, 'html.parser')
    result = extractor._extract_with_selector(soup, '>>>invalid<<<', 'title')
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
