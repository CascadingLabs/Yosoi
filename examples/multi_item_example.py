"""Multi-item extraction example.

Demonstrates extracting multiple items from catalog/listing pages where
selectors like ``.product-card h3`` match N items instead of just one.

Three modes for container detection:

1. **Auto-discovery** — The AI discovers `yosoi_container` automatically by
   analysing the page structure. Zero user config needed.

2. **Contract override** — Pin the container selector via ``model_config``
   when you know the wrapper element in advance (or the AI guesses wrong).
   Same ``json_schema_extra`` pattern used by ``yosoi_selector``, ``yosoi_hint``, etc.

3. **Single-item fallback** — When there is no container (detail pages),
   ``scrape()`` yields exactly one item and ``process_url()`` behaves
   identically to before.

Two API entry points:

- ``pipeline.scrape(url)`` — async generator, yields one ``ContentMap`` per item.
  This is the canonical entry point.
- ``pipeline.process_url(url)`` — thin wrapper that drains ``scrape()`` and
  returns a boolean success/failure flag.
"""

import asyncio
import os

from dotenv import load_dotenv
from pydantic import ConfigDict

import yosoi as ys

load_dotenv()


# ============================================================================
# Option 1: AI auto-discovers container (zero config)
# ============================================================================


class Product(ys.Contract):
    """The AI sees repeating `.product-card` elements and returns yosoi_container."""

    name: str = ys.Title()
    price: float = ys.Price()
    rating: str = ys.Rating()


async def example_1_auto_discovery():
    """AI auto-discovers the container selector from the page structure."""
    print('\n=== Example 1: Auto-discovered container ===')

    pipeline = ys.Pipeline(
        os.environ.get('YOSOI_MODEL', 'openai:gpt-4o'),
        contract=Product,
        output_format='json',  # saved JSON will use {"items": [...]} shape
    )

    # scrape yields one ContentMap per product found on the page
    async for item in pipeline.scrape('https://books.toscrape.com'):
        print(f'  {item.get("name", "?"):40s}  {item.get("price", "?")}')


# ============================================================================
# Option 2: User pins the container via model_config
# ============================================================================


class ProductPinned(ys.Contract):
    """Container is hard-coded — AI's yosoi_container is ignored."""

    model_config = ConfigDict(json_schema_extra={'yosoi_container': 'article.product_pod'})

    name: str = ys.Title()
    price: float = ys.Price(hint='Includes £ symbol')


async def example_2_pinned_container():
    """Use a contract-level override for the container selector."""
    print('\n=== Example 2: Pinned container via model_config ===')

    pipeline = ys.Pipeline(
        os.environ.get('YOSOI_MODEL', 'openai:gpt-4o'),
        contract=ProductPinned,
    )

    count = 0
    async for item in pipeline.scrape('https://books.toscrape.com'):
        count += 1
        print(f'  #{count}: {item.get("name")}')
    print(f'  → Total items: {count}')


# ============================================================================
# Option 3: Single-item page — no container, yields one item
# ============================================================================


class BookDetail(ys.Contract):
    """Detail page for a single book — no container needed."""

    title: str = ys.Title()
    price: float = ys.Price(hint='Includes £ symbol')
    availability: str = ys.Field(description='Stock availability status')


async def example_3_single_item():
    """scrape on a single-item page yields exactly one item."""
    print('\n=== Example 3: Single-item page (no container) ===')

    pipeline = ys.Pipeline(
        os.environ.get('YOSOI_MODEL', 'openai:gpt-4o'),
        contract=BookDetail,
    )

    async for item in pipeline.scrape('https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html'):
        print(f'  Title: {item.get("title")}')
        print(f'  Price: {item.get("price")}')
        print(f'  Availability: {item.get("availability")}')


# ============================================================================
# Option 4: process_url (existing API) — also detects containers now
# ============================================================================


async def example_4_process_url():
    """process_url() returns bool, but multi-item pages now save items format.

    The saved JSON on disk will contain:
    {
      "items": [...],
      "item_count": N,
      ...
    }
    """
    print('\n=== Example 4: process_url with auto container ===')

    pipeline = ys.Pipeline(
        os.environ.get('YOSOI_MODEL', 'openai:gpt-4o'),
        contract=Product,
        output_format=['json', 'markdown'],  # save both formats
    )

    success = await pipeline.process_url('https://books.toscrape.com')
    print(f'  Success: {success}')


# ============================================================================
# Option 5: Multiple output formats for multi-item data
# ============================================================================


async def example_5_multi_format():
    """Multi-item data works with all output formats.

    - json:     {"items": [...], "item_count": N}
    - markdown: numbered sections separated by ---
    - jsonl:    one row per item (appended)
    - csv:      one row per item (appended)
    """
    print('\n=== Example 5: Multiple output formats ===')

    pipeline = ys.Pipeline(
        os.environ.get('YOSOI_MODEL', 'openai:gpt-4o'),
        contract=ProductPinned,
        output_format=['json', 'jsonl', 'csv', 'markdown'],
    )

    success = await pipeline.process_url('https://books.toscrape.com')
    print(f'  Saved in 4 formats: {success}')


if __name__ == '__main__':
    # Run whichever example you like:
    asyncio.run(example_1_auto_discovery())
    asyncio.run(example_2_pinned_container())
    asyncio.run(example_3_single_item())
    asyncio.run(example_4_process_url())
    asyncio.run(example_5_multi_format())
