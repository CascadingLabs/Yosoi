import json

from pydantic import Field
from pydantic_ai import Agent, capture_run_messages
from pydantic_ai.models.test import TestModel

from yosoi.models.contract import Contract
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

    # 1. Setup the Selector Model (this is what the agent returns)
    SelectorModel = ShoppingContract.to_selector_model()

    # 2. Setup the Agent with a TestModel
    # We don't need a real LLM for this; TestModel just echoes back what we give it
    model = TestModel()

    system_prompt = 'You are a web scraping expert. Find CSS selectors for the requested fields.'
    agent = Agent(model, output_type=SelectorModel, system_prompt=system_prompt)

    user_prompt = (
        "Analyze this HTML: <div class='product'><h1 id='name'>Coffee Maker</h1><span class='price'>$49.99</span></div>"
    )

    # 3. Capture the run
    import contextlib

    with capture_run_messages() as messages, contextlib.suppress(Exception):
        agent.run_sync(user_prompt)

    # 4. Display the rendered messages
    for i, msg in enumerate(messages):
        print(f'\n[Message {i} - {type(msg).__name__}]')
        for part in msg.parts:
            if hasattr(part, 'content'):
                print(f'Content:\n{part.content}')

    # 5. Display the JSON Schema that Pydantic AI sends to the model
    # (This is how the model knows what structure to return)
    print('\n--- Model Output Schema ---')
    schema = SelectorModel.model_json_schema()
    print(json.dumps(schema, indent=2))


if __name__ == '__main__':
    main()
