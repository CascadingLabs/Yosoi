"""Scrape the qscrape.dev L1 e-shop catalog.

Run:
    uv run python examples/qscrape.dev/l1/eshop/catalog.py
"""

from __future__ import annotations

import asyncio
import os

import yosoi as ys
from yosoi.core.discovery import LLMConfig

URLS = [
    'https://qscrape.dev/l1/eshop/catalog/?cat=Forge%20%26%20Smithing',
    'https://qscrape.dev/l1/eshop/catalog/?cat=Potions%20%26%20Elixirs',
    'https://qscrape.dev/l1/eshop/catalog/?cat=Arcane%20Tomes',
]


class Product(ys.Contract):
    """A product card in the static qscrape.dev L1 e-shop catalog."""

    name: str = ys.Title(description='Product name')
    category: str = ys.Field(description='Product category label')
    price: float = ys.Price(description='Product price as a number')
    rating: int = ys.Rating(as_float=True, description='Visible star rating as a 1-5 score')
    reviews_count: int | None = ys.Field(description='Number of product reviews')
    availability: str = ys.Field(description='Stock status')


def model_config() -> LLMConfig | str | None:
    """Choose the discovery model without changing the scraper."""
    if model := os.getenv('YOSOI_MODEL'):
        return model

    # Copy-paste provider switch:
    # return ys.claude_sdk('claude-opus-4-7')
    # return ys.opencode('openai/gpt-5-codex')
    # return ys.openrouter('anthropic/claude-3.5-sonnet')
    # return ys.provider('groq:llama-3.3-70b-versatile')
    return None


async def main() -> None:
    result = await ys.scrape(
        URLS,
        Product,
        model=model_config(),
        fetcher_type='simple',
        force=os.getenv('YOSOI_FORCE', '').lower() in {'1', 'true', 'yes'},
        quiet=False,
    )
    ys.show(result)


if __name__ == '__main__':
    asyncio.run(main())
