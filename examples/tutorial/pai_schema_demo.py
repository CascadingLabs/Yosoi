"""Demo: Pydantic AI prompt rendering and schema generation.

Shows how Yosoi's discovery agent constructs prompts and what JSON
schema is sent to the LLM for structured output.  Uses TestModel so
no API key or network access is needed.
"""

import json

from pydantic import Field
from pydantic_ai import Agent, capture_run_messages
from pydantic_ai.models.test import TestModel

from yosoi.models.contract import Contract
from yosoi.models.selectors import FieldSelectors, SelectorLevel
from yosoi.prompts.discovery import (
    DiscoveryInput,
    FieldDiscoveryDeps,
    build_user_prompt,
    field_single_base_instructions,
    field_single_field_instructions,
    field_single_level_instructions,
    field_single_page_hints,
)
from yosoi.types.price import Price
from yosoi.types.url import Url


# Define a contract to show off the schema integration
class ShoppingContract(Contract):
    """A contract for e-commerce scraping."""

    product_name: str = Field(description='The full name of the product')
    price: float = Price(currency_symbol='$', description='Look for the large price text near the Buy button')
    official_url: str = Url(require_https=True, description="The link to the manufacturer's website")


async def main() -> None:
    print('--- Pydantic AI Prompt Rendering Demo ---')

    # 1. Build a FieldDiscoveryAgent-style Agent with TestModel
    model = TestModel()
    agent: Agent[FieldDiscoveryDeps, FieldSelectors] = Agent(
        model,
        deps_type=FieldDiscoveryDeps,
        output_type=FieldSelectors,
    )
    agent.system_prompt(field_single_base_instructions)
    agent.system_prompt(field_single_field_instructions)
    agent.system_prompt(field_single_level_instructions)
    agent.system_prompt(field_single_page_hints)

    # 2. Build typed inputs and capture the run
    discovery_input = DiscoveryInput(
        url='https://example.com/product',
        html="<div class='product'><h1 id='name'>Coffee Maker</h1><span class='price'>$49.99</span></div>",
    )
    deps = FieldDiscoveryDeps(
        field_name='price',
        field_description='The product price',
        input=discovery_input,
        target_level=SelectorLevel.CSS,
    )

    import contextlib

    with capture_run_messages() as messages, contextlib.suppress(Exception):
        await agent.run(build_user_prompt(discovery_input), deps=deps)

    # 3. Display the rendered messages
    for i, msg in enumerate(messages):
        print(f'\n[Message {i} - {type(msg).__name__}]')
        for part in msg.parts:
            if hasattr(part, 'content'):
                print(f'Content:\n{part.content}')

    # 4. Display the JSON Schema that Pydantic AI sends to the model
    print('\n--- Contract Selector Model Schema ---')
    schema = ShoppingContract.to_selector_model().model_json_schema()
    print(json.dumps(schema, indent=2))


if __name__ == '__main__':
    import asyncio

    asyncio.run(main())
