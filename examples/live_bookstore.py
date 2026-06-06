"""LIVE scrape — discover selectors ONCE, replay across the catalogue. No mocks.

Hits books.toscrape.com for real, extracts structured records with a 4-line contract,
and shows the discover-once-replay-forever cost model live: the first page pays one LLM
discovery; every other page is a pure cached replay with zero LLM calls.

    uv run python examples/live_bookstore.py
"""

from __future__ import annotations

import asyncio
import time

import yosoi as ys


class Book(ys.Contract):
    """A book product page on books.toscrape.com."""

    title: str = ys.Title(description="the book's title")
    price: str = ys.Field(description='the price, e.g. £51.77')
    availability: str = ys.Field(description='the in-stock availability text')


_BASE = 'https://books.toscrape.com/catalogue/'
_BOOKS = [
    'a-light-in-the-attic_1000',
    'tipping-the-velvet_999',
    'soumission_998',
    'sharp-objects_997',
    'sapiens-a-brief-history-of-humankind_996',
    'the-requiem-red_995',
    'the-black-maria_991',
    'starving-hearts-triangular-trade-trilogy-1_990',
    'shakespeares-sonnets_989',
    'set-me-free_988',
    'scott-pilgrims-precious-little-life-scott-pilgrim-1_987',
    'rip-it-up-and-start-again_986',
]
URLS = [f'{_BASE}{slug}/index.html' for slug in _BOOKS]


async def main() -> None:
    model = ys.claude_sdk()
    t = time.time()
    await ys.scrape(URLS[0], Book, model=model)  # cold: one LLM discovery, caches selectors
    cold = time.time() - t

    t = time.time()
    results = await ys.scrape(URLS[1:], Book, model=model)  # warm: pure cached replay, no LLM
    warm, n = time.time() - t, len(URLS) - 1

    print(f'\n  {"TITLE":<46}{"PRICE":>9}  STOCK')
    for url in URLS[1:]:
        b = (results[url] or [{}])[0]
        print(f'  {b.get("title", "?")[:44]:<46}{b.get("price", "?"):>9}  {b.get("availability", "?")}')
    print(f'\n  cold start  (1 page, LLM discovery): {cold:5.1f}s')
    print(f'  warm replay ({n} pages, cached)    : {warm:5.1f}s  →  {warm / n * 1000:.0f} ms/page, ZERO LLM calls')
    print(f'  discover once · replay forever — {n} live pages off a single discovery.')


if __name__ == '__main__':
    asyncio.run(main())
