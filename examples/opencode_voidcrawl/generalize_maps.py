"""Experiment: does ONE Maps ReplayPlan generalize across queries — no LLM, no re-discovery?

The plan/recipe are guitar-agnostic: they key on Maps' AX structure (role="article"
cards, role="image" rating), not on the query. So the same plan + extraction should
work for any category. If it does, one plan replaces per-query LLM discovery across
all of Google Maps. We reuse maps_teleport's recipe + coercion verbatim and only vary
the query string.

    uv run python examples/opencode_voidcrawl/generalize_maps.py
"""

from __future__ import annotations

import asyncio

from maps_teleport import _EXTRACT, City, GuitarShop, _coerce  # reuse recipe + coercion verbatim
from replay_runtime import execute_plan
from voidcrawl import BrowserConfig, BrowserSession

from yosoi.core.fetcher.dom.ax import extract_records
from yosoi.models.replay import ReplayPlan, css, navigate, scroll_until, selector_present, teleport, url_contains

_FEED = 'div[role="feed"]'
_ITEM = 'a.hfpxzc'
TARGET = 20

QUERIES = ['guitar shops', 'coffee shops', 'dentists', 'hardware stores', 'tattoo parlors']
NY = City('New York', 40.7128, -74.0060, 'America/New_York')


def _maps_url(query: str) -> str:
    return f'https://www.google.com/maps/search/{query.replace(" ", "+")}+near+me/'


def plan_for(city: City, query: str) -> ReplayPlan:
    """Same structure as maps_teleport.build_plan, parametrised by query."""
    feed_present = selector_present(css(_FEED))
    url = _maps_url(query)
    read = navigate(url, expect=url_contains('/maps/'))
    read.assess = feed_present
    scroll = scroll_until(_FEED, _ITEM, TARGET)
    scroll.assess = feed_present
    return ReplayPlan(
        target='google.com/maps',
        task=query,
        source='scripted',
        nodes=[teleport(city.lat, city.lon, city.tz, city.locale), navigate(url), read, scroll],
        extract=_EXTRACT,
    )


async def run_query(city: City, query: str, cfg: BrowserConfig) -> tuple[float, list[GuitarShop]]:
    plan = plan_for(city, query)
    async with BrowserSession(cfg) as browser:
        page = await browser.new_page('about:blank')
        report = await execute_plan(plan, page)
        ax_nodes = await page.get_full_ax_tree()
        records = extract_records(
            ax_nodes,
            card_role=_EXTRACT.card_role,
            fields={f.key: f.selectors for f in _EXTRACT.fields},
            skip_name_prefixes=tuple(_EXTRACT.skip_prefixes),
        )
        return report.score, [_coerce(_EXTRACT, r) for r in records[:TARGET]]
    raise RuntimeError('BrowserSession exited without yielding a page')  # unreachable


async def main() -> None:
    cfg = BrowserConfig(headless=True, stealth=True, no_sandbox=True)
    print('Same plan + recipe, different queries (New York), no LLM:\n', flush=True)
    for query in QUERIES:
        score, shops = await run_query(NY, query, cfg)
        rated = sum(1 for s in shops if s.rating is not None)
        top = shops[0] if shops else None
        eg = f'{top.name!r} ({top.rating}★, {top.reviews})' if top else '—'
        print(
            f'  {query:16s}: {len(shops):2d} shops · verify {score:.0%} · {rated}/{len(shops)} rated · top={eg}',
            flush=True,
        )


if __name__ == '__main__':
    asyncio.run(main())
