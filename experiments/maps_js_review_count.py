"""Scoped experiment: extract Google Maps review_count via ys.js.

Validates that the JS probe returns the correct review count before wiring
it into the full homewell_maps_reviews.py batch.

Run:
    uv run python experiments/maps_js_review_count.py
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from pydantic import BeforeValidator

import yosoi as ys
from yosoi.utils.files import init_yosoi, is_initialized

MODEL = ys.claude_sdk('claude-sonnet-4-6')
FETCHER = 'headless'

SEED_URL = 'https://www.google.com/maps/search/HomeWell+Care+Services+Plano%2C+TX/@33.021,-96.719,15z'

# ── Contract ──────────────────────────────────────────────────────────────────


def _to_count(value: object) -> int:
    """Coerce a raw review-count value ('1,234', '47', native int) to an int."""
    text = str(value).strip()
    return int(text.replace(',', '')) if text and text.lower() != 'none' else 0


class MapsPlaceFacts(ys.Contract):
    """Minimal Maps contract — CSS discovery for most fields, ys.js for review_count.

    review_count uses ys.js auto-discovery: the LLM writes the script once on the
    first domain visit, caches it, replays on all subsequent URLs — zero extra LLM
    calls after the first.

    review_count is **statically typed as int** with a comma-tolerant
    ``BeforeValidator`` (CAS-114). The JS output is validated through this declared
    Pydantic type at *discovery* (a script returning a non-numeric blob is rejected
    and retried) and at *scrape* (a bad value is dropped to the default, not kept
    raw) — so the field is a real int, not a loosely-typed string.
    """

    business_name: str = ys.Title(default='')
    rating: str = ys.Rating(default='')
    review_count: Annotated[int, BeforeValidator(_to_count)] = ys.js(
        description=(
            'Google Maps review count — the integer shown in parentheses next to the '
            "star rating, e.g. 47 from '4.7 (47)' or 1234 from '4.8 (1,234)'. "
            'Return only the digits and commas, no parentheses or surrounding text.'
        ),
        default=0,
    )
    phone: str = ys.Field(
        default='',
        description="Business phone number shown on the Maps panel, e.g. '(972) 555-1234'.",
    )


# ── Runner ────────────────────────────────────────────────────────────────────


async def main() -> None:
    if not is_initialized():
        init_yosoi()

    print(f'URL:     {SEED_URL}')
    print(f'Fetcher: {FETCHER}\n')

    items = await ys.scrape(
        SEED_URL,
        MapsPlaceFacts,
        model=MODEL,
        fetcher_type=FETCHER,
        force=True,
        quiet=False,
    )

    print('\n── Result ───────────────────────────────────────────────────────')
    if not items:
        print('  (no items returned)')
        return
    for item in items:
        for field, value in item.items():
            v = str(value or '').strip()
            print(f'  {field:<16} {v!r}')
    print('─────────────────────────────────────────────────────────────────')

    rc = items[0].get('review_count', 0) if items else 0
    if isinstance(rc, int) and rc > 0:
        print(f'\n✓ review_count={rc!r} (int) — typed + validated, looks correct')
    else:
        print(f'\n✗ review_count={rc!r} — JS probe found nothing usable')


if __name__ == '__main__':
    asyncio.run(main())
