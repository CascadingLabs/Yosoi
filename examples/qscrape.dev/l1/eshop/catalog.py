"""Scrape the qscrape.dev L1 e-shop catalog.

Run:
    uv run python examples/qscrape.dev/l1/eshop/catalog.py
"""

from __future__ import annotations

import asyncio
import json
import os

import yosoi as ys

URLS = [
    'https://qscrape.dev/l1/eshop/catalog/?cat=Forge%20%26%20Smithing',
    'https://qscrape.dev/l1/eshop/catalog/?cat=Potions%20%26%20Elixirs',
    'https://qscrape.dev/l1/eshop/catalog/?cat=Arcane%20Tomes',
]


class Product(ys.Contract):
    """A product card in the static qscrape.dev L1 e-shop catalog."""

    root = ys.css('.product-card')

    name: str = ys.Title(description='Product name')
    category: str = ys.Field(description='Product category label')
    price: float = ys.Price(description='Product price as a number')
    rating: str = ys.Rating(description='Visible star rating')
    reviews_count: int | None = ys.Field(default=None, description='Number of product reviews')
    availability: str = ys.Field(description='Stock status')


async def main() -> None:
    result = await ys.scrape(
        URLS,
        Product,
        model=os.getenv('YOSOI_MODEL') or None,
        fetcher_type='simple',
        force=os.getenv('YOSOI_FORCE', '').lower() in {'1', 'true', 'yes'},
        quiet=False,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
