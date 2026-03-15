"""Tests for ContentExtractor nested contract flattening and unflattening."""

import pytest
from rich.console import Console

import yosoi as ys
from yosoi.core.extraction.extractor import ContentExtractor

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


class _Price(ys.Contract):
    amount: float = ys.Price()
    currency: str = ys.Field(description='Currency symbol')


class _ProductContract(ys.Contract):
    root = ys.css('.product-card')
    name: str = ys.Title()
    price: _Price = ys.Field(description='Product price info')  # type: ignore[assignment]


@pytest.fixture
def extractor() -> ContentExtractor:
    return ContentExtractor(console=Console(quiet=True), contract=_ProductContract)


# ---------------------------------------------------------------------------
# expected_fields
# ---------------------------------------------------------------------------


def test_extractor_expands_expected_fields(extractor: ContentExtractor) -> None:
    assert set(extractor.expected_fields) == {'name', 'price_amount', 'price_currency'}


# ---------------------------------------------------------------------------
# _unflatten
# ---------------------------------------------------------------------------


def test_unflatten_flat_dict() -> None:
    result = ContentExtractor._unflatten({'name': 'Widget', 'rating': '5'}, frozenset())
    assert result == {'name': 'Widget', 'rating': '5'}


def test_unflatten_nested_prefix() -> None:
    flat = {'name': 'Widget', 'price_amount': '£5', 'price_currency': '£'}
    result = ContentExtractor._unflatten(flat, frozenset({'price'}))
    assert result == {'name': 'Widget', 'price': {'amount': '£5', 'currency': '£'}}


def test_unflatten_disambiguates_literal_underscores() -> None:
    """Fields like is_instock must not be accidentally split."""
    flat = {'is_instock': 'true', 'price_amount': '£5'}
    # only 'price' is a nested prefix — 'is' is not
    result = ContentExtractor._unflatten(flat, frozenset({'price'}))
    assert result == {'is_instock': 'true', 'price': {'amount': '£5'}}


# ---------------------------------------------------------------------------
# extract_content_with_html — unflattened output
# ---------------------------------------------------------------------------


_SIMPLE_HTML = """
<html><body>
  <div class="product-card">
    <h1 class="title">Anvil</h1>
    <span class="price-amount">£25</span>
    <span class="currency">£</span>
  </div>
</body></html>
"""

_SELECTORS: dict[str, dict[str, str]] = {
    'name': {'primary': 'h1.title'},
    'price_amount': {'primary': 'span.price-amount'},
    'price_currency': {'primary': 'span.currency'},
}


def test_extract_content_with_html_nested(extractor: ContentExtractor) -> None:
    result = extractor.extract_content_with_html('http://x.com', _SIMPLE_HTML, _SELECTORS)
    assert result is not None
    assert result['name'] == 'Anvil'
    assert isinstance(result['price'], dict)
    assert result['price']['amount'] == '£25'  # type: ignore[index]
    assert result['price']['currency'] == '£'  # type: ignore[index]


# ---------------------------------------------------------------------------
# extract_items — unflattened output
# ---------------------------------------------------------------------------


_LIST_HTML = """
<html><body>
  <div class="product-card">
    <h1 class="title">Anvil</h1>
    <span class="price-amount">£25</span>
    <span class="currency">£</span>
  </div>
  <div class="product-card">
    <h1 class="title">Hammer</h1>
    <span class="price-amount">£10</span>
    <span class="currency">£</span>
  </div>
</body></html>
"""


def test_extract_items_nested(extractor: ContentExtractor) -> None:
    items = extractor.extract_items('http://x.com', _LIST_HTML, _SELECTORS, '.product-card')
    assert items is not None
    assert len(items) == 2
    for item in items:
        assert isinstance(item.get('price'), dict)
    assert items[0]['name'] == 'Anvil'
    assert items[1]['name'] == 'Hammer'
