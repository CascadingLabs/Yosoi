"""Scrape the qscrape.dev L1 e-shop catalog.

Run:
    uv run python examples/qscrape.dev/l1/eshop/catalog.py
"""

from __future__ import annotations

import asyncio

import yosoi as ys

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


async def main() -> None:
    policy = ys.Policy.cascade(
        ys.Policy.from_env(),
        ys.Policy(
            scrape=ys.ScrapePolicy(fetcher_type='simple'),
            output=ys.OutputPolicy(quiet=False),
        ),
    )
    result = await ys.scrape(
        URLS,
        Product,
        policy=policy,
    )
    ys.show(result)


if __name__ == '__main__':
    asyncio.run(main())
