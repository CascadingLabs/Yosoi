"""Google Maps geolocation-teleport scrape — scripted PyO3 + accessibility-tree selectors.

The use case: the *same* query ("guitar shops near me") in three cities, where the
city is set purely by **teleporting** the browser's geolocation (CAS-45) — so Maps'
"near me" resolution, not the query text, drives the results.

Two deliberate choices:

  * Scripted PyO3 for the fixed mechanics (teleport -> navigate x2 -> scroll the feed
    to >= TARGET). No LLM in the browsing loop, fully reproducible.
  * **Accessibility-tree selectors** for extraction (CAS-27), not CSS. Each result is
    role="article" with the shop name as its accessible name; the rating is a
    descendant role="image" named "4.4 stars 2,980 Reviews". Those roles + names are
    stable and human-readable, where Maps' obfuscated classes (a.hfpxzc, MW4etd) churn.
    Because the AX semantics are clear, no LLM discovery is needed here at all — the
    AX "selector" is a tiny, readable recipe (see ax_extract.AxField). For a site with
    murkier semantics, the same recipe could be discovered once from the compact AX
    outline (cheaper to read than HTML) — that's the discover-once path on AX.

Run (needs voidcrawl >= 0.3.2 PyO3 + Chromium; no OpenCode/MCP needed):
    uv run python examples/opencode_voidcrawl/maps_teleport.py
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from ax_extract import AxField, extract_cards
from pydantic import BaseModel
from voidcrawl import BrowserConfig, BrowserSession

HERE = Path(__file__).parent

# "near me" so Maps resolves location from navigator.geolocation (which teleport
# overrides) rather than the IP-based map viewport.
MAPS_URL = 'https://www.google.com/maps/search/guitar+shops+near+me/'
TARGET = 20  # force enough results that the feed must be scrolled (lazy-loaded)


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


class GuitarShop(BaseModel):
    name: str
    rating: float | None = None
    reviews: int | None = None
    address: str | None = None


# ── accessibility-tree selectors (CAS-27) ───────────────────────────────────
# Each card is an `article`; these fields are read from within its subtree by role.
_CARD_ROLE = 'article'
_FIELDS = [
    AxField('rating', role='image', pattern=r'([\d.]+)\s*stars'),
    AxField('reviews', role='image', pattern=r'stars?\s+([\d,]+)\s*Reviews'),
    AxField(
        'address',
        role='StaticText',
        pattern=r'\d{1,6}\s+\w.*\b(?:St|Ave|Avenue|Blvd|Rd|Road|Dr|Drive|Ln|Lane|Way|Pl|Pkwy|Hwy|Street|Ct|Sq|Fl)\b',
    ),
]


def _to_shop(rec: dict[str, str | None]) -> GuitarShop:
    r, rv = rec.get('rating'), rec.get('reviews')
    rating = float(r) if r else None
    reviews = int(rv.replace(',', '')) if rv else None
    return GuitarShop(name=rec.get('name') or '', rating=rating, reviews=reviews, address=rec.get('address'))


# ── scripted PyO3 browsing (deterministic) + AX extraction ──────────────────


async def scrape_city(city: City, cfg: BrowserConfig, target: int = TARGET) -> list[GuitarShop]:
    """Teleport to *city* in a FRESH session, scroll Maps to >= target, extract via AX.

    A fresh session per location is required (per the teleport docs): a recycled tab
    carries the prior page's resolved location, so cities would bleed into each other.
    """
    async with BrowserSession(cfg) as browser:
        page = await browser.new_page('about:blank')  # blank first so we can teleport pre-nav
        await page.set_geolocation(city.lat, city.lon, 50.0)
        await page.set_timezone(city.tz)
        await page.set_locale(city.locale)
        await page.navigate(MAPS_URL)  # prime: Maps resolves location on first load
        await asyncio.sleep(2.5)
        await page.navigate(MAPS_URL)  # read: applies the teleported location
        await asyncio.sleep(3.5)
        for _ in range(15):
            raw = await page.evaluate_js(
                '(()=>{const f=document.querySelector(\'div[role="feed"]\');'
                'if(!f)return -1;f.scrollTop=f.scrollHeight;'
                "return f.querySelectorAll('a.hfpxzc').length;})()"
            )
            count = raw if isinstance(raw, int) else -1
            print(f'  [{city.name}] scrolled -> {count} results', flush=True)
            if count >= target:
                break
            await asyncio.sleep(1.3)
        nodes = await page.get_full_ax_tree()
        cards = extract_cards(nodes, card_role=_CARD_ROLE, fields=_FIELDS, skip_name_prefixes=('Ad ·',))
        return [_to_shop(r) for r in cards[:target]]
    raise RuntimeError('BrowserSession exited without yielding a page')  # unreachable


# ── orchestration (the script does as much as possible) ─────────────────────


async def main() -> None:
    out_dir = HERE / '.yosoi' / 'maps'
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = BrowserConfig(headless=True, stealth=True, no_sandbox=True)

    results: dict[str, list[GuitarShop]] = {}
    for city in CITIES:
        print(f'=== {city.name} (teleport {city.lat},{city.lon}) ===', flush=True)
        results[city.name] = await scrape_city(city, cfg)

    print('\n=== results (teleport drives the city; extracted via AX role+name) ===', flush=True)
    for city in CITIES:
        shops = results[city.name]
        (out_dir / f'{city.name.lower().replace(" ", "_")}.json').write_text(
            json.dumps([s.model_dump() for s in shops], indent=2), encoding='utf-8'
        )
        top = shops[0] if shops else None
        line = f'  {city.name:12s}: {len(shops):2d} shops'
        if top:
            line += f'  e.g. {top.name!r} ({top.rating}★, {top.reviews} reviews) {top.address or ""}'
        print(line, flush=True)
    print(f'\n  per-city JSON -> {out_dir}', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
