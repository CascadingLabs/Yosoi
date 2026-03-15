"""Examples of the dynamic Contract system.

Three examples demonstrating different ways to use contracts with the Pipeline:
1. Static subclass with field-right types (books.toscrape.com)
2. ContractBuilder fluent API (quotes.toscrape.com)
"""

import asyncio

from pydantic import field_validator

import yosoi as ys

# auto_config() picks up YOSOI_MODEL, then the first env key it finds.
config = ys.auto_config()


# -- Example 1: Static subclass ----------------------------------------------
class Book(ys.Contract):
    """Scrape book data from books.toscrape.com."""

    title: str = ys.Title()
    price: float = ys.Price(hint='Book price including currency symbol')
    rating: str = ys.Rating(hint="Star rating (e.g. 'Three')")
    footer: str = ys.Field(description='optional footer if the site has one')

    @field_validator('price', mode='after')
    @classmethod
    def price_must_be_positive(cls, v: float) -> float:
        """Ensure price is positive."""
        if v <= 0:
            raise ValueError('price must be positive')
        return v


async def example_1_static_subclass():
    """Static contract subclass with field validators."""
    print('\n=== Example 1: Static Contract Subclass (books.toscrape.com) ===')
    pipeline = ys.Pipeline(llm_config=config, contract=Book)
    await pipeline.process_url('https://books.toscrape.com')


# -- Example 2: ContractBuilder fluent API ------------------------------------
async def example_2_contract_builder():
    """ContractBuilder fluent API for defining contracts at runtime."""
    print('\n=== Example 2: ContractBuilder (quotes.toscrape.com) ===')

    Quote = (
        ys.Contract.define('Quote')
        .text(description='The quote text', type=str)
        .author(description="The author's name", type=str)
        .tags(description='Comma-separated tags', type=str)
        .build()
    )

    pipeline = ys.Pipeline(llm_config=config, contract=Quote)
    await pipeline.process_url('https://quotes.toscrape.com')


if __name__ == '__main__':
    asyncio.run(example_1_static_subclass())
    asyncio.run(example_2_contract_builder())
