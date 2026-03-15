"""Tests for nested Contract composition (flat discovery, reassembly before Pydantic)."""

import pytest

import yosoi as ys
from yosoi.models.selectors import is_discover_sentinel

# ---------------------------------------------------------------------------
# Shared fixtures (module-level classes so __init_subclass__ fires once)
# ---------------------------------------------------------------------------


class _Price(ys.Contract):
    amount: float = ys.Price()
    currency: str = ys.Field(description='Currency symbol')


class _PricePinned(ys.Contract):
    root = ys.css('.price-block')
    amount: float = ys.Price()
    currency: str = ys.Field(description='Currency symbol')


class _PriceAutoRoot(ys.Contract):
    root = ys.discover()
    amount: float = ys.Price()
    currency: str = ys.Field(description='Currency symbol')


class _Product(ys.Contract):
    root = ys.css('.product-card')
    name: str = ys.Title()
    price: _Price = ys.Field(description='Product price info')  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# nested_contracts()
# ---------------------------------------------------------------------------


def test_nested_contracts_detects_contract_typed_fields():
    nested = _Product.nested_contracts()
    assert 'price' in nested
    assert nested['price'] is _Price


def test_nested_contracts_empty_for_flat():
    assert _Price.nested_contracts() == {}


# ---------------------------------------------------------------------------
# field_descriptions()
# ---------------------------------------------------------------------------


def test_field_descriptions_expands_nested_flat():
    descs = _Product.field_descriptions()
    assert 'name' in descs
    assert 'price_amount' in descs
    assert 'price_currency' in descs
    assert 'price' not in descs  # parent field itself must not appear


def test_field_descriptions_pinned_root_adds_within_hint():
    class _ProductPinned(ys.Contract):
        name: str = ys.Title()
        price: _PricePinned = ys.Field()  # type: ignore[assignment]

    descs = _ProductPinned.field_descriptions()
    assert '(within: .price-block)' in descs['price_amount']
    assert '(within: .price-block)' in descs['price_currency']


def test_field_descriptions_discover_root_adds_scoped_hint():
    class _ProductAuto(ys.Contract):
        name: str = ys.Title()
        price: _PriceAutoRoot = ys.Field()  # type: ignore[assignment]

    descs = _ProductAuto.field_descriptions()
    assert '(co-located with other price fields)' in descs['price_amount']
    assert '(co-located with other price fields)' in descs['price_currency']


def test_field_descriptions_skips_child_overrides():
    from yosoi.types.field import Field as YsField

    class _PriceOverride(ys.Contract):
        amount: float = ys.Price()
        currency: str = YsField(description='Currency', selector='span.currency')  # type: ignore[assignment]

    class _ProductOverride(ys.Contract):
        name: str = ys.Title()
        price: _PriceOverride = ys.Field()  # type: ignore[assignment]

    descs = _ProductOverride.field_descriptions()
    assert 'price_amount' in descs
    assert 'price_currency' not in descs  # excluded because it has a selector override


# ---------------------------------------------------------------------------
# field_hints()
# ---------------------------------------------------------------------------


def test_field_hints_expands_nested():
    hints = _Product.field_hints()
    assert 'price_amount' in hints
    assert 'price_currency' in hints
    assert 'price' not in hints


# ---------------------------------------------------------------------------
# to_selector_model()
# ---------------------------------------------------------------------------


def test_to_selector_model_nested_flat():
    SelectorModel = _Product.to_selector_model()
    fields = SelectorModel.model_fields
    assert 'price_amount' in fields
    assert 'price_currency' in fields


def test_to_selector_model_nested_skips_top_level_parent_name():
    SelectorModel = _Product.to_selector_model()
    assert 'price' not in SelectorModel.model_fields


# ---------------------------------------------------------------------------
# get_selector_overrides()
# ---------------------------------------------------------------------------


def test_get_selector_overrides_includes_child_overrides_as_flat_keys():
    from yosoi.types.field import Field as YsField

    class _PriceOverride2(ys.Contract):
        amount: float = ys.Price()
        currency: str = YsField(description='Currency', selector='span.currency')  # type: ignore[assignment]

    class _ProductOverride2(ys.Contract):
        name: str = ys.Title()
        price: _PriceOverride2 = ys.Field()  # type: ignore[assignment]

    overrides = _ProductOverride2.get_selector_overrides()
    assert 'price_currency' in overrides
    assert overrides['price_currency'] == {'primary': 'span.currency'}


# ---------------------------------------------------------------------------
# Name collision check
# ---------------------------------------------------------------------------


def test_name_collision_raises_at_class_definition():
    with pytest.raises(TypeError, match='collides with nested expansion'):

        class _Bad(ys.Contract):
            price_amount: str = ys.Field()  # type: ignore[assignment]
            price: _Price = ys.Field()  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Pydantic validation
# ---------------------------------------------------------------------------


def test_nested_contract_pydantic_validation():
    result = _Product.model_validate({'name': 'Widget', 'price': {'amount': 5.0, 'currency': '£'}})
    assert result.name == 'Widget'
    assert result.price.currency == '£'  # type: ignore[attr-defined]


def test_nested_contract_standalone_still_works():
    result = _Price.model_validate({'amount': 5.0, 'currency': '£'})
    assert result.amount == 5.0
    assert result.currency == '£'


# ---------------------------------------------------------------------------
# discover sentinel
# ---------------------------------------------------------------------------


def test_discover_sentinel_detection():
    assert is_discover_sentinel(ys.discover()) is True
    assert is_discover_sentinel(ys.css('.foo')) is False
    assert is_discover_sentinel(None) is False
