"""Examples of the dynamic Contract system.

Three examples demonstrating different ways to use contracts with the Pipeline:
1. Static subclass with field validator (books.toscrape.com)
2. ContractBuilder fluent API (quotes.toscrape.com)
3. Default NewsArticle contract (vlr.gg)
"""

import os
from typing import Annotated

from dotenv import load_dotenv
from pydantic import Field, field_validator

import yosoi as ys

# Load environment variables
load_dotenv()

# Configure your LLM (edit as needed)
config = ys.LLMConfig(
    provider='groq',
    model_name='llama-3.3-70b-versatile',
    api_key=os.environ.get('GROQ_KEY', ''),
)


# ── Example 1: Static subclass ──────────────────────────────────────────────
class Book(ys.Contract):
    """Scrape book data from books.toscrape.com."""

    title: Annotated[str, Field(description='Book title')]
    price: Annotated[str, Field(description='Book price including currency symbol')]
    rating: Annotated[str, Field(description="Star rating (e.g. 'Three')")]
    footer: Annotated[str, Field(description='optional footer if the site has one')]

    @field_validator('price', mode='after')
    @classmethod
    def price_must_have_symbol(cls, v: str) -> str:
        """Ensure price contains a currency symbol."""
        if '£' not in v and '$' not in v:
            raise ValueError('price must include currency symbol')
        return v


def example_1_static_subclass():
    """Static contract subclass with field validators."""
    print('\n=== Example 1: Static Contract Subclass (books.toscrape.com) ===')
    pipeline = ys.Pipeline(llm_config=config, contract=Book)
    pipeline.process_url('https://books.toscrape.com')


# ── Example 2: ContractBuilder fluent API ───────────────────────────────────
def example_2_contract_builder():
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
    pipeline.process_url('https://quotes.toscrape.com')


if __name__ == '__main__':
    example_1_static_subclass()
    example_2_contract_builder()
