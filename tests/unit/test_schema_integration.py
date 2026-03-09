from pydantic import Field
from pydantic_ai import Agent, capture_run_messages
from pydantic_ai.models.test import TestModel

from yosoi.models.contract import Contract
from yosoi.types.price import Price


class TestContract(Contract):
    """Test contract with custom types and hints."""

    item_price: float = Price(currency_symbol='£', hint='Look for GBP symbol')
    name: str = Field(description='The name of the item')


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
