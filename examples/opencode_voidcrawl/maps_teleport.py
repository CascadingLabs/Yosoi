"""Google Maps geolocation-teleport scrape — canonical ReplayPlan, unified selectors, no LLM.

The same query ("guitar shops near me") in three cities, where the city is set only by
**teleporting** the browser's geolocation (CAS-45). The flow is a canonical `ReplayPlan`
(yosoi.models.replay) — A3Node parts (teleport -> navigate x2 -> scroll-until) — then
**executed and verified by rerun** (replay_runtime), yielding a `VerifyReport` score.

Extraction reuses Yosoi's selector + type machinery, with no regex on the recipe:
each field is a `FieldSelectors` cascade of `SelectorEntry` (here `role('image')`, the
AX selector) and a Yosoi coercion `type` that turns the matched node's text into the
value — `rating` via the built-in Rating coercer, `reviews` via a small coercer whose
regex lives in the *type*, not the recipe. The selector finds the node; the type reads
the value. Zero LLM at runtime.

    uv run python examples/opencode_voidcrawl/maps_teleport.py   # voidcrawl>=0.3.2 + Chromium
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from replay_runtime import execute_plan, load_plan, open_page, save_plan
from voidcrawl import BrowserConfig

from yosoi.core.fetcher.dom.ax import extract_records
from yosoi.models.replay import (
    ExtractField,
    ExtractRecipe,
    FieldSelectors,
    ReplayPlan,
    css,
    min_count,
    navigate,
    role,
    scroll_until,
    selector_present,
    teleport,
    url_contains,
    wait,
)
from yosoi.types import rating as _rating  # noqa: F401  registers the built-in 'rating' coercer
from yosoi.types.registry import CoercionConfig, _registry, register_coercion

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


@register_coercion('reviews', description='Review count parsed from a "… N Reviews" label')
def Reviews(v: object, config: CoercionConfig, source_url: str | None = None) -> int | None:
    """Coerce 'N Reviews' -> int. The regex lives in the TYPE (like Rating), not the recipe."""
    m = re.search(r'([\d,]+)\s*Reviews', str(v), re.IGNORECASE)
    return int(m.group(1).replace(',', '')) if m else None


# Each field: a SelectorEntry cascade + a Yosoi coercion type. The selector targets the
# right NODE by role + accessible-name substring (`role('image', 'stars')` picks the
# rating image, not the shop photo) — a selector concern, like click_by_role. The TYPE
# then reads the value from that node's text. No regex on the recipe.
_RATING_IMG = role('image', 'stars')
_EXTRACT = ExtractRecipe(
    card_role='article',
    fields=[
        ExtractField(
            key='rating',
            type='rating',
            config={'as_float': True, 'scale': 5},
            selectors=FieldSelectors(primary=_RATING_IMG),
        ),
        ExtractField(key='reviews', type='reviews', selectors=FieldSelectors(primary=_RATING_IMG)),
    ],
    skip_prefixes=['Ad ·'],
)


class GuitarShop(BaseModel):
    name: str
    rating: float | None = None
    reviews: int | None = None


_RESULTS_BASELINE = 8  # a populated feed; the scroll node then drives it up to TARGET
_GEO_SETTLE = 3.0  # see the wait node below — the ONE fixed pause in the whole system


def build_plan(city: City) -> ReplayPlan:
    """The canonical replay plan for one city — teleport coords baked into the node.

    Almost entirely event-driven, with ONE deliberate exception. Geolocation has no DOM
    *event*: Maps requests the position internally (a few seconds into the prime load) with
    no observable effect, and voidcrawl exposes no init-script hook to instrument that call.
    So a single fixed `wait` sits between prime and read to let Maps acquire the position —
    the one irreducible pause. Everything else is gated on signals: prime waits for results,
    and read+scroll wait on `url_contains('@<deg>')`, the teleport's verifiable *effect* on
    the URL. That gate doubles as geo-correctness verification — it fails loudly if the
    teleport didn't apply (instead of silently scraping stale IP-location results).
    """
    feed_present = selector_present(css(_FEED))
    results_ready = min_count(_RESULTS_BASELINE, css(_ITEM))
    geo_resolved = url_contains(f'@{int(city.lat)}')  # the teleport's verifiable effect on the URL
    prime = navigate(MAPS_URL, expect=results_ready)  # prime: trigger the geolocation request + load
    settle_geo = wait(_GEO_SETTLE, intent='let Maps acquire the teleported position (no DOM signal)')
    read = navigate(MAPS_URL, expect=geo_resolved)  # read: re-centre on the resolved position
    read.assess = feed_present  # wait for the prime load before re-navigating
    scroll = scroll_until(_FEED, _ITEM, TARGET)
    scroll.assess = geo_resolved  # only scroll once the map has actually re-centred (geo-correct)
    return ReplayPlan(
        target=TARGET_KEY,
        task='guitar shops near me',
        source='scripted',
        nodes=[teleport(city.lat, city.lon, city.tz, city.locale), prime, settle_geo, read, scroll],
        extract=_EXTRACT,
    )


def _coerce(recipe: ExtractRecipe, rec: dict[str, str | None]) -> GuitarShop:
    """Selector found the node text; the field's Yosoi type turns it into the value."""
    out: dict[str, Any] = {'name': rec.get('name') or ''}
    for f in recipe.fields:
        raw = rec.get(f.key)
        coercer = _registry.get(f.type)
        try:
            out[f.key] = coercer(raw, dict(f.config)) if (raw and coercer) else None
        except (ValueError, TypeError):
            out[f.key] = None
    return GuitarShop(**out)


async def scrape_city(city: City, cfg: BrowserConfig) -> tuple[float, list[GuitarShop]]:
    """Execute the plan in a FRESH session (teleport needs a clean one), then extract."""
    plan = build_plan(city)
    async with open_page(cfg) as page:  # blank first so teleport applies pre-nav; teardown guaranteed
        report = await execute_plan(plan, page)
        ax_nodes = await page.get_full_ax_tree()
        recipe = plan.extract or _EXTRACT
        records = extract_records(
            ax_nodes,
            card_role=recipe.card_role,
            fields={f.key: f.selectors for f in recipe.fields},
            skip_name_prefixes=tuple(recipe.skip_prefixes),
        )
        return report.score, [_coerce(recipe, r) for r in records[:TARGET]]


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

    print('\n=== results (teleport drives the city; AX selectors + type coercion; verified) ===', flush=True)
    for city in CITIES:
        score, shops = results[city.name]
        (OUT_DIR / f'{city.name.lower().replace(" ", "_")}.json').write_text(
            json.dumps([s.model_dump() for s in shops], indent=2), encoding='utf-8'
        )
        top = shops[0] if shops else None
        line = f'  {city.name:12s}: {len(shops):2d} shops  (verify {score:.0%})'
        if top:
            line += f'  e.g. {top.name!r} ({top.rating}★, {top.reviews} reviews)'
        print(line, flush=True)
    print(f'\n  plan -> {path}   per-city JSON -> {OUT_DIR}', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
