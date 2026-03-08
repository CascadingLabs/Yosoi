"""OpenRouter example using stepfun/step-3.5-flash:free.

OpenRouter provides access to hundreds of models (including free tiers) via a
single OpenAI-compatible API.  Get a key at https://openrouter.ai/keys and add
it to your .env as OPENROUTER_KEY.

Two examples:
1. Static Contract subclass (books.toscrape.com)
2. ContractBuilder fluent API (quotes.toscrape.com)
"""

import os

from dotenv import load_dotenv

import yosoi as ys

load_dotenv()
# stepfun/step-3.5-flash:free is a free model available on OpenRouter
config = ys.openrouter('llama-3.3-70b-versatile:free', os.environ['OPENROUTER_KEY'])


# ── Example 1: Static Contract subclass ─────────────────────────────────────
class Book(ys.Contract):
    """Scrape book data from books.toscrape.com."""

    title: ys.Title
    price: ys.Price = ys.Field(hint='Book price — always includes £ symbol')
    rating: ys.Rating = ys.Field(hint="Star rating written as a word e.g. 'Three'")


def example_1_books():
    """Scrape books.toscrape.com using a static Contract and OpenRouter."""
    print('\n=== Example 1: Books (books.toscrape.com) via OpenRouter ===')
    pipeline = ys.Pipeline(llm_config=config, contract=Book)
    pipeline.process_url('https://books.toscrape.com')


# ── Example 2: ContractBuilder fluent API ───────────────────────────────────
def example_2_quotes():
    """Scrape quotes.toscrape.com using ContractBuilder and OpenRouter."""
    print('\n=== Example 2: Quotes (quotes.toscrape.com) via OpenRouter ===')

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
    example_1_books()
    example_2_quotes()
