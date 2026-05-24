"""Google Maps geolocation-teleport scrape — A3Node-replayable, AX-tree selectors.

The use case: the *same* query ("guitar shops near me") in three cities, where the
city is set purely by **teleporting** the browser's geolocation (CAS-45).

The whole flow is captured as an **A3Node** (CAS-13) — the locked-in action sequence
(teleport → navigate x2 → scroll the feed to >= TARGET) plus an **accessibility-tree
extraction recipe** (CAS-27: card role="article", rating from a descendant
role="image" named "4.4 stars 2,980 Reviews"). The first run locks it in and saves it
per-domain; every run after that **replays it deterministically** over the PyO3
binding — no agent, no LLM, no re-discovery. A failed `assert_min` on the scroll act
means the page changed and the node should be re-discovered.

Where the actions come from: hand-authored here, but the same A3Node acts can be
captured from the MCP agent's tool calls (see recipe.py / browse_and_save.py) — the
agent discovers once, A3Node locks it in, PyO3 replays forever.

Run twice to see it: first run "locks in", second run "replays (replay_count=1)".
    uv run python examples/opencode_voidcrawl/maps_teleport.py   # needs voidcrawl>=0.3.2 + Chromium
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from a3node import A3AssertError, A3Node, Act, ExtractRecipe, extract, replay_acts
from pydantic import BaseModel
from voidcrawl import BrowserConfig, BrowserSession

HERE = Path(__file__).parent
A3_DIR = HERE / '.yosoi' / 'a3nodes'
OUT_DIR = HERE / '.yosoi' / 'maps'
DOMAIN = 'google.com/maps'

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


def maps_a3node() -> A3Node:
    """The locked-in Maps flow: teleport → navigate x2 → scroll → AX extract.

    Hand-authored here, but shaped exactly like what `recipe.acts_from_tool_parts`
    produces from an MCP agent's tool calls — the discover-once-then-lock-in path.
    """
    return A3Node(
        domain=DOMAIN,
        task='guitar shops near me',
        acts=[
            Act(op='teleport'),  # geo supplied per city at replay
            Act(op='navigate', url=MAPS_URL),  # prime: Maps resolves location on first load
            Act(op='navigate', url=MAPS_URL),  # read: applies the teleported location
            Act(op='scroll', feed='div[role="feed"]', item='a.hfpxzc', target=TARGET, assert_min=12),
        ],
        extract=ExtractRecipe(
            card_role='article',
            fields=[
                {'key': 'rating', 'role': 'image', 'pattern': r'([\d.]+)\s*stars'},
                {'key': 'reviews', 'role': 'image', 'pattern': r'stars?\s+([\d,]+)\s*Reviews'},
                {
                    'key': 'address',
                    'role': 'StaticText',
                    'pattern': r'\d{1,6}\s+\w.*\b(?:St|Ave|Avenue|Blvd|Rd|Road|Dr|Drive|Ln|Lane|Way|Pl|Pkwy|Hwy|Street|Ct|Sq|Fl)\b',
                },
            ],
            skip_prefixes=['Ad ·'],
        ),
    )


def _to_shop(rec: dict[str, str | None]) -> GuitarShop:
    r, rv = rec.get('rating'), rec.get('reviews')
    rating = float(r) if r else None
    reviews = int(rv.replace(',', '')) if rv else None
    return GuitarShop(name=rec.get('name') or '', rating=rating, reviews=reviews, address=rec.get('address'))


async def scrape_city(node: A3Node, city: City, cfg: BrowserConfig) -> list[GuitarShop]:
    """Replay the A3Node in a FRESH session for *city* (teleport needs a clean session)."""
    async with BrowserSession(cfg) as browser:
        page = await browser.new_page('about:blank')  # blank first so teleport applies pre-nav
        await replay_acts(node, page, geo=(city.lat, city.lon, city.tz, city.locale))
        ax_nodes = await page.get_full_ax_tree()
        return [_to_shop(r) for r in extract(node, ax_nodes)[:TARGET]]
    raise RuntimeError('BrowserSession exited without yielding a page')  # unreachable


async def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cfg = BrowserConfig(headless=True, stealth=True, no_sandbox=True)

    node = A3Node.load(DOMAIN, A3_DIR)
    first_run = node is None
    if node is None:
        node = maps_a3node()
        print(f'no A3Node for {DOMAIN} — locking in {len(node.acts)} acts (first run)', flush=True)
    else:
        print(
            f'replaying A3Node for {DOMAIN} (replay_count={node.replay_count}, locked in {node.discovered_at[:19]})',
            flush=True,
        )

    results: dict[str, list[GuitarShop]] = {}
    try:
        for city in CITIES:
            print(f'=== {city.name} (teleport {city.lat},{city.lon}) ===', flush=True)
            results[city.name] = await scrape_city(node, city, cfg)
            print(f'  -> {len(results[city.name])} shops', flush=True)
    except A3AssertError as e:
        print(f'  A3 assert failed: {e}', flush=True)
        print('  (in a full system this triggers MCP re-discovery of the acts)', flush=True)
        raise

    # Lock-in / replay bookkeeping (mirrors yosoi A3NodeStorage.replay_count).
    if not first_run:
        node.replay_count += 1
    node.last_replayed_at = datetime.now().isoformat()
    node.save(A3_DIR)

    print('\n=== results (teleport drives the city; extracted via AX role+name) ===', flush=True)
    for city in CITIES:
        shops = results[city.name]
        (OUT_DIR / f'{city.name.lower().replace(" ", "_")}.json').write_text(
            json.dumps([s.model_dump() for s in shops], indent=2), encoding='utf-8'
        )
        top = shops[0] if shops else None
        line = f'  {city.name:12s}: {len(shops):2d} shops'
        if top:
            line += f'  e.g. {top.name!r} ({top.rating}★, {top.reviews} reviews) {top.address or ""}'
        print(line, flush=True)

    verb = 'locked in & saved' if first_run else f'replayed (replay_count={node.replay_count})'
    print(f'\n  A3Node {verb} -> {A3Node._path(DOMAIN, A3_DIR)}', flush=True)
    print(f'  per-city JSON -> {OUT_DIR}', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
