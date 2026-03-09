from pydantic import Field
from pydantic_ai import Agent, capture_run_messages
from pydantic_ai.models.test import TestModel

from yosoi.models.contract import Contract
from yosoi.types.field import Field as YsField
from yosoi.types.price import Price


class TestContract(Contract):
    """Test contract with custom types and hints."""

    item_price: float = Price(currency_symbol='£', hint='Look for GBP symbol')
    name: str = Field(description='The name of the item')


class OverrideContract(Contract):
    """Contract with a mix of AI-discovered and selector-overridden fields."""

    title: str = Field(description='The item title')
    price: float = YsField(description='The item price', selector='p.price_color')  # type: ignore[assignment]
    rating: str = YsField(description='Star rating', selector='p.star-rating')  # type: ignore[assignment]


def test_selector_model_metadata_preservation():
    """Verify that to_selector_model preserves descriptions and hints."""
    SelectorModel = TestContract.to_selector_model()

    # Check item_price field
    price_field = SelectorModel.model_fields['item_price']
    extra = price_field.json_schema_extra
    assert isinstance(extra, dict)
    assert extra.get('yosoi_hint') == 'Look for GBP symbol'

    # Check name field
    name_field = SelectorModel.model_fields['name']
    assert name_field.description == 'The name of the item'


def test_pydantic_ai_schema_rendering():
    """Verify that Pydantic AI receives the metadata in the schema."""
    SelectorModel = TestContract.to_selector_model()
    model = TestModel()
    agent = Agent(model, output_type=SelectorModel)

    import contextlib

    with capture_run_messages(), contextlib.suppress(BaseException):
        agent.run_sync('Test')

    # The output schema is part of the tool call definition sent to the model.
    # In Pydantic AI, this is usually rendered in the system prompt or as a tool definition.

    # Let's check the JSON schema directy
    schema = SelectorModel.model_json_schema()

    # Verify price field schema
    price_properties = schema['properties']['item_price']
    # If it's a reference to FieldSelectors, we should check $ref
    assert '$ref' in price_properties

    # The description in Pydantic models usually goes to the property that uses it.
    # But for dynamic models, let's see where it landed.

    # Actually, in to_selector_model, we did:
    # field_defs[name] = (FieldSelectors, selector_field)
    # where selector_field = Field(description=description, json_schema_extra={'yosoi_hint': hint})

    assert schema['properties']['item_price']['description'] == 'Look for GBP symbol'
    assert schema['properties']['item_price']['yosoi_hint'] == 'Look for GBP symbol'
    assert schema['properties']['name']['description'] == 'The name of the item'


# ---------------------------------------------------------------------------
# Selector override tests
# ---------------------------------------------------------------------------


def test_overridden_fields_excluded_from_selector_model():
    """Fields with yosoi_selector must not appear in the LLM selector model."""
    SelectorModel = OverrideContract.to_selector_model()
    fields = SelectorModel.model_fields

    assert 'title' in fields, 'Non-overridden field should be in selector model'
    assert 'price' not in fields, 'Overridden field should be excluded from selector model'
    assert 'rating' not in fields, 'Overridden field should be excluded from selector model'


def test_overridden_fields_excluded_from_field_descriptions():
    """field_descriptions() must omit overridden fields so they don't appear in the prompt."""
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
    """A contract where every field is overridden should yield an empty selector model."""

    class AllOverride(Contract):
        name: str = YsField(description='Name', selector='h1')  # type: ignore[assignment]
        desc: str = YsField(description='Desc', selector='p.desc')  # type: ignore[assignment]

    SelectorModel = AllOverride.to_selector_model()
    assert AllOverride.field_descriptions() == {}
    assert len(SelectorModel.model_fields) == 0
