"""Same-domain prior transfer: does a learned (outline -> selector) example help heal?

Compares COLD 0-shot heal vs PRIMED (a learned worked-example from the same site
injected as one few-shot) — across a strong and a weak heal model, with a deliberately
*vague* field description so the model can't keyword-match 'stars'. Headroom is the
point: on well-labelled Maps a strong model heals cold every time (prior adds nothing);
the prior should matter where the model is weak or the cue is vague.

One browse; all heal cells run in-memory on the captured AX nodes.

    uv run python examples/opencode_voidcrawl/transfer_study.py
"""

from __future__ import annotations

import asyncio
import os

from heal_study import HealedSelector, _outline_first_card, _ratings  # reuse browse-free helpers
from maps_teleport import CITIES, build_plan
from opencode_server import ensure_opencode_server
from pydantic_ai import Agent
from replay_runtime import execute_plan
from voidcrawl import BrowserConfig, BrowserSession

from yosoi.integrations.opencode import OpenCodeModel
from yosoi.models.replay import SelectorEntry

# Deliberately vague — no "stars"/"rating" keyword to latch onto.
_VAGUE = "the place's overall quality score (a single number out of five)"

# A learned worked-example from a PRIOR session on the same site (the transfer prior).
_PRIOR_OUTLINE = (
    'article "Some Place"\n  link "Some Place"\n  image "4.6 stars 210 Reviews"\n  StaticText "Category · 5 Main St"'
)
_PRIOR_FIELD = 'the star rating'
_PRIOR_ANSWER = "role='image', name_contains='stars'"

_STRONG = os.getenv('OC_STRONG', 'gpt-5.3-codex')
_WEAK = os.getenv('OC_WEAK', 'gpt-5.4-mini')

_SYSTEM = (
    'You repair a broken web-extraction selector. Given an accessibility-tree outline of ONE result '
    'card as `role "name"` lines, return the AX role and an optional accessible-name substring that '
    'uniquely locates the requested field within a card. Prefer the most specific role; use '
    'name_contains to disambiguate when several nodes share a role.'
)


async def _heal(model: OpenCodeModel, outline: str, *, primed: bool) -> SelectorEntry:
    prior = ''
    if primed:
        prior = (
            'Worked example from a previous page on the SAME site:\n'
            f'Field: {_PRIOR_FIELD}\nOutline:\n{_PRIOR_OUTLINE}\nCorrect selector: {_PRIOR_ANSWER}\n\n'
        )
    agent: Agent[None, HealedSelector] = Agent(model, output_type=HealedSelector, system_prompt=_SYSTEM)
    result = await agent.run(f'{prior}Now do this one.\nField to locate: {_VAGUE}\n\nCard outline:\n{outline}')
    h = result.output
    return SelectorEntry(type='role', role=h.role, name=h.name_contains)


async def main() -> None:
    cfg = BrowserConfig(headless=True, stealth=True, no_sandbox=True)
    async with ensure_opencode_server():
        async with BrowserSession(cfg) as browser:
            page = await browser.new_page('about:blank')
            await execute_plan(build_plan(CITIES[0]), page)
            nodes = await page.get_full_ax_tree()

        outline = _outline_first_card(nodes)
        n = len(_ratings(nodes, SelectorEntry(type='role', role='image', name='stars')))
        print(
            f'baseline good selector: {sum(x is not None for x in _ratings(nodes, SelectorEntry(type="role", role="image", name="stars")))}/{n}\n',
            flush=True,
        )

        for model_id in (_STRONG, _WEAK):
            model = OpenCodeModel(provider_id=os.getenv('OC_PROVIDER', 'openai'), model_id=model_id)
            for primed in (False, True):
                sel = await _heal(model, outline, primed=primed)
                ok = sum(x is not None for x in _ratings(nodes, sel))
                cond = 'primed' if primed else 'cold  '
                print(
                    f'  model={model_id:14s} {cond} -> {ok:2d}/{n} rated  (role={sel.role!r} name={sel.name!r})',
                    flush=True,
                )


if __name__ == '__main__':
    asyncio.run(main())
