"""Scrape the qscrape.dev L2 JavaScript-rendered e-shop catalog.

Run:
    uv run python examples/qscrape.dev/l2/eshop/catalog.py
"""

from __future__ import annotations

import asyncio
import os

import yosoi as ys

URL = 'https://qscrape.dev/l2/eshop/'


class Product(ys.Contract):
    """A product card in the JS-rendered qscrape.dev L2 e-shop catalog."""

    name: str = ys.Title(description='Product name')
    category: str | None = ys.Field(description='Product category label')
    price: float = ys.Price(description='Product price as a number')


async def main() -> None:
    items = await ys.scrape(
        URL,
        Product,
        model=os.getenv('YOSOI_MODEL') or None,
        selector_level=ys.SelectorLevel.XPATH,
        force=os.getenv('YOSOI_FORCE', '').lower() in {'1', 'true', 'yes'},
        quiet=False,
    )
    ys.show(items)


if __name__ == '__main__':
    asyncio.run(main())
