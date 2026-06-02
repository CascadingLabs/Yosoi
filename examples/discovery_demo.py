"""Keyless live DISCOVERY via the Claude Agent SDK — no provider API key required.

Yosoi can drive its selector-discovery LLM through subscription-backed agent CLIs (the
Claude Agent SDK / Claude Code, or OpenCode) instead of a per-token API key (CAS-28).
This runs discovery from scratch (``force=True``) — the LLM analyses the live HTML, Yosoi
verifies each selector against the DOM, then extracts and caches the result so future runs
replay deterministically with no LLM (see ``examples/replay_demo.py``).

Auth: uses the ambient Claude Code session — no key in the environment is needed, just a
working ``claude`` CLI / ``claude_agent_sdk`` install.

Run:
    uv run python examples/discovery_demo.py
"""

from __future__ import annotations

import asyncio
import time

import yosoi as ys

_MODEL = ys.claude_sdk('claude-sonnet-4-5')


class CatalogProduct(ys.Contract):
    """A qscrape.dev L1 catalog item (static HTML)."""

    name: str | None = ys.Title(default=None, description='Product name')
    price: str | None = ys.Field(default=None, description='Product price')


class RedditPost(ys.Contract):
    """A reddit post / comment (JS-rendered)."""

    author: str | None = ys.Author(default=None, description='Username of the poster')
    title: str | None = ys.Title(default=None, description='Post title')
    score: str | None = ys.Field(default=None, description='Post or comment score')


class MapsBusiness(ys.Contract):
    """A Google Maps business result (JS-rendered)."""

    business_name: str | None = ys.Title(default=None, description='Business name')
    phone: str | None = ys.Field(default=None, description='Phone number')


# (contract, url, fetcher_type). qscrape L1 is static (fast); reddit/maps need a browser.
_TARGETS = [
    (CatalogProduct, 'https://qscrape.dev/l1/eshop/catalog/?cat=Forge%20%26%20Smithing', 'simple'),
    (RedditPost, 'https://www.reddit.com/r/webscraping/comments/1tqajln/i_need_help/', 'headless'),
    (MapsBusiness, 'https://www.google.com/maps/search/HomeWell+Care+Services+Plano%2C+TX/', 'headless'),
]


async def _discover(contract: type[ys.Contract], url: str, fetcher_type: str) -> None:
    print(f'\n=== DISCOVER {contract.__name__} :: {url[:60]} (tier={fetcher_type}) ===', flush=True)
    t = time.time()
    try:
        items = await ys.scrape(url, contract, model=_MODEL, force=True, fetcher_type=fetcher_type)
    except Exception as e:  # demo: report per-target, don't abort the batch
        print(f'  ✗ after {time.time() - t:.0f}s: {type(e).__name__}: {str(e)[:200]}', flush=True)
        return
    print(f'  ✓ discovered + extracted in {time.time() - t:.0f}s -> {len(items)} record(s)', flush=True)
    for i, item in enumerate(items[:5], 1):
        print(f'  {i:02d}. {item}', flush=True)


async def main() -> None:
    for contract, url, fetcher_type in _TARGETS:
        await _discover(contract, url, fetcher_type)


if __name__ == '__main__':
    asyncio.run(main())
