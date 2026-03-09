"""Tests for Contract schema generation, selector overrides, and validators."""

import pytest
from pydantic import Field
from pydantic_ai import Agent, capture_run_messages
from pydantic_ai.models.test import TestModel

import yosoi as ys
from yosoi.models.contract import Contract
from yosoi.types.field import Field as YsField
from yosoi.types.price import Price


class SampleContract(Contract):
    """Sample contract with custom types and hints."""

    item_price: float = Price(currency_symbol='£', hint='Look for GBP symbol')
    name: str = Field(description='The name of the item')


class OverrideContract(Contract):
    """Contract with a mix of AI-discovered and selector-overridden fields."""

    title: str = Field(description='The item title')
    price: float = YsField(description='The item price', selector='p.price_color')  # type: ignore[assignment]
    rating: str = YsField(description='Star rating', selector='p.star-rating')  # type: ignore[assignment]


class BookContract(Contract):
    title: str = ys.Title()
    price: float = ys.Price()
    author: str = ys.Author()


# ---------------------------------------------------------------------------
# Selector model metadata
# ---------------------------------------------------------------------------


def test_selector_model_metadata_preservation():
    """Verify that to_selector_model preserves descriptions and hints."""
    SelectorModel = SampleContract.to_selector_model()

    price_field = SelectorModel.model_fields['item_price']
    extra = price_field.json_schema_extra
    assert isinstance(extra, dict)
    assert extra.get('yosoi_hint') == 'Look for GBP symbol'

    name_field = SelectorModel.model_fields['name']
    assert name_field.description == 'The name of the item'


def test_pydantic_ai_schema_rendering():
    """Verify that Pydantic AI receives the metadata in the schema."""
    SelectorModel = SampleContract.to_selector_model()
    model = TestModel()
    agent = Agent(model, output_type=SelectorModel)

    import contextlib

    with capture_run_messages(), contextlib.suppress(BaseException):
        agent.run_sync('Test')

    schema = SelectorModel.model_json_schema()

    price_properties = schema['properties']['item_price']
    assert '$ref' in price_properties

    # yosoi_hint carries the hint; description is the default from the type
    assert schema['properties']['item_price']['yosoi_hint'] == 'Look for GBP symbol'
    assert schema['properties']['name']['description'] == 'The name of the item'


# ---------------------------------------------------------------------------
# Selector overrides
# ---------------------------------------------------------------------------


def test_overridden_fields_excluded_from_selector_model():
    """Fields with yosoi_selector must not appear in the LLM selector model."""
    SelectorModel = OverrideContract.to_selector_model()
    fields = SelectorModel.model_fields

    assert 'title' in fields
    assert 'price' not in fields
    assert 'rating' not in fields


def test_overridden_fields_excluded_from_field_descriptions():
    """field_descriptions() must omit overridden fields."""
    descriptions = OverrideContract.field_descriptions()

    assert 'title' in descriptions
    assert 'price' not in descriptions
    assert 'rating' not in descriptions


def test_get_selector_overrides_returns_correct_mapping():
    """get_selector_overrides() should return only fields with yosoi_selector set."""
    overrides = OverrideContract.get_selector_overrides()

    assert overrides == {
        'price': {'primary': 'p.price_color'},
        'rating': {'primary': 'p.star-rating'},
    }
    assert 'title' not in overrides


def test_fully_overridden_contract_produces_empty_selector_model():
    """A contract where every field is overridden yields an empty selector model."""

    class AllOverride(Contract):
        name: str = YsField(description='Name', selector='h1')  # type: ignore[assignment]
        desc: str = YsField(description='Desc', selector='p.desc')  # type: ignore[assignment]

    SelectorModel = AllOverride.to_selector_model()
    assert AllOverride.field_descriptions() == {}
    assert len(SelectorModel.model_fields) == 0


# ---------------------------------------------------------------------------
# Validators inner class
# ---------------------------------------------------------------------------


def test_validators_inner_class_transforms():
    class ProductContract(Contract):
        name: str
        category: str

        class Validators:
            @staticmethod
            def name(v: str) -> str:
                return v.title()

            @staticmethod
            def category(v: str) -> str:
                return v.upper()

    result = ProductContract.model_validate({'name': 'laptop stand', 'category': 'accessories'})
    assert result.name == 'Laptop Stand'
    assert result.category == 'ACCESSORIES'


def test_validators_inner_class_value_error_propagates():
    from pydantic import ValidationError

    class StrictContract(Contract):
        price: str

        class Validators:
            @staticmethod
            def price(v: str) -> str:
                if not v.startswith('$'):
                    raise ValueError('price must start with $')
                return v

    with pytest.raises(ValidationError):
        StrictContract.model_validate({'price': '12.99'})


def test_validators_only_applies_defined_fields():
    """Fields without a Validators method are passed through unchanged."""

    class PartialContract(Contract):
        name: str
        description: str

        class Validators:
            @staticmethod
            def name(v: str) -> str:
                return v.upper()

    result = PartialContract.model_validate({'name': 'item', 'description': '  some desc  '})
    assert result.name == 'ITEM'
    assert result.description == '  some desc  '


def test_validators_and_type_coercion_combined():
    """Validators inner class runs before Price coercion."""

    class ShopContract(Contract):
        price: float = ys.Price()

        class Validators:
            @staticmethod
            def price(v: str) -> str:
                return v.removeprefix('PRICE:').strip()

    result = ShopContract.model_validate({'price': 'PRICE: £19.99'})
    assert result.price == 19.99


# ---------------------------------------------------------------------------
# generate_manifest
# ---------------------------------------------------------------------------


def test_contract_generate_manifest():
    manifest = BookContract.generate_manifest()
    assert '# BookContract' in manifest
    assert '| `price`' in manifest
    assert '`price`' in manifest
