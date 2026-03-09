"""Unit tests for ContentExtractor."""

from bs4 import BeautifulSoup
from rich.console import Console

from yosoi.core.extraction.extractor import ContentExtractor


def _make_extractor() -> ContentExtractor:
    return ContentExtractor(console=Console(quiet=True))


def test_body_text_adjacent_spans_have_spaces():
    """get_text(strip=True) concatenates adjacent inline elements — should have space."""
    extractor = _make_extractor()
    html = '<p><span>Hello</span><span>World</span></p>'
    soup = BeautifulSoup(html, 'html.parser')
    result = extractor._extract_with_selector(soup, 'p', 'body_text')
    assert result == 'Hello World'


def test_body_text_multiple_paragraphs_joined_with_newlines():
    """Multiple paragraph elements should be joined with double newlines."""
    extractor = _make_extractor()
    html = '<div><p>First paragraph.</p><p>Second paragraph.</p></div>'
    soup = BeautifulSoup(html, 'html.parser')
    result = extractor._extract_with_selector(soup, 'p', 'body_text')
    assert result == 'First paragraph.\n\nSecond paragraph.'
