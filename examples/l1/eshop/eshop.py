"""Eshop example: comparing pinned root vs auto-discover vs nested contracts.

Case 1 — Pinned root: ``root = ys.css('.product-card')``
    We tell Yosoi exactly which element wraps each product.
    AI skips root discovery and goes straight to field selectors.

Case 2 — Auto-discover: no root set
    AI analyses the page and decides the root element itself.
    Useful when you don't know (or don't want to hardcode) the wrapper.

Case 3 — Nested contract (pure data grouping, no DOM scoping):
    Price fields are grouped into a child contract for type safety.
    Discovery stays flat — AI sees price_amount, price_currency directly.

Case 4 — Concurrent: process multiple category pages with workers.
    Uses ``pipeline.process_urls(workers=3)`` to scrape several
    category pages in parallel via the taskiq broker.
"""

import asyncio
import re

import yosoi as ys

URL = 'https://qscrape.dev/l1/eshop/catalog/?cat=Forge%20%26%20Smithing'
CATEGORY_URLS = [
    'https://qscrape.dev/l1/eshop/catalog/?cat=Forge%20%26%20Smithing',
    'https://qscrape.dev/l1/eshop/catalog/?cat=Potions%20%26%20Elixirs',
    'https://qscrape.dev/l1/eshop/catalog/?cat=Arcane%20Tomes',
]
MODEL = 'openrouter:stepfun/step-3.5-flash:free'


# ---------------------------------------------------------------------------
# Shared contract definition
# ---------------------------------------------------------------------------


class _PriceDetails(ys.Contract):
    """Structural nesting — pure data grouping, no DOM scoping needed."""

    amount: float = ys.Price()
    currency: str = ys.Field(description='Currency name only (e.g. "Gold Sovereigns"), without the numeric amount')

    class Validators:
        @staticmethod
        def currency(v: object) -> str:
            import re

            return re.sub(r'^\d[\d.,\s]*', '', str(v)).strip()


class _BaseProduct(ys.Contract):
    name: str = ys.Title(description='Product name or title')
    price: float | None = ys.Price(description='Product price (including currency symbol)')
    rating: float = ys.Rating(description='Review score as a number')
    reviews_count: int | None = ys.Field(description='Number of reviews or ratings')
    description: str = ys.BodyText(description='Product description or summary')
    availability: str = ys.Field(description='Stock status (e.g. "In Stock", "Out of Stock")')
    is_instock: bool | None = ys.Field(description='Whether the product is in stock')

    class Validators:
        @staticmethod
        def rating(v: object) -> float:
            return float(str(v).count('★'))

        @staticmethod
        def reviews_count(v: object) -> int | None:
            if v is None:
                return None
            m = re.search(r'\d+', str(v))
            return int(m.group()) if m else None

        @staticmethod
        def is_instock(v: object) -> bool | None:
            if v is None:
                return None
            text = str(v).strip().lower()
            return not ('out of stock' in text or not text)


# ---------------------------------------------------------------------------
# Case 1 — Pinned root
# ---------------------------------------------------------------------------


class ProductPinned(_BaseProduct):
    """Root is hard-coded — AI never has to guess the wrapper element."""

    root = ys.css('.product-card')


# ---------------------------------------------------------------------------
# Case 2 — Auto-discover root
# ---------------------------------------------------------------------------


class ProductAuto(_BaseProduct):
    """No root set — AI analyses the page and picks the wrapper itself."""


# ---------------------------------------------------------------------------
# Case 3 — Nested contract (pure data grouping)
# ---------------------------------------------------------------------------


class ProductComposed(_BaseProduct):
    """Nested price sub-contract — Case 3: no root on child (pure data grouping)."""

    root = ys.css('.product-card')
    price: _PriceDetails = ys.Field(description='Product price')  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _print_items(label: str, items: list) -> None:
    print(f'\n{"=" * 60}')
    print(f'  {label}  ({len(items)} items)')
    print('=' * 60)
    for i, item in enumerate(items, 1):
        price = item.get('price')
        if isinstance(price, dict):
            price = price.get('amount', '?')
        print(
            f'  #{i:02d}  {item.get("name", "?")[:40]:<40s}'
            f'  £{price or "?":>6}  '
            f'{"✓" if item.get("is_instock") else "✗"} stock'
        )


async def run_pinned() -> None:
    print('\n[Case 1] Pinned root = ys.css(".product-card")')
    pipeline = ys.Pipeline(llm_config=MODEL, contract=ProductPinned, output_format='json')
    items = [item async for item in pipeline.scrape(URL, force=False)]
    _print_items('Pinned root', items)


async def run_auto() -> None:
    print('\n[Case 2] Auto-discover root')
    pipeline = ys.Pipeline(llm_config=MODEL, contract=ProductAuto, output_format='json')
    items = [item async for item in pipeline.scrape(URL, force=False)]
    _print_items('Auto-discover root', items)


async def run_composed() -> None:
    print('\n[Case 3] Nested contract (price: _PriceDetails)')
    pipeline = ys.Pipeline(llm_config=MODEL, contract=ProductComposed, output_format='json')
    items = [item async for item in pipeline.scrape(URL, force=False)]
    _print_items('Nested contract', items)


async def run_concurrent() -> None:
    """Case 4 — Process multiple category pages concurrently with workers=3.

    All same-domain URLs are now processed (no domain-dedup skips).
    Per-domain serialization ensures the first URL discovers selectors
    and siblings hit the snapshot cache.
    """
    print('\n[Case 4] Concurrent workers=3 — all same-domain URLs processed')
    pipeline = ys.Pipeline(llm_config=MODEL, contract=ProductPinned, output_format='json')
    results = await pipeline.process_urls(CATEGORY_URLS, workers=3)
    print(f'  Successful: {len(results["successful"])}')
    print(f'  Failed:     {len(results["failed"])}')


async def main() -> None:
    await run_pinned()
    await run_auto()
    await run_composed()
    await run_concurrent()


asyncio.run(main())
