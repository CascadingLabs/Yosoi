"""Fan-out PoC: six Maps cities replayed off the SAME A3Node plan, fully concurrently.

The concurrency goal made concrete. Each city is an independent A3Node-replay job in
its own fresh `BrowserSession` (teleport demands a clean session), driven through
`fan_out` at a bounded concurrency `limit`. Because the executor holds no shared mutable
state and only reads the plan, the six replays don't interfere — and we prove it two ways:

  * distinctness — each city returns its own ranked shops (teleport isolation held under load)
  * speedup     — wall-clock vs the summed per-job time ≈ the concurrency limit

Run (override with FANOUT_LIMIT, e.g. FANOUT_LIMIT=3 on a small box):

    uv run python examples/opencode_voidcrawl/fanout_maps.py     # voidcrawl>=0.3.2 + Chromium

The browser-free concurrency contract this leans on is unit-tested in test_fanout.py.
"""

from __future__ import annotations

import asyncio
import json
import os
from functools import partial
from time import monotonic

from fanout import fan_out
from maps_teleport import OUT_DIR, City, GuitarShop, scrape_city
from voidcrawl import BrowserConfig

# Six cities — the "six maps jobs at a time" use case. Structure is identical across
# jobs; only the teleport coordinates differ, so one plan shape replays six ways.
SIX_CITIES = [
    City('New York', 40.7128, -74.0060, 'America/New_York'),
    City('Los Angeles', 34.0522, -118.2437, 'America/Los_Angeles'),
    City('Chicago', 41.8781, -87.6298, 'America/Chicago'),
    City('Houston', 29.7604, -95.3698, 'America/Chicago'),
    City('Phoenix', 33.4484, -112.0740, 'America/Phoenix'),
    City('Seattle', 47.6062, -122.3321, 'America/Los_Angeles'),
]

JobResult = tuple[str, float, float, list[GuitarShop]]  # (city, elapsed, verify_score, shops)


async def _timed_city(city: City, cfg: BrowserConfig) -> JobResult:
    """One fan-out job: time a single city's full replay + extract."""
    started = monotonic()
    score, shops = await scrape_city(city, cfg)
    return city.name, monotonic() - started, score, shops


async def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    limit = int(os.getenv('FANOUT_LIMIT', str(len(SIX_CITIES))))
    cfg = BrowserConfig(headless=True, stealth=True, no_sandbox=True)

    print(f'fanning out {len(SIX_CITIES)} Maps replays (concurrency limit={limit})', flush=True)
    jobs = [partial(_timed_city, city, cfg) for city in SIX_CITIES]

    wall_start = monotonic()
    results = await fan_out(jobs, limit=limit)
    wall = monotonic() - wall_start

    print('\n=== per-city (each an isolated A3Node replay; teleport sets the city) ===', flush=True)
    job_seconds = 0.0
    for city, outcome in zip(SIX_CITIES, results, strict=True):
        if isinstance(outcome, Exception):  # isolated — one failure doesn't sink the batch
            print(f'  {city.name:12s}: FAILED — {type(outcome).__name__}: {outcome}', flush=True)
            continue
        name, elapsed, score, shops = outcome
        job_seconds += elapsed
        top = shops[0] if shops else None
        line = f'  {name:12s}: {len(shops):2d} shops  (verify {score:.0%}, {elapsed:.1f}s)'
        if top:
            line += f'  e.g. {top.name!r} ({top.rating}★)'
        print(line, flush=True)
        (OUT_DIR / f'{name.lower().replace(" ", "_")}.json').write_text(
            json.dumps([s.model_dump() for s in shops], indent=2), encoding='utf-8'
        )

    speedup = (job_seconds / wall) if wall else 0.0
    print(
        f'\n  wall={wall:.1f}s   summed-jobs={job_seconds:.1f}s   speedup={speedup:.1f}x  (limit={limit})',
        flush=True,
    )
    print('  speedup approaching the limit = the replays genuinely overlapped.', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
