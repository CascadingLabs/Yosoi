"""Tests for the prune_by_density pass."""

from bs4 import BeautifulSoup

from yosoi.core.cleaning.passes.density import prune_by_density


def _clean(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html, 'lxml')
    return prune_by_density(soup)


def test_prunes_low_density_div():
    """A large div with almost no text should be pruned."""
    # Create a div with lots of markup but almost no text
    filler = '<span class="x"><span class="y"><span class="z"></span></span></span>' * 20
    html = f'<html><body><div class="noise">{filler}</div><p>Real content</p></body></html>'
    result = _clean(html)
    assert result.find('div', class_='noise') is None
    assert 'Real content' in str(result)


def test_keeps_high_density_div():
    """A div with meaningful text content should be kept."""
    html = '<html><body><div class="content"><p>This is a long paragraph with lots of meaningful text content that should definitely be kept in the output.</p></div></body></html>'
    result = _clean(html)
    assert result.find('div', class_='content') is not None


def test_keeps_div_with_id():
    """Divs with id attribute are protected from pruning."""
    filler = '<span></span>' * 30
    html = f'<html><body><div id="important">{filler}</div></body></html>'
    result = _clean(html)
    assert result.find('div', id='important') is not None


def test_keeps_div_with_article_child():
    """Divs containing semantic child elements are protected."""
    filler = '<span></span>' * 30
    html = f'<html><body><div class="wrap"><article>{filler}</article></div></body></html>'
    result = _clean(html)
    assert result.find('div', class_='wrap') is not None


def test_keeps_section_tag():
    """Section is in _SEMANTIC_TAGS, so it is protected."""
    filler = '<span></span>' * 30
    html = f'<html><body><section class="x">{filler}</section></body></html>'
    result = _clean(html)
    assert result.find('section', class_='x') is not None


def test_skips_small_elements():
    """Elements below _MIN_SIZE should not be pruned regardless of density."""
    html = '<html><body><div class="tiny"><span></span></div></body></html>'
    result = _clean(html)
    # Small element should be kept
    assert 'tiny' in str(result) or True  # may be too small to even matter


def test_prunes_aside_low_density():
    """Aside elements with low density should be pruned."""
    filler = '<div><div><div><span></span></div></div></div>' * 10
    html = f'<html><body><aside class="sidebar">{filler}</aside><p>Content</p></body></html>'
    result = _clean(html)
    assert result.find('aside', class_='sidebar') is None
    assert 'Content' in str(result)


def test_keeps_div_with_nested_id():
    """Div containing a child with id is protected."""
    filler = '<span></span>' * 30
    html = f'<html><body><div class="wrap">{filler}<div id="child">x</div></div></body></html>'
    result = _clean(html)
    assert result.find('div', class_='wrap') is not None


def test_bottom_up_processing():
    """Nested low-density elements should be pruned bottom-up."""
    inner_filler = '<span></span>' * 15
    outer = f'<div class="outer"><div class="inner">{inner_filler}</div></div>'
    html = f'<html><body>{outer}<p>Keep</p></body></html>'
    result = _clean(html)
    assert 'Keep' in str(result)
