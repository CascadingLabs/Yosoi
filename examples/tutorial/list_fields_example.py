"""List field extraction example using quotes.toscrape.com.

Demonstrates ``list[T]`` fields in contracts — extracting multiple values
per field from a single page or per item on a multi-item page.

Two real DOM patterns for lists:

- **Pattern A** (separate elements): ``<a class="tag">love</a><a class="tag">life</a>``
  — one selector, multiple matches.  The extractor collects *all* matched texts.

- **Pattern B** (delimited string): ``<span>Alice, Bob, and Carol</span>``
  — one selector, one match.  Coercion splits on ``, ; and`` by default
  (or a custom ``delimiter`` regex).

This example uses quotes.toscrape.com where each quote has:
- ``span.text``   — the quote text (scalar ``str``)
- ``small.author`` — the author name (scalar ``str``)
- ``a.tag``        — multiple tag links (``list[str]`` — Pattern A)
"""

import asyncio
import os

from dotenv import load_dotenv

import yosoi as ys

load_dotenv()


# ============================================================================
# Example 1: Multi-item page with list[str] tags (Pattern A)
# ============================================================================


class Quote(ys.Contract):
    """A quote with its author and tags.

    ``tags`` is ``list[str]`` — the AI discovers ``a.tag`` and the extractor
    collects *every* matching element instead of just the first.
    """

    root = ys.css('div.quote')

    text: str = ys.Field(description='The quote text')
    author: str = ys.Author()
    # If the LLM discovers ``div.tags`` (the wrapper) instead of ``a.tag``
    # (each item), add ``selector='a.tag'`` to pin it.
    tags: list[str] = ys.Field(description='Topic tags for the quote')


async def example_1_list_tags():
    """Extract quotes with their tags as a proper list."""
    print('\n=== Example 1: list[str] tags from separate elements (Pattern A) ===')

    pipeline = ys.Pipeline(
        os.environ.get('YOSOI_MODEL', 'openai:gpt-4o'),
        contract=Quote,
        output_format='json',
    )

    async for item in pipeline.scrape('https://quotes.toscrape.com'):
        tags = item.get('tags', [])
        tag_str = ', '.join(tags) if isinstance(tags, list) else tags
        print(f'  {item.get("author", "?"):25s}  [{tag_str}]')


# ============================================================================
# Example 2: Coercion demo — show splitting and passthrough locally
# ============================================================================


def example_2_coercion_demo():
    """Show list coercion without hitting any website."""
    print('\n=== Example 2: List coercion (no network) ===')

    # Pattern A: extractor returns a proper list — passes through unchanged
    raw_a = {'text': '"Be yourself."', 'author': 'Oscar Wilde', 'tags': ['life', 'self']}
    result_a = Quote.model_validate(raw_a)
    print(f'  Pattern A input:  {raw_a["tags"]}')
    print(f'  Pattern A output: {result_a.tags}')

    # Pattern B: single delimited string in a list — auto-split on , ; and
    raw_b = {'text': '"Be yourself."', 'author': 'Oscar Wilde', 'tags': ['life, self and wisdom']}
    result_b = Quote.model_validate(raw_b)
    print(f'  Pattern B input:  {raw_b["tags"]}')
    print(f'  Pattern B output: {result_b.tags}')

    # Raw string (edge case): also split
    raw_c = {'text': '"Be yourself."', 'author': 'Oscar Wilde', 'tags': 'life, self, wisdom'}
    result_c = Quote.model_validate(raw_c)
    print(f'  String input:     {raw_c["tags"]!r}')
    print(f'  String output:    {result_c.tags}')

    # Known limitation: "and" inside a value splits it — use a custom delimiter
    # if your data contains literal "and" (e.g. "command and control" → ['command', 'control'])
    raw_d = {'text': '"Think."', 'author': 'IBM', 'tags': ['command and control']}
    result_d = Quote.model_validate(raw_d)
    print(f'  "and" edge case:  {raw_d["tags"]} → {result_d.tags}  (splits on "and")')


# ============================================================================
# Example 3: Custom delimiter for pipe-separated values
# ============================================================================


class PipeSeparated(ys.Contract):
    """Contract with a custom pipe delimiter for categories."""

    title: str = ys.Title()
    categories: list[str] = ys.Field(description='Categories', delimiter=r'\s*\|\s*')


def example_3_custom_delimiter():
    """Show custom delimiter splitting."""
    print('\n=== Example 3: Custom delimiter ===')

    raw = {'title': 'Some Article', 'categories': ['Tech | Science | AI']}
    result = PipeSeparated.model_validate(raw)
    print(f'  Input:  {raw["categories"]}')
    print(f'  Output: {result.categories}')


# ============================================================================
# Example 4: list[float] with per-element Price coercion
# ============================================================================


class PriceComparison(ys.Contract):
    """Product with multiple vendor prices — each element gets Price coercion."""

    name: str = ys.Title()
    vendor_prices: list[float] = ys.Price(description='Prices from different vendors')


def example_4_list_price_coercion():
    """Show per-element coercion on list[float] with ys.Price()."""
    print('\n=== Example 4: list[float] with Price coercion ===')

    raw = {'name': 'Widget', 'vendor_prices': ['$12.99', '£9.50', '€11.00']}
    result = PriceComparison.model_validate(raw)
    print(f'  Input:  {raw["vendor_prices"]}')
    print(f'  Output: {result.vendor_prices}')


if __name__ == '__main__':
    # Local demos (no API key needed)
    example_2_coercion_demo()
    example_3_custom_delimiter()
    example_4_list_price_coercion()

    # Live scrape (needs YOSOI_MODEL / API key)
    asyncio.run(example_1_list_tags())
