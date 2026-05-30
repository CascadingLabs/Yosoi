"""Phase-0 warmup before the full 151-URL run.

Phase 1 — single URL, sequential:
    Discovers selectors + records A3Node for google.com.
    Prints what was found so you can sanity-check before going wider.

Phase 2 — 3 URLs, workers=3:
    Verifies cached selectors replay correctly on different franchise locations.
    Gentle on the machine; each worker opens one headless browser tab.

Run:
    uv run python experiments/homewell_maps_warmup.py

After you're happy with the output, run the full batch:
    uv run python experiments/homewell_maps_reviews.py
"""

from __future__ import annotations

import asyncio
from typing import Any

import yosoi as ys
from yosoi import Pipeline
from yosoi.reporting import banner, print_records, report_a3node, report_selectors
from yosoi.utils.files import init_yosoi, is_initialized

# ── Config ─────────────────────────────────────────────────────────────────────

MODEL = ys.claude_sdk('claude-sonnet-4-6')
FETCHER = 'headless'

SEED_URL = 'https://www.google.com/maps/search/HomeWell+Care+Services+Plano%2C+TX/@33.021,-96.719,15z'

PROBE_URLS = [
    'https://www.google.com/maps/search/HomeWell+Care+Services+Seattle%2C+WA/@47.734,-122.356,15z',
    'https://www.google.com/maps/search/HomeWell+Care+Services+Troy%2C+MI/@42.558,-83.155,15z',
    'https://www.google.com/maps/search/HomeWell+Care+Services+Tampa%2C+FL/@28.036,-82.489,15z',
]

MAPS_DOMAIN = 'google.com'


# ── Contract ──────────────────────────────────────────────────────────────────


class MapsPlaceFacts(ys.Contract):
    """GBP signals from a Google Maps place/search page."""

    business_name: str = ys.Title(default='')
    rating: str = ys.Rating(default='')
    review_count: str = ys.Field(default='')  # TODO: wire up once eval_js lands
    category: str = ys.Field(
        default='',
        description="Google Maps business category, e.g. 'Home health care service'. Empty if not shown.",
    )
    address: str = ys.Field(default='', description='Street address shown on the Maps panel. Empty if not visible.')
    hours: str = ys.Field(
        default='',
        description="Opening hours status, e.g. 'Open 24 hours' or 'Closed'. Empty if not shown.",
    )
    phone: str = ys.Field(
        default='',
        description="Business phone number as shown on the Maps panel, e.g. '(972) 555-1234'. Empty if not displayed.",
    )


# ── Phase runners ──────────────────────────────────────────────────────────────


async def run_phase1() -> Pipeline:
    """Single-URL seed: discover selectors + A3Node. Returns the live pipeline."""
    banner('PHASE 1 — single URL seed', 'Discovering selectors + A3Node for google.com')
    print(f'  URL: {SEED_URL}\n')

    pipeline = Pipeline(
        MODEL,
        contract=MapsPlaceFacts,
        output_format=['json'],
        selector_level=ys.SelectorLevel.CSS,
        experimental_a3node=True,
    )

    items: list[dict[str, Any]] = [
        item
        async for item in pipeline.scrape(
            SEED_URL,
            fetcher_type=FETCHER,
            force=True,
        )
    ]

    print_records(items, title='Extracted (Phase 1)')
    await report_selectors(pipeline.storage, MAPS_DOMAIN, title='Selectors cached for google.com')
    await report_a3node(MAPS_DOMAIN, title='A3Node for google.com')

    return pipeline


async def run_phase2(pipeline: Pipeline) -> None:
    """3-URL concurrent replay. Re-uses the pipeline from Phase 1."""
    banner('PHASE 2 — 3 URLs, workers=3  (cached selector replay)')
    for u in PROBE_URLS:
        print(f'  • {u}')
    print()

    results = await pipeline.process_urls(
        PROBE_URLS,
        workers=3,
        fetcher_type=FETCHER,
        force=False,
    )

    ok = len(results.get('successful', []))
    fail = len(results.get('failed', []))
    print(f'\n  Result: {ok} ok  {fail} failed')

    for url in PROBE_URLS:
        content = await pipeline.storage.load_content(url, contract_sig=pipeline._contract_sig)
        label = url.split('search/')[1].split('/@')[0].replace('+', ' ')
        items = [content] if isinstance(content, dict) else (content or [])
        print_records(items, title=f'Probe: {label}')

    await report_a3node(MAPS_DOMAIN, title='A3Node after Phase 2 (replay_count should be ≥ 3)')


# ── Entry point ────────────────────────────────────────────────────────────────


async def main() -> None:
    if not is_initialized():
        init_yosoi()

    pipeline = await run_phase1()

    print('\n  → Phase 1 complete. Review the selectors above.')
    print('    Press Enter to run Phase 2 (3 concurrent probes), or Ctrl-C to stop.')
    try:
        await asyncio.to_thread(input)
    except (EOFError, KeyboardInterrupt):
        print('\n  Stopped before Phase 2.')
        return

    await run_phase2(pipeline)

    print('\n  ✓ Warmup done. Selectors and A3Node are validated.')
    print('    Run the full batch when ready:')
    print('      uv run python experiments/homewell_maps_reviews.py')


if __name__ == '__main__':
    asyncio.run(main())
