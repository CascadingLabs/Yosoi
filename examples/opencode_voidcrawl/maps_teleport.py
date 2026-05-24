"""Google Maps geolocation-teleport scrape — canonical ReplayPlan, executed + verified.

The same query ("guitar shops near me") in three cities, where the city is set only
by **teleporting** the browser's geolocation (CAS-45). The flow is expressed as a
canonical `ReplayPlan` (yosoi.models.replay) — a sequence of A3Node parts
(teleport -> navigate x2 -> scroll-until) built from reusable helpers — then **executed
and verified by rerun** (replay_runtime): each node's `assert` is checked, yielding a
`VerifyReport` quality score. Extraction uses AX role+name selectors (CAS-27).

This supersedes the earlier bespoke a3node.py: the plan is now the canonical schema,
and the same plan an MCP agent emits (replay_runtime.plan_from_tool_parts) is what
runs here. The plan is persisted and reloaded across runs.

    uv run python examples/opencode_voidcrawl/maps_teleport.py   # voidcrawl>=0.3.2 + Chromium
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel
from replay_runtime import execute_plan, load_plan, save_plan
from voidcrawl import BrowserConfig, BrowserSession

from yosoi.core.fetcher.dom.ax import AxField, extract_records
from yosoi.models.replay import (
    ExtractField,
    ExtractRecipe,
    ReplayPlan,
    css,
    navigate,
    scroll_until,
    selector_present,
    teleport,
    url_contains,
)

HERE = Path(__file__).parent
PLAN_DIR = HERE / '.yosoi' / 'plans'
OUT_DIR = HERE / '.yosoi' / 'maps'
TARGET_KEY = 'google.com/maps'

MAPS_URL = 'https://www.google.com/maps/search/guitar+shops+near+me/'
TARGET = 20
_FEED = 'div[role="feed"]'
_ITEM = 'a.hfpxzc'


@dataclass(frozen=True)
class City:
    name: str
    lat: float
    lon: float
    tz: str
    locale: str = 'en-US'


CITIES = [
    City('New York', 40.7128, -74.0060, 'America/New_York'),
    City('Los Angeles', 34.0522, -118.2437, 'America/Los_Angeles'),
    City('Chicago', 41.8781, -87.6298, 'America/Chicago'),
]

_EXTRACT = ExtractRecipe(
    card_role='article',
    fields=[
        ExtractField(key='rating', role='image', pattern=r'([\d.]+)\s*stars'),
        ExtractField(key='reviews', role='image', pattern=r'stars?\s+([\d,]+)\s*Reviews'),
        ExtractField(
            key='address',
            role='StaticText',
            pattern=r'\d{1,6}\s+\w.*\b(?:St|Ave|Avenue|Blvd|Rd|Road|Dr|Drive|Ln|Lane|Way|Pl|Pkwy|Hwy|Street|Ct|Sq|Fl)\b',
        ),
    ],
    skip_prefixes=['Ad ·'],
)


class GuitarShop(BaseModel):
    name: str
    rating: float | None = None
    reviews: int | None = None
    address: str | None = None


def build_plan(city: City) -> ReplayPlan:
    """The canonical replay plan for one city — teleport coords baked into the node.

    Settling is event-driven: the read-navigate and scroll nodes `assess` that the
    results feed is present (the prior step finished loading) instead of sleeping —
    the SPA's network never idles, so readiness is gated on the structure.
    """
    feed_present = selector_present(css(_FEED))
    read = navigate(MAPS_URL, expect=url_contains('/maps/'))  # read
    read.assess = feed_present  # wait for the prime load before re-navigating
    scroll = scroll_until(_FEED, _ITEM, TARGET)
    scroll.assess = feed_present  # wait for the read load before scrolling
    return ReplayPlan(
        target=TARGET_KEY,
        task='guitar shops near me',
        source='scripted',
        nodes=[
            teleport(city.lat, city.lon, city.tz, city.locale),
            navigate(MAPS_URL),  # prime
            read,
            scroll,
        ],
        extract=_EXTRACT,
    )


def _to_shop(rec: dict[str, str | None]) -> GuitarShop:
    r, rv = rec.get('rating'), rec.get('reviews')
    return GuitarShop(
        name=rec.get('name') or '',
        rating=float(r) if r else None,
        reviews=int(rv.replace(',', '')) if rv else None,
        address=rec.get('address'),
    )


def _ax_fields(recipe: ExtractRecipe) -> list[AxField]:
    return [AxField(f.key, role=f.role, pattern=f.pattern) for f in recipe.fields]


async def scrape_city(city: City, cfg: BrowserConfig) -> tuple[float, list[GuitarShop]]:
    """Execute the plan in a FRESH session (teleport needs a clean one), then extract."""
    plan = build_plan(city)
    async with BrowserSession(cfg) as browser:
        page = await browser.new_page('about:blank')  # blank first so teleport applies pre-nav
        report = await execute_plan(plan, page)
        ax_nodes = await page.get_full_ax_tree()
        recipe = plan.extract or _EXTRACT
        records = extract_records(
            ax_nodes,
            card_role=recipe.card_role,
            fields=_ax_fields(recipe),
            skip_name_prefixes=tuple(recipe.skip_prefixes),
        )
        return report.score, [_to_shop(r) for r in records[:TARGET]]
    raise RuntimeError('BrowserSession exited without yielding a page')  # unreachable


async def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cfg = BrowserConfig(headless=True, stealth=True, no_sandbox=True)

    existing = load_plan(TARGET_KEY, PLAN_DIR)
    print(f'plan for {TARGET_KEY}: {"reloaded" if existing else "building fresh"}', flush=True)

    results: dict[str, tuple[float, list[GuitarShop]]] = {}
    for city in CITIES:
        print(f'=== {city.name} (teleport {city.lat},{city.lon}) ===', flush=True)
        score, shops = await scrape_city(city, cfg)
        results[city.name] = (score, shops)
        print(f'  verify score={score:.2f}  shops={len(shops)}', flush=True)

    # Persist the representative plan (structure is identical; teleport coords are input).
    plan = existing or build_plan(CITIES[0])
    if existing:
        plan.replay_count += 1
    path = save_plan(plan, PLAN_DIR)

    print('\n=== results (teleport drives the city; AX extraction; verified replay) ===', flush=True)
    for city in CITIES:
        score, shops = results[city.name]
        (OUT_DIR / f'{city.name.lower().replace(" ", "_")}.json').write_text(
            json.dumps([s.model_dump() for s in shops], indent=2), encoding='utf-8'
        )
        top = shops[0] if shops else None
        line = f'  {city.name:12s}: {len(shops):2d} shops  (verify {score:.0%})'
        if top:
            line += f'  e.g. {top.name!r} ({top.rating}★, {top.reviews}) {top.address or ""}'
        print(line, flush=True)
    print(f'\n  plan -> {path}   per-city JSON -> {OUT_DIR}', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
