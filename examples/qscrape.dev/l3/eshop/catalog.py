"""Scrape the qscrape.dev L3 island-rendered e-shop catalog.

Run:
    uv run python examples/qscrape.dev/l3/eshop/catalog.py
"""

from __future__ import annotations

import asyncio

import yosoi as ys

URL = 'https://qscrape.dev/l3/eshop/'


class Product(ys.Contract):
    """A product assembled across qscrape.dev L3 framework islands."""

    name: str = ys.Title(description='Product name')
    category: str | None = ys.Field(description='Product category label')
    price: float = ys.Price(description='Product price as a number')


async def main() -> None:
    policy = ys.Policy.cascade(
        ys.Policy.from_env(),
        ys.Policy(
            scrape=ys.ScrapePolicy(selector_level=ys.SelectorLevel.XPATH),
            output=ys.OutputPolicy(quiet=False),
        ),
    )
    items = await ys.scrape(
        URL,
        Product,
        policy=policy,
    )
    ys.show(items)


if __name__ == '__main__':
    asyncio.run(main())
