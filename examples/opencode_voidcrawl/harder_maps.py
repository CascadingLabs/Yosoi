"""Harder Maps experiment: click into detail + contract-size generalization (no LLM).

Tests two things the earlier runs didn't:
  1. The action cascade LIVE — clicking a result open via role('link', name) -> css
     fallback (our executor's click path had never run live).
  2. Contract generalization — the SAME machinery extracts a small 2-field contract
     from the card, then a large 6-field contract from the detail panel. A contract is
     just data (typed FieldSelectors); the executor / extractor / coercion don't change.

Phase 1: card -> {name, rating}. Phase 2: click into detail -> {name, rating, reviews,
address, phone, website}. Detail fields are role+name nodes ("Address: …", "Phone: …",
"Website: …"); a tiny `after_label` coercion strips the label, rating/reviews reuse the
earlier coercers.

    uv run python examples/opencode_voidcrawl/harder_maps.py
"""

from __future__ import annotations

import asyncio
from typing import Any

from maps_teleport import City  # importing also registers the 'rating' + 'reviews' coercers
from replay_runtime import execute_plan
from voidcrawl import BrowserConfig, BrowserSession

from yosoi.core.fetcher.dom.ax import extract_one, extract_records
from yosoi.models.replay import (
    A3Node,
    Act,
    FieldSelectors,
    ReplayPlan,
    click,
    css,
    navigate,
    role,
    scroll_until,
    selector_present,
    teleport,
    url_contains,
)
from yosoi.types.registry import CoercionConfig, _registry, register_coercion

_FEED = 'div[role="feed"]'
_ITEM = 'a.hfpxzc'
TARGET = 20
NY = City('New York', 40.7128, -74.0060, 'America/New_York')
QUERY = 'guitar shops'
URL = f'https://www.google.com/maps/search/{QUERY.replace(" ", "+")}+near+me/'


@register_coercion('after_label', description='Strip a "Label: value" prefix down to the value')
def AfterLabel(v: object, config: CoercionConfig, source_url: str | None = None) -> str:
    """'Address: 726 Lafayette Ave' -> '726 Lafayette Ave'. Parsing lives in the TYPE."""
    s = str(v)
    return s.split(':', 1)[1].strip() if ':' in s else s.strip()


# Small contract: rating off the card (name is returned by extract_records automatically).
_SMALL = {'rating': FieldSelectors(primary=role('image', 'stars'))}

# Large contract: rating/reviews + address/phone/website off the detail panel.
_LARGE_SELECTORS = {
    'rating': FieldSelectors(primary=role('image', 'stars')),
    'reviews': FieldSelectors(primary=role('image', 'stars')),
    'address': FieldSelectors(primary=role('button', 'Address:')),
    'phone': FieldSelectors(primary=role('button', 'Phone:')),
    'website': FieldSelectors(primary=role('link', 'Website:')),
}
_LARGE_TYPES: dict[str, tuple[str, dict[str, object]]] = {
    'rating': ('rating', {'as_float': True, 'scale': 5}),
    'reviews': ('reviews', {}),
    'address': ('after_label', {}),
    'phone': ('after_label', {}),
    'website': ('after_label', {}),
}


def _coerce(raw: dict[str, str | None], types: dict[str, tuple[str, dict[str, object]]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, (type_name, cfg) in types.items():
        value = raw.get(key)
        coercer = _registry.get(type_name)
        try:
            out[key] = coercer(value, dict(cfg)) if (value and coercer) else None
        except (ValueError, TypeError):
            out[key] = None
    return out


async def main() -> None:
    cfg = BrowserConfig(headless=True, stealth=True, no_sandbox=True)
    feed = selector_present(css(_FEED))
    detail = selector_present(css('button[aria-label^="Address:"]'))

    async with BrowserSession(cfg) as browser:
        page = await browser.new_page('about:blank')

        # Phase 1 — load results, SMALL contract off the card.
        read = navigate(URL, expect=url_contains('/maps/'))
        read.assess = feed
        scroll = scroll_until(_FEED, _ITEM, TARGET)
        scroll.assess = feed
        p1 = ReplayPlan(
            target='google.com/maps',
            task=QUERY,
            source='scripted',
            nodes=[teleport(NY.lat, NY.lon, NY.tz, NY.locale), navigate(URL), read, scroll],
        )
        r1 = await execute_plan(p1, page)
        cards = extract_records(
            await page.get_full_ax_tree(), card_role='article', fields=_SMALL, skip_name_prefixes=('Ad ·',)
        )
        first = cards[0]
        print(
            f'phase 1  verify {r1.score:.0%}  | SMALL contract (card): '
            f'name={first["name"]!r} rating_raw={first["rating"]!r}',
            flush=True,
        )

        # Phase 2 — click that result (role -> css cascade), wait for detail, LARGE contract.
        open_detail = click(role('link', first['name']), css(_ITEM))  # cascade: durable role first
        open_detail.assess = feed
        wait_detail = A3Node(act=Act(op='wait'), assess=detail, expect=detail)
        p2 = ReplayPlan(
            target='google.com/maps:detail', task=QUERY, source='scripted', nodes=[open_detail, wait_detail]
        )
        r2 = await execute_plan(p2, page)

        rec = _coerce(extract_one(await page.get_full_ax_tree(), fields=_LARGE_SELECTORS), _LARGE_TYPES)
        rec['name'] = first['name']
        print(f'phase 2  verify {r2.score:.0%}  | LARGE contract (detail, via role->css click):', flush=True)
        for key in ('name', 'rating', 'reviews', 'address', 'phone', 'website'):
            print(f'    {key:8s}: {rec.get(key)}', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
