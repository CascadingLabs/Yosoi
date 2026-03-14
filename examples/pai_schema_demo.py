import json

from pydantic import Field
from pydantic_ai import capture_run_messages
from pydantic_ai.models.test import TestModel

from yosoi.core.discovery.yosoi_agent import YosoiAgent
from yosoi.models.contract import Contract
from yosoi.prompts.discovery import DiscoveryInput
from yosoi.types.price import Price
from yosoi.types.url import Url


# Define a complex contract to show off integration
class ShoppingContract(Contract):
    """A contract for e-commerce scraping."""

    product_name: str = Field(description='The full name of the product')
    price: float = Price(currency_symbol='$', hint='Look for the large price text near the Buy button')
    official_url: str = Url(require_https=True, hint="The link to the manufacturer's website")


def main():
    print('--- Pydantic AI Prompt Rendering Demo ---')

    # 1. Setup the Agent — output type is derived from the contract automatically
    model = TestModel()
    system_prompt = 'You are a web scraping expert. Find CSS selectors for the requested fields.'
    agent = YosoiAgent(model, contract=ShoppingContract, system_prompt=system_prompt)

    # 2. Build a typed DiscoveryInput and capture the run
    discovery_input = DiscoveryInput(
        url='https://example.com/product',
        html="<div class='product'><h1 id='name'>Coffee Maker</h1><span class='price'>$49.99</span></div>",
    )

    import contextlib

    with capture_run_messages() as messages, contextlib.suppress(Exception):
        agent.run_sync(discovery_input)

    # 3. Display the rendered messages
    for i, msg in enumerate(messages):
        print(f'\n[Message {i} - {type(msg).__name__}]')
        for part in msg.parts:
            if hasattr(part, 'content'):
                print(f'Content:\n{part.content}')

    # 4. Display the JSON Schema that Pydantic AI sends to the model
    print('\n--- Model Output Schema ---')
    schema = ShoppingContract.to_selector_model().model_json_schema()
    print(json.dumps(schema, indent=2))


if __name__ == '__main__':
    main()
