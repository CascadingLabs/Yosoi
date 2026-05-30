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

# ── JS probe ───────────────────────────────────────────────────────────────────

_REVIEW_COUNT_JS = """
(() => {
  // Primary: .F7nice textContent contains "4.7(43)" — fast O(1) lookup.
  const ratingEl = document.querySelector('.F7nice');
  if (ratingEl) {
    const m = (ratingEl.textContent || '').match(/\\((\\d[\\d,]+)\\)/);
    if (m) return m[1];
  }
  // Fallback: scan leaf nodes for "(N)" — survives .F7nice class rotation.
  for (const el of document.querySelectorAll('span, div')) {
    if (el.children.length === 0) {
      const text = (el.textContent || '').trim();
      const m = text.match(/^\\((\\d[\\d,]+)\\)$/);
      if (m) return m[1];
    }
  }
  return '';
})()
""".strip()


# ── Contract ──────────────────────────────────────────────────────────────────


class MapsPlaceFacts(ys.Contract):
    """Minimal Maps contract — rating via CSS discovery, review_count via ys.js."""

    business_name: str = ys.Title(default='')
    rating: str = ys.Rating(default='')
    review_count: str = ys.js(
        _REVIEW_COUNT_JS,
        default='',
        description='Google review count extracted from parenthetical text in the live DOM.',
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
