"""Deterministic, no-LLM REPLAY against cached selectors — Google Maps, reddit, qscrape.

Yosoi's "discover once, scrape forever" promise: once selectors + a DOM-stability recipe
(A3Node) are cached for a domain, a repeat visit replays them with **no LLM in the loop**.
This example proves that — it never constructs a live model call; it fetches each live page
and extracts with the per-domain cached selectors in ``.yosoi/selectors/``.

Prerequisite: the three domains must already have cached selectors (run discovery once, or
use a checked-out ``.yosoi/`` cache). Discovery itself (the LLM step) is a separate path —
see ``examples/reddit_comments_contract.py`` — and needs a provider API key.

Run:
    uv run python examples/replay_demo.py
"""

from __future__ import annotations

import asyncio

import yosoi as ys

# A model is constructed but NEVER called on a cache hit (force=False + skip_verification).
# Any constructible spec works; no API key is needed because no request is made.
_REPLAY_MODEL = 'groq:llama-3.3-70b-versatile'


class Product(ys.Contract):
    """qscrape.dev L2 e-shop item (React-rendered)."""

    name: str | None = ys.Title(default=None, description='Product name')
    price: str | None = ys.Field(default=None, description='Product price')


class MapsBusiness(ys.Contract):
    """A Google Maps business result."""

    business_name: str | None = ys.Title(default=None, description='Business name')
    rating: str | None = ys.Field(default=None, description='Average review rating')
    phone: str | None = ys.Field(default=None, description='Phone number')


class RedditPost(ys.Contract):
    """Thread-level metadata from a reddit post."""

    post_id: str | None = ys.Field(default=None, description='Stable post id')
    subreddit: str | None = ys.Field(default=None, description='Subreddit name')
    author: str | None = ys.Author(default=None, description='Original poster username')
    title: str | None = ys.Title(default=None, description='Post title')
    score: int | None = ys.Field(default=None, description='Post score')


# (contract, url, fetcher_type) — urls/tiers mirror the cached snapshots.
_TARGETS = [
    (Product, 'http://qscrape.dev/l2/eshop/', 'headless'),
    (RedditPost, 'https://www.reddit.com/r/webscraping/comments/1tqajln/i_need_help/', 'headless'),
    (
        MapsBusiness,
        'https://www.google.com/maps/search/HomeWell+Care+Services+Plano%2C+TX/',
        'headless',
    ),
]


async def _replay(contract: type[ys.Contract], url: str, fetcher_type: str) -> None:
    print(f'\n=== REPLAY {contract.__name__} :: {url[:70]} (tier={fetcher_type}) ===')
    try:
        items = await ys.scrape(
            url,
            contract,
            model=_REPLAY_MODEL,
            force=False,  # use cached selectors — no discovery
            skip_verification=True,  # deterministic extract only — no LLM re-verify
            fetcher_type=fetcher_type,
        )
    except Exception as e:  # demo: report per-target, don't abort the batch
        print(f'  ✗ {type(e).__name__}: {str(e)[:200]}')
        return
    print(f'  ✓ {len(items)} record(s)')
    for i, item in enumerate(items[:3], 1):
        print(f'  {i:02d}. {item}')


async def main() -> None:
    for contract, url, fetcher_type in _TARGETS:
        await _replay(contract, url, fetcher_type)


if __name__ == '__main__':
    asyncio.run(main())
