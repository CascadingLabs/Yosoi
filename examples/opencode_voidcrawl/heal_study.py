"""Study: when a selector breaks, can a 0-shot LLM heal it from the AX outline?

The verify/extraction signal tells us a field broke (ratings go None). We then hand
OpenCode *only* the compact accessibility-tree outline of one card — far cheaper than
HTML — and ask, 0-shot, for the AX role + name that locates the field. Re-extract with
the healed selector and measure recovery. One browse; all break cells run in-memory on
the captured AX nodes, so the only variable is the selector.

Cells per break: broken-count -> 0-shot-healed-count vs baseline. Verdict: HEALED /
partial / no-heal. This maps the "replay-OK vs needs-LLM, and is 0-shot enough" frontier.

    uv run python examples/opencode_voidcrawl/heal_study.py   # needs opencode auth + voidcrawl 0.3.2
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))  # examples/ — for opencode_server

import maps_teleport  # noqa: F401  registers the 'rating' coercer on import
from maps_teleport import CITIES, build_plan
from opencode_server import ensure_opencode_server
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from replay_runtime import execute_plan
from voidcrawl import BrowserConfig, BrowserSession

from yosoi.core.fetcher.dom.ax import descendants, extract_records, is_ignored, value_of
from yosoi.integrations.opencode import OpenCodeModel
from yosoi.models.replay import FieldSelectors, SelectorEntry
from yosoi.types.registry import _registry

_CARD = 'article'
_GOOD = SelectorEntry(type='role', role='image', name='stars')
_BREAKS: dict[str, SelectorEntry] = {
    'wrong_name': SelectorEntry(type='role', role='image', name='constellation'),  # no match -> None
    'wrong_role': SelectorEntry(type='role', role='button', name='stars'),  # wrong role
    'too_generic': SelectorEntry(type='role', role='image'),  # first image = the photo, not the rating
}
_FIELD_DESC = "the place's numeric star rating, shown like '4.4 stars 109 Reviews'"


class HealedSelector(BaseModel):
    """0-shot LLM output: how to locate the field within a card via the AX tree."""

    role: str = Field(description="AX role of the node holding the value, e.g. 'image'")
    name_contains: str | None = Field(
        default=None, description="accessible-name substring to disambiguate, e.g. 'stars'"
    )


def _outline_first_card(nodes: list[dict[str, Any]]) -> str:
    """Render the first non-ad card's subtree as `role "name"` lines (the LLM's input)."""
    by_id = {n['nodeId']: n for n in nodes if 'nodeId' in n}
    for node in nodes:
        if is_ignored(node) or value_of(node, 'role') != _CARD:
            continue
        name = value_of(node, 'name').strip()
        if not name or name.startswith('Ad ·'):
            continue
        lines = [f'{_CARD} "{name}"']
        for d in descendants(node, by_id):
            role, dn = value_of(d, 'role'), value_of(d, 'name').strip()
            if role and dn:
                lines.append(f'  {role} "{dn[:48]}"')
        return '\n'.join(lines[:40])
    return ''


def _ratings(nodes: list[dict[str, Any]], sel: SelectorEntry) -> list[float | None]:
    """Extract + coerce the rating for every card using `sel`."""
    recs = extract_records(
        nodes, card_role=_CARD, fields={'rating': FieldSelectors(primary=sel)}, skip_name_prefixes=('Ad ·',)
    )
    coerce = _registry['rating']
    out: list[float | None] = []
    for r in recs:
        raw = r['rating']
        try:
            v = coerce(raw, {'as_float': True, 'scale': 5}) if raw else None
        except (ValueError, TypeError):
            v = None
        out.append(float(v) if isinstance(v, (int, float)) else None)
    return out


async def _llm_heal(model: OpenCodeModel, outline: str) -> SelectorEntry:
    """0-shot: AX outline of one card -> repaired role+name selector."""
    agent: Agent[None, HealedSelector] = Agent(
        model,
        output_type=HealedSelector,
        system_prompt=(
            'You repair a broken web-extraction selector. Given an accessibility-tree outline of ONE '
            'result card as `role "name"` lines, return the AX role and an optional accessible-name '
            'substring that uniquely locates the requested field within a card. Prefer the most '
            'specific role; use name_contains to disambiguate when several nodes share a role.'
        ),
    )
    result = await agent.run(f'Field to locate: {_FIELD_DESC}\n\nCard outline:\n{outline}')
    h = result.output
    return SelectorEntry(type='role', role=h.role, name=h.name_contains)


async def main() -> None:
    cfg = BrowserConfig(headless=True, stealth=True, no_sandbox=True)
    async with ensure_opencode_server():
        model = OpenCodeModel(
            provider_id=os.getenv('OC_PROVIDER', 'openai'),
            model_id=os.getenv('OC_MODEL', 'gpt-5.3-codex'),
        )
        async with BrowserSession(cfg) as browser:
            page = await browser.new_page('about:blank')
            await execute_plan(build_plan(CITIES[0]), page)
            nodes = await page.get_full_ax_tree()

        outline = _outline_first_card(nodes)
        base = _ratings(nodes, _GOOD)
        base_ok = sum(x is not None for x in base)
        n = len(base)
        print(f'baseline (good selector): {base_ok}/{n} ratings extracted', flush=True)
        print(f'\ncard AX outline given to the LLM (0-shot):\n{outline[:360]}\n', flush=True)

        for label, broken in _BREAKS.items():
            broke_ok = sum(x is not None for x in _ratings(nodes, broken))
            healed_sel = await _llm_heal(model, outline)
            healed_ok = sum(x is not None for x in _ratings(nodes, healed_sel))
            verdict = (
                'HEALED' if healed_ok >= max(1, base_ok) * 0.9 else ('partial' if healed_ok > broke_ok else 'no-heal')
            )
            print(
                f'  break={label:12s} broken={broke_ok:2d}/{n}  ->  0-shot heal -> {healed_ok:2d}/{n}  [{verdict}]'
                f'  (LLM said role={healed_sel.role!r} name={healed_sel.name!r})',
                flush=True,
            )


if __name__ == '__main__':
    asyncio.run(main())
