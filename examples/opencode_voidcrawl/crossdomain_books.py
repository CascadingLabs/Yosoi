"""Cross-domain test: does the AX machinery + 0-shot discovery port off Maps?

books.toscrape.com — a structurally different, bot-friendly, less-memorised site. We
(1) try the Maps-tuned AX extraction here, (2) cold vs primed 0-shot discovery of the
title selector (prior = the Maps card->role pattern), and (3) surface where it breaks:
the rating is a CSS class with no text (AX-blind), and book cards may have no accessible
name (Maps places do) which `extract_records` currently requires.

    uv run python examples/opencode_voidcrawl/crossdomain_books.py
"""

from __future__ import annotations

import asyncio
import os

from heal_study import HealedSelector  # reuse the 0-shot output model
from opencode_server import ensure_opencode_server
from pydantic_ai import Agent
from voidcrawl import BrowserConfig, BrowserSession

from yosoi.core.fetcher.dom.ax import descendants, extract_records, is_ignored, value_of
from yosoi.integrations.opencode import OpenCodeModel
from yosoi.models.replay import FieldSelectors, SelectorEntry, role

_URL = 'https://books.toscrape.com/'
_CARD = 'article'

# Maps-learned prior (the transfer example): a card-shaped outline -> role selector.
_PRIOR = (
    'Worked example from a previous page on a DIFFERENT site:\n'
    'Field: the place name\nOutline:\n  article "Moe\'s Guitars"\n    link "Moe\'s Guitars"\n'
    '    image "5.0 stars"\nCorrect selector: role=\'link\', name_contains=None\n\n'
)
_SYSTEM = (
    'You locate a field in a result card via the accessibility tree. Given an outline of ONE card '
    'as `role "name"` lines, return the AX role and an optional accessible-name substring that '
    'uniquely locates the requested field. Prefer the most specific role.'
)


def _outline_first_card(nodes: list[dict], card_role: str = _CARD) -> str:
    """First card's subtree as `role "name"` lines — NOT requiring a card name."""
    by_id = {n['nodeId']: n for n in nodes if 'nodeId' in n}
    for node in nodes:
        if is_ignored(node) or value_of(node, 'role') != card_role:
            continue
        lines = [f'{card_role} "{value_of(node, "name").strip()}"']
        for d in descendants(node, by_id):
            r, nm = value_of(d, 'role'), value_of(d, 'name').strip()
            if r and nm:
                lines.append(f'  {r} "{nm[:46]}"')
        return '\n'.join(lines[:24])
    return ''


def _count_field(nodes: list[dict], sel: SelectorEntry) -> int:
    recs = extract_records(nodes, card_role=_CARD, fields={'f': FieldSelectors(primary=sel)})
    return sum(1 for r in recs if r.get('f'))


async def _discover(model: OpenCodeModel, outline: str, field_desc: str, *, primed: bool) -> SelectorEntry:
    agent: Agent[None, HealedSelector] = Agent(model, output_type=HealedSelector, system_prompt=_SYSTEM)
    prompt = (_PRIOR if primed else '') + f'Now do this one.\nField to locate: {field_desc}\n\nCard outline:\n{outline}'
    h = (await agent.run(prompt)).output
    return SelectorEntry(type='role', role=h.role, name=h.name_contains)


async def main() -> None:
    cfg = BrowserConfig(headless=True, stealth=True, no_sandbox=True)
    async with ensure_opencode_server():
        async with BrowserSession(cfg) as browser:
            page = await browser.new_page('about:blank')
            await page.navigate(_URL)
            await asyncio.sleep(2)
            nodes = await page.get_full_ax_tree()
            n_articles = await page.evaluate_js("document.querySelectorAll('article.product_pod').length")

        outline = _outline_first_card(nodes)
        recs = extract_records(nodes, card_role=_CARD, fields={'title': FieldSelectors(primary=role('link'))})
        print(
            f'DOM has {n_articles} product cards; extract_records found {len(recs)} (card_role={_CARD!r})', flush=True
        )
        print(f'\nfirst card AX outline:\n{outline}\n', flush=True)
        if not recs:
            print(
                'FINDING: extract_records returned 0 — book <article> nodes have no accessible name,\n'
                '         and extract_records requires one (Maps places have names; books do not).',
                flush=True,
            )
        print(
            f'AX presence: title(link)={_count_field(nodes, role("link"))}  '
            f'price(StaticText £)={_count_field(nodes, role("StaticText", "£"))}  '
            f'rating(image)={_count_field(nodes, role("image"))}',
            flush=True,
        )

        model = OpenCodeModel(
            provider_id=os.getenv('OC_PROVIDER', 'openai'), model_id=os.getenv('OC_MODEL', 'gpt-5.3-codex')
        )
        for primed in (False, True):
            sel = await _discover(model, outline, 'the book title', primed=primed)
            cond = 'primed' if primed else 'cold  '
            print(
                f'  discover title {cond} -> role={sel.role!r} name={sel.name!r}  hits={_count_field(nodes, sel)}',
                flush=True,
            )


if __name__ == '__main__':
    asyncio.run(main())
