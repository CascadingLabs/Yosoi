"""Google Maps geolocation-teleport scrape — scripted PyO3 + discover-once.

The use case: the *same* query ("guitar shops") in three cities, where the city
is set purely by **teleporting** the browser's geolocation (CAS-45) — so Maps'
"near me" resolution, not the query text, drives the results.

Why this split (decided with the maintainer): the teleport→navigate→scroll recipe
is fixed, so the deterministic mechanics run in-script over the **PyO3 binding**
(voidcrawl >= 0.3.2) — no LLM in the browsing loop, fully reproducible. The LLM
(OpenCode) is reserved for the one part that needs judgement: discovering the
result-card selectors **once** on the first city, which are then replayed
deterministically (parsel) across the rest. "Discover once, scrape forever."

  per city (scripted PyO3, deterministic):
      tab.set_geolocation/timezone/locale  ->  teleport
      tab.navigate(url) x2                  ->  prime + read (Maps applies geo on 2nd)
      scroll div[role=feed] until >= TARGET ->  forces the lazy-load "action"
      tab.content()                         ->  rendered HTML
  once (OpenCode LLM):  discover card/name/rating/address selectors on city 1
  every city (parsel):  replay those selectors -> GuitarShop rows

Run (needs `opencode auth login`; voidcrawl 0.3.2 PyO3 + Chromium; no MCP needed):
    uv run python examples/opencode_voidcrawl/maps_teleport.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from parsel import Selector
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from voidcrawl import BrowserConfig, BrowserSession

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))  # opencode_server

from opencode_server import ensure_opencode_server

from yosoi.integrations.opencode import OpenCodeModel

load_dotenv()

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


class ShopSelectors(BaseModel):
    """CSS selectors for one Maps result card and its fields (discovered once)."""

    card: str = Field(description='CSS selector matching ONE repeating result card (multiple on the page)')
    name: str = Field(description='CSS selector (relative to a card) for the shop name')
    name_attr: str | None = Field(
        default=None, description="Attribute holding the name, e.g. 'aria-label'; null if text"
    )
    rating: str | None = Field(default=None, description='CSS selector (relative to a card) for the numeric rating')
    address: str | None = Field(default=None, description='CSS selector (relative to a card) for the address/locality')


class GuitarShop(BaseModel):
    name: str
    rating: float | None = None
    address: str | None = None


# Anchor that the probe proved reliable, used only if discovery extracts nothing.
_FALLBACK = ShopSelectors(card='a.hfpxzc', name='', name_attr='aria-label')


# ── scripted PyO3 browsing (deterministic) ──────────────────────────────────


async def render_city(city: City, cfg: BrowserConfig, target: int = TARGET) -> str:
    """Teleport to *city* in a FRESH session, load Maps, scroll to >= target, return HTML.

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
        return await page.content()
    raise RuntimeError('BrowserSession exited without yielding a page')  # unreachable


# ── discover once (LLM) + replay (parsel) ───────────────────────────────────


async def discover_selectors(html: str, model: OpenCodeModel) -> ShopSelectors:
    """Ask OpenCode to find the result-card + field selectors from a feed sample."""
    feed = Selector(text=html).css('div[role="feed"]').get() or html
    sample = feed[:18000]
    agent: Agent[None, ShopSelectors] = Agent(
        model,
        output_type=ShopSelectors,
        system_prompt=(
            'You are given a slice of a Google Maps results feed. Return robust CSS selectors '
            'for ONE repeating result card and, relative to a card, the shop name, numeric '
            'rating, and address. The name is usually the aria-label of the result link.'
        ),
    )
    result = await agent.run(f'HTML feed sample:\n{sample}')
    return result.output


def extract_shops(html: str, sel: ShopSelectors, limit: int = TARGET) -> list[GuitarShop]:
    """Replay discovered selectors over a city's HTML — deterministic, no LLM."""
    shops: list[GuitarShop] = []
    for card in Selector(text=html).css(sel.card)[:limit]:
        if sel.name_attr:
            name = card.css(sel.name).attrib.get(sel.name_attr) or card.attrib.get(sel.name_attr)
        else:
            name = card.css(f'{sel.name} ::text').get() or card.css(sel.name).xpath('normalize-space()').get()
        if not name:
            continue
        rating_txt = card.css(f'{sel.rating} ::text').get() if sel.rating else None
        address = card.css(f'{sel.address} ::text').get() if sel.address else None
        rating: float | None = None
        if rating_txt:
            try:
                rating = float(rating_txt.strip().split()[0].replace(',', '.'))
            except (ValueError, IndexError):
                rating = None
        shops.append(GuitarShop(name=name.strip(), rating=rating, address=address.strip() if address else None))
    return shops


# ── orchestration (the script does as much as possible) ─────────────────────


async def main() -> None:
    out_dir = HERE / '.yosoi' / 'maps'
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = BrowserConfig(headless=True, stealth=True, no_sandbox=True)

    async with ensure_opencode_server():
        model = OpenCodeModel(
            provider_id=os.getenv('OC_PROVIDER', 'openai'),
            model_id=os.getenv('OC_MODEL', 'gpt-5.3-codex'),
        )

        # City 1: render + discover the selectors once.
        print(f'=== rendering {CITIES[0].name} (discovery city) ===', flush=True)
        first_html = await render_city(CITIES[0], cfg)
        print('=== discovering result-card selectors (LLM, once) ===', flush=True)
        selectors = await discover_selectors(first_html, model)
        print(f'  discovered: {selectors.model_dump(exclude_none=True)}', flush=True)
        first_shops = extract_shops(first_html, selectors)
        if not first_shops:
            print('  discovery extracted 0 — falling back to a.hfpxzc[aria-label]', flush=True)
            selectors = _FALLBACK
            first_shops = extract_shops(first_html, selectors)
        (out_dir / 'selectors.json').write_text(selectors.model_dump_json(indent=2), encoding='utf-8')

        # All cities: render in a FRESH session + replay the SAME selectors deterministically.
        results: dict[str, list[GuitarShop]] = {CITIES[0].name: first_shops}
        for city in CITIES[1:]:
            print(f'=== rendering {city.name} (replay) ===', flush=True)
            results[city.name] = extract_shops(await render_city(city, cfg), selectors)

        print('\n=== results (teleport drives the city) ===', flush=True)
        for city in CITIES:
            shops = results[city.name]
            (out_dir / f'{city.name.lower().replace(" ", "_")}.json').write_text(
                json.dumps([s.model_dump() for s in shops], indent=2), encoding='utf-8'
            )
            top = shops[0] if shops else None
            print(
                f'  {city.name:12s}: {len(shops):2d} shops' + (f'  e.g. {top.name!r} ({top.rating})' if top else ''),
                flush=True,
            )
        print(f'\n  selectors + per-city JSON -> {out_dir}', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
