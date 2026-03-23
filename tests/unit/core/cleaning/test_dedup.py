"""Tests for the deduplicate_siblings pass."""

from bs4 import BeautifulSoup, Tag

from yosoi.core.cleaning.passes.dedup import (
    _descendant_class_set,
    _select_diverse,
    _structural_signature,
    deduplicate_siblings,
)


def _clean(html: str, **kwargs) -> BeautifulSoup:
    soup = BeautifulSoup(html, 'lxml')
    return deduplicate_siblings(soup, **kwargs)


def test_dedup_identical_divs_above_threshold():
    cards = ''.join(f'<div class="card"><p>Item {i}</p></div>' for i in range(6))
    html = f'<html><body>{cards}</body></html>'
    result = _clean(html)
    remaining = result.find_all('div', class_='card')
    assert len(remaining) == 3


def test_keeps_group_below_threshold():
    cards = ''.join(f'<div class="card"><p>Item {i}</p></div>' for i in range(4))
    html = f'<html><body>{cards}</body></html>'
    result = _clean(html)
    remaining = result.find_all('div', class_='card')
    assert len(remaining) == 4


def test_dedup_exactly_at_threshold():
    """Group of exactly min_group (5) should be deduped."""
    cards = ''.join(f'<div class="card"><p>Item {i}</p></div>' for i in range(5))
    html = f'<html><body>{cards}</body></html>'
    result = _clean(html)
    remaining = result.find_all('div', class_='card')
    assert len(remaining) == 3


def test_dedup_with_custom_keep():
    cards = ''.join(f'<div class="card"><p>Item {i}</p></div>' for i in range(6))
    html = f'<html><body>{cards}</body></html>'
    result = _clean(html, keep=2)
    remaining = result.find_all('div', class_='card')
    assert len(remaining) == 2


def test_dedup_preserves_different_signatures():
    """Different tag/attr combos should not be grouped together."""
    html = '<html><body>'
    html += '<div class="a">1</div><div class="a">2</div><div class="a">3</div>'
    html += '<div class="a">4</div><div class="a">5</div><div class="a">6</div>'
    html += '<p class="b">X</p><p class="b">Y</p>'
    html += '</body></html>'
    result = _clean(html)
    assert len(result.find_all('div', class_='a')) == 3
    assert len(result.find_all('p', class_='b')) == 2


def test_dedup_non_consecutive_groups_separate():
    """Groups broken by a different element should be treated independently."""
    html = '<html><body>'
    html += '<div class="c">1</div><div class="c">2</div><div class="c">3</div>'
    html += '<hr/>'
    html += '<div class="c">4</div><div class="c">5</div><div class="c">6</div>'
    html += '</body></html>'
    result = _clean(html)
    # Each group of 3 is below threshold, so all should remain
    assert len(result.find_all('div', class_='c')) == 6


def test_structural_signature_matches_on_tag_and_attrs():
    soup = BeautifulSoup('<div class="x" id="y">text</div>', 'lxml')
    tag = soup.find('div')
    sig = _structural_signature(tag)
    assert sig[0] == 'div'
    assert set(sig[1]) == {'class', 'id'}


def test_dedup_nested_lists():
    """Dedup should work on nested list items too."""
    items = ''.join(f'<li>Item {i}</li>' for i in range(7))
    html = f'<html><body><ul>{items}</ul></body></html>'
    result = _clean(html)
    remaining = result.find_all('li')
    assert len(remaining) == 3


def test_preserves_content_in_kept_items():
    cards = ''.join(f'<div class="card"><p>Item {i}</p></div>' for i in range(6))
    html = f'<html><body>{cards}</body></html>'
    result = _clean(html)
    text = result.get_text()
    # First item is always kept as anchor
    assert 'Item 0' in text


# ---------------------------------------------------------------------------
# Diversity-aware selection
# ---------------------------------------------------------------------------


def test_diversity_keeps_items_with_unique_classes():
    """Dedup should prefer items that add unseen class names."""
    # 6 product cards: most are plain, but #3 has a promo badge and #5 has review count
    cards = []
    for i in range(6):
        inner = f'<span class="name">Item {i}</span>'
        if i == 3:
            inner += '<span class="promoBadge">SALE</span>'
        if i == 5:
            inner += '<span class="reviewCount">42 reviews</span>'
        cards.append(f'<div class="card">{inner}</div>')
    html = f'<html><body>{"".join(cards)}</body></html>'
    result = _clean(html, keep=3)
    result_str = str(result)
    # Both unique classes should survive in the kept items
    assert 'promoBadge' in result_str
    assert 'reviewCount' in result_str


def test_diversity_first_item_always_kept():
    """The first item in a group is always selected as anchor."""
    cards = [f'<div class="card"><p>Item {i}</p></div>' for i in range(6)]
    html = f'<html><body>{"".join(cards)}</body></html>'
    result = _clean(html)
    assert 'Item 0' in result.get_text()


def test_select_diverse_with_identical_items():
    """When all items are identical, just pick the first N."""
    soup = BeautifulSoup('<div><p class="a">x</p><p class="a">y</p><p class="a">z</p></div>', 'lxml')
    tags = [t for t in soup.find_all('p') if isinstance(t, Tag)]
    selected = _select_diverse(tags, 2)
    assert len(selected) == 2


def test_descendant_class_set_collects_nested():
    """_descendant_class_set should find classes in nested descendants."""
    soup = BeautifulSoup('<div class="card"><span class="name">X</span><span class="price">$5</span></div>', 'lxml')
    tag = soup.find('div', class_='card')
    classes = _descendant_class_set(tag)
    assert 'card' in classes
    assert 'name' in classes
    assert 'price' in classes
