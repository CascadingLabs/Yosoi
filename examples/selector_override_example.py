"""Selector override example using books.toscrape.com.

Demonstrates the ``selector`` parameter on ``ys.Field`` / type helpers, which
lets you hard-code a CSS selector for a field and skip AI discovery entirely.

Use cases:
- Migrating from a legacy scraper with known-good selectors
- Finicky sites where the LLM struggles to find the right element
- Mixed contracts: some fields pinned, others still AI-discovered

Four examples:
1. All fields pinned  → AI is skipped completely
2. Mixed contract     → AI discovers unknown fields, overrides are merged in
3. Single-page URL   → demonstrates a pinned selector on a book detail page
4. YosoiConfig.force → force re-discovery via config instead of per-call flag
"""

import asyncio

import yosoi as ys

config = ys.auto_config()


# -- Example 1: All fields pinned — no AI call at all -------------------------
class BookFullOverride(ys.Contract):
    """Every selector is hard-coded; AI discovery is skipped entirely."""

    title: str = ys.Title(selector='article.product_pod h3 a')
    price: float = ys.Price(selector='article.product_pod p.price_color')
    rating: str = ys.Rating(selector='article.product_pod p.star-rating')


async def example_1_full_override():
    """All selectors pinned — zero LLM calls."""
    print('\n=== Example 1: Full override (no AI) ===')
    pipeline = ys.Pipeline(llm_config=config, contract=BookFullOverride)
    await pipeline.process_url('https://books.toscrape.com')


# -- Example 2: Mixed — some pinned, some AI-discovered -----------------------
class BookMixed(ys.Contract):
    """Price selector is pinned; title and rating are discovered by AI."""

    title: str = ys.Title()
    price: float = ys.Price(
        hint='Book price — always includes £ symbol',
        selector='article.product_pod p.price_color',  # we know this one
    )
    rating: str = ys.Rating(hint="Star rating written as a word e.g. 'Three'")


async def example_2_mixed():
    """Price is pinned; title and rating go through normal AI discovery."""
    print('\n=== Example 2: Mixed contract (price pinned, rest AI) ===')
    pipeline = ys.Pipeline(llm_config=config, contract=BookMixed)
    await pipeline.process_url('https://books.toscrape.com')


# -- Example 3: Detail page with a pinned availability selector ---------------
class BookDetail(ys.Contract):
    """Scrape a single book's detail page."""

    title: str = ys.Title()
    price: float = ys.Price(hint='Includes £ symbol')
    availability: str = ys.Field(
        description='Stock availability status',
        selector='table.table-striped tr:nth-child(6) td',  # known table row
    )


async def example_3_detail_page():
    """Detail page: availability selector is pinned, others AI-discovered."""
    print('\n=== Example 3: Detail page (availability pinned) ===')
    pipeline = ys.Pipeline(llm_config=config, contract=BookDetail)
    await pipeline.process_url('https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html')


# -- Example 4: Force re-discovery via YosoiConfig ---------------------------
async def example_4_force_via_config():
    """Force re-discovery using YosoiConfig.force instead of a per-call flag.

    Useful when you want every run in a script to bypass the selector cache
    without having to pass force=True to every process_url call.
    """
    print('\n=== Example 4: Force re-discovery via YosoiConfig ===')
    forced_config = ys.auto_config()
    forced_config = ys.YosoiConfig(llm=forced_config.llm, force=True)
    pipeline = ys.Pipeline(forced_config, contract=BookMixed)
    await pipeline.process_url('https://books.toscrape.com')


if __name__ == '__main__':
    asyncio.run(example_1_full_override())
    asyncio.run(example_2_mixed())
    asyncio.run(example_3_detail_page())
    asyncio.run(example_4_force_via_config())
