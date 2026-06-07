"""Explore the high-level fingerprint API.

Run:
    uv run python examples/api_design/fingerprint.py
"""

from __future__ import annotations

import asyncio

import yosoi as ys
from yosoi.core.fetcher.simple import SimpleFetcher

URLS = [
    'https://qscrape.dev/l1/eshop/catalog/?cat=Forge%20%26%20Smithing',
    'https://qscrape.dev/l1/eshop/catalog/?cat=Potions%20%26%20Elixirs',
]


async def main() -> None:
    async with SimpleFetcher(min_delay=0, max_delay=0, randomize_headers=False) as fetcher:
        first, second = await asyncio.gather(*(fetcher.fetch(url) for url in URLS))

    fingerprint = ys.fingerprint(first)

    ys.show(fingerprint, title='Single page fingerprint')
    ys.show(first, fingerprint=second, title='Catalog shape comparison')


if __name__ == '__main__':
    asyncio.run(main())
