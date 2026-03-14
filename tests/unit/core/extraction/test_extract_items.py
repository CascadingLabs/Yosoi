"""Unit tests for ContentExtractor.extract_items (multi-item extraction)."""

from rich.console import Console

import yosoi as ys
from yosoi.core.extraction.extractor import ContentExtractor
from yosoi.models.contract import Contract


def _make_extractor(contract: type[Contract] | None = None) -> ContentExtractor:
    return ContentExtractor(console=Console(quiet=True), contract=contract)


# ---------------------------------------------------------------------------
# Catalog HTML fixture
# ---------------------------------------------------------------------------

CATALOG_HTML = """\
<html><body>
<div class="product-card">
  <h2 class="name">Iron Pickaxe</h2>
  <span class="price">14.50 Gold</span>
</div>
<div class="product-card">
  <h2 class="name">Steel Anvil</h2>
  <span class="price">89.00 Gold</span>
</div>
<div class="product-card">
  <h2 class="name">Bronze Shield</h2>
  <span class="price">45.00 Gold</span>
</div>
</body></html>
"""


class ProductContract(Contract):
    name: str = ys.Title()
    price: str = ys.Field(description='Product price')


SELECTORS = {
    'name': {'primary': 'h2.name'},
    'price': {'primary': 'span.price'},
}


# ---------------------------------------------------------------------------
# extract_items — happy path
# ---------------------------------------------------------------------------


def test_extract_items_returns_list_of_dicts():
    extractor = _make_extractor(ProductContract)
    result = extractor.extract_items(
        'https://shop.example.com/catalog',
        CATALOG_HTML,
        SELECTORS,
        '.product-card',
    )
    assert result is not None
    assert isinstance(result, list)
    assert len(result) == 3


def test_extract_items_first_item_has_correct_fields():
    extractor = _make_extractor(ProductContract)
    result = extractor.extract_items(
        'https://shop.example.com/catalog',
        CATALOG_HTML,
        SELECTORS,
        '.product-card',
    )
    assert result is not None
    assert result[0]['name'] == 'Iron Pickaxe'
    assert result[0]['price'] == '14.50 Gold'


def test_extract_items_all_items_have_both_fields():
    extractor = _make_extractor(ProductContract)
    result = extractor.extract_items(
        'https://shop.example.com/catalog',
        CATALOG_HTML,
        SELECTORS,
        '.product-card',
    )
    assert result is not None
    for item in result:
        assert 'name' in item
        assert 'price' in item


# ---------------------------------------------------------------------------
# extract_items — edge cases
# ---------------------------------------------------------------------------


def test_extract_items_no_containers_returns_none():
    extractor = _make_extractor(ProductContract)
    result = extractor.extract_items(
        'https://shop.example.com/catalog',
        CATALOG_HTML,
        SELECTORS,
        '.nonexistent-container',
    )
    assert result is None


def test_extract_items_empty_containers_returns_none():
    """Containers exist but selectors don't match anything inside them."""
    html = '<div class="card"></div><div class="card"></div>'
    extractor = _make_extractor(ProductContract)
    result = extractor.extract_items(
        'https://shop.example.com/catalog',
        html,
        SELECTORS,
        '.card',
    )
    assert result is None


def test_extract_items_uses_fallback_selector():
    html = """\
    <div class="item">
      <h3 class="fallback-name">Fallback Item</h3>
    </div>
    """
    selectors = {
        'name': {'primary': 'h2.name', 'fallback': 'h3.fallback-name'},
        'price': {'primary': 'span.price'},
    }
    extractor = _make_extractor(ProductContract)
    result = extractor.extract_items('https://x.com', html, selectors, '.item')
    assert result is not None
    assert len(result) == 1
    assert result[0]['name'] == 'Fallback Item'


def test_extract_items_single_container():
    """Single container should return a list with one item."""
    html = """\
    <div class="product-card">
      <h2 class="name">Only Item</h2>
      <span class="price">10 Gold</span>
    </div>
    """
    extractor = _make_extractor(ProductContract)
    result = extractor.extract_items('https://x.com', html, SELECTORS, '.product-card')
    assert result is not None
    assert len(result) == 1
    assert result[0]['name'] == 'Only Item'


def test_extract_items_without_contract_has_no_fields():
    """Without a contract, expected_fields is empty, so nothing is extracted."""
    extractor = _make_extractor()
    result = extractor.extract_items('https://x.com', CATALOG_HTML, SELECTORS, '.product-card')
    # No expected_fields → no fields extracted → all items empty → returns None
    assert result is None
