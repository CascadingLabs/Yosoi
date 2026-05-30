"""Scoped experiment: extract Google Maps review_count via ys.js.

Validates that the JS probe returns the correct review count before wiring
it into the full homewell_maps_reviews.py batch.

Run:
    uv run python experiments/maps_js_review_count.py
"""

from __future__ import annotations

import asyncio

import yosoi as ys
from yosoi.utils.files import init_yosoi, is_initialized

MODEL = ys.claude_sdk('claude-sonnet-4-6')
FETCHER = 'headless'

SEED_URL = 'https://www.google.com/maps/search/HomeWell+Care+Services+Plano%2C+TX/@33.021,-96.719,15z'

# ── Contract ──────────────────────────────────────────────────────────────────


class MapsPlaceFacts(ys.Contract):
    """Minimal Maps contract — CSS discovery for most fields, ys.js for review_count.

    review_count uses ys.js auto-discovery: LLM writes the script once on the
    first domain visit, caches it, replays on all subsequent URLs — zero extra
    LLM calls after the first.
    """

    business_name: str = ys.Title(default='')
    rating: str = ys.Rating(default='')
    review_count: str = ys.js(
        description=(
            'Google Maps review count — the integer shown in parentheses next to the '
            "star rating, e.g. '47' from '4.7 (47)' or '1,234' from '4.8 (1,234)'. "
            'Return only the digits and commas, no parentheses or surrounding text.'
        ),
        default='',
    )
    phone: str = ys.Field(
        default='',
        description="Business phone number shown on the Maps panel, e.g. '(972) 555-1234'.",
    )


# ── Runner ────────────────────────────────────────────────────────────────────


async def main() -> None:  # noqa: D103
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

    rc = items[0].get('review_count', '') if items else ''
    rating = items[0].get('rating', '') if items else ''
    if rc and rc != rating:
        print(f'\n✓ review_count={rc!r} is distinct from rating={rating!r} — looks correct')
    elif rc == rating:
        print(f'\n✗ review_count={rc!r} duplicates rating — JS probe needs adjustment')
    else:
        print('\n✗ review_count is empty — JS probe found nothing')


if __name__ == '__main__':
    asyncio.run(main())
