"""Scrape the qscrape.dev L3 island-rendered e-shop catalog.

Run:
    uv run python examples/qscrape.dev/l3/eshop/catalog.py
"""

from __future__ import annotations

import asyncio
import json
import os

import yosoi as ys

URL = 'https://qscrape.dev/l3/eshop/'


class Product(ys.Contract):
    """A product assembled across qscrape.dev L3 framework islands."""

    name: str = ys.Title(description='Product name')
    category: str | None = ys.Field(default=None, description='Product category label')
    price: float = ys.Price(description='Product price as a number')
    availability: str | None = ys.Field(default=None, description='Stock status')


async def main() -> None:
    items = await ys.scrape(
        URL,
        Product,
        model=os.getenv('YOSOI_MODEL') or None,
        fetcher_type='waterfall',
        selector_level=ys.SelectorLevel.XPATH,
        force=os.getenv('YOSOI_FORCE', '').lower() in {'1', 'true', 'yes'},
        quiet=False,
    )
    print(json.dumps(items, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
