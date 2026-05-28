"""Example-side helpers for the ReplayPlan executor.

The runtime itself (``execute_plan`` / ``run_node`` and the act/check dispatch
machinery) was promoted to ``yosoi.core.replay.runtime`` in the package, so
this module now hosts only the **example-specific** pieces:

  * ``plan_from_tool_parts`` — capture an MCP agent's voidcrawl tool-call
    transcript and turn it into a ReplayPlan (ground truth from a live agent).
  * ``open_page`` — voidcrawl ``BrowserSession`` + ``new_page`` lifecycle with
    guaranteed teardown. Used by every example here.
  * ``extract_records_dom`` — DOM-side recipe extractor used by examples that
    were authored before the unified ``ContentExtractor`` path (Phase E will
    delete the remaining ExtractRecipe consumers and this function with them).
  * ``save_plan`` / ``load_plan`` — JSON persistence for hand-authored example
    plans (the LLM-discovered cache uses ``yosoi.storage.action_plan`` instead).

``execute_plan`` and ``run_node`` are re-exported for backward compatibility
with examples that import them from here.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from voidcrawl import BrowserConfig, BrowserSession, VoidCrawlError

# Re-exported from the package — examples can still `from replay_runtime import execute_plan`.
from yosoi.core.replay.runtime import execute_plan, run_node
from yosoi.models.replay import (
    A3Node,
    Act,
    ExtractRecipe,
    Parallel,
    ReplayPlan,
    click,
    css,
    navigate,
    role,
    teleport,
    visual,
)

__all__ = [
    'execute_plan',
    'extract_records_dom',
    'load_plan',
    'open_page',
    'plan_from_tool_parts',
    'run_node',
    'save_plan',
]

_PREFIX = 'voidcrawl_'


# ── capture: MCP tool parts -> A3Nodes (ground truth) ────────────────────────


def plan_from_tool_parts(tool_parts: list[dict[str, Any]], *, target: str, task: str) -> ReplayPlan:
    """Build a ReplayPlan from an MCP agent's *completed* voidcrawl tool calls.

    Mirrors the A3Node ethos: only successful calls become nodes (an errored click
    that the agent corrected never enters the plan). Read-only / lifecycle tools
    (session_open/close, ax_tree, title, extract, screenshot) are skipped.
    """
    nodes: list[A3Node | Parallel] = []
    for part in tool_parts:
        if part.get('type') != 'tool':
            continue
        state = part.get('state') or {}
        if state.get('status') != 'completed':
            continue
        tool = part.get('tool', '')
        if not tool.startswith(_PREFIX):
            continue
        node = _node_for(tool[len(_PREFIX) :], state.get('input') or {})
        if node is not None:
            nodes.append(node)
    return ReplayPlan(target=target, task=task, nodes=nodes, source='mcp-agent')


def _node_for(name: str, inp: dict[str, Any]) -> A3Node | None:
    if name in ('session_navigate', 'fetch'):
        return navigate(inp.get('url', ''))
    if name == 'teleport':
        return teleport(inp['latitude'], inp['longitude'], inp.get('timezone'), inp.get('locale'))
    if name == 'click_by_role':
        return click(role(inp.get('role', ''), inp.get('name', ''), inp.get('nth') or 0))
    if name == 'click':
        return click(css(inp.get('selector', '')))
    if name == 'click_visual_coords':
        return click(visual(inp['x'], inp['y']))
    if name == 'wait_for_network_idle':
        return A3Node(act=Act(op='wait'))
    return None  # session_open/close, ax_tree, title, extract, eval_js, screenshot, ...


# ── DOM-side extraction (legacy ExtractRecipe consumer — will be deleted in Phase E) ─


async def extract_records_dom(page: Any, recipe: ExtractRecipe) -> list[dict[str, str | None]]:
    """Resolve an ExtractRecipe against the DOM — dispatch on each selector's TYPE.

    Each entry in a field's selector cascade tells the executor BOTH where to
    look and how to read:

      * ``css`` / ``xpath``  — scoped query inside the card, return innerText.
      * ``attr`` (value=name) — read ``card.getAttribute(value)``.
      * ``global_id`` (value=template, identity=attr) — interpolate the card's
        identity attr into the template's ``{id}`` slot, then look up by
        ``document.getElementById(resolved)``.

    Dispatch is keyed off SelectorEntry.type, which is exactly what the LLM
    discovery agent emits via the unified ``to_selector_model`` schema.
    """
    if recipe.card is None:
        raise ValueError('extract_records_dom requires recipe.card (a SelectorEntry); for AX, use extract_records')
    field_payload = [
        {
            'key': f.key,
            'selectors': [
                {'type': e.type, 'value': e.value, 'identity': e.identity}
                for _, e in f.selectors.as_entries()
                if e and e.type in ('css', 'xpath', 'attr', 'global_id')
            ],
        }
        for f in recipe.fields
    ]
    payload = {
        'card': recipe.card.value,
        'fields': field_payload,
        'skip_prefixes': list(recipe.skip_prefixes),
    }
    raw = await page.evaluate_js(_EXTRACT_RECORDS_JS.replace('__PAYLOAD__', json.dumps(payload)))
    return raw if isinstance(raw, list) else []


_EXTRACT_RECORDS_JS = """((cfg) => {
  const cards = document.querySelectorAll(cfg.card);
  const skip = cfg.skip_prefixes || [];
  const out = [];
  const text = (el) => el ? (el.innerText || '').trim() || null : null;
  const readOne = (card, sel) => {
    if (sel.type === 'attr') return card.getAttribute(sel.value);
    if (sel.type === 'global_id') {
      const key = card.getAttribute(sel.identity || 'id');
      if (!key) return null;
      const resolved = sel.value.replace('{id}', key);
      return text(document.getElementById(resolved));
    }
    const el = card.querySelector(sel.value);
    return text(el);
  };
  for (const card of cards) {
    const rec = {};
    let dropped = false;
    for (const f of cfg.fields) {
      let value = null;
      for (const sel of f.selectors) {
        value = readOne(card, sel);
        if (value) break;
      }
      rec[f.key] = value;
    }
    if (cfg.fields.length && skip.length) {
      const lead = rec[cfg.fields[0].key] || '';
      if (skip.some(p => lead.startsWith(p))) dropped = true;
    }
    if (!dropped) out.push(rec);
  }
  return out;
})(__PAYLOAD__)"""


# ── lifecycle (guaranteed teardown — no leaked tabs/sessions) ────────────────


@contextlib.asynccontextmanager
async def open_page(cfg: BrowserConfig, url: str = 'about:blank') -> AsyncIterator[Any]:
    """Yield a fresh page (tab), closing the tab AND the session on every path."""
    async with BrowserSession(cfg) as browser:
        page = await browser.new_page(url)
        try:
            yield page
        finally:
            with contextlib.suppress(VoidCrawlError, RuntimeError, OSError):
                await page.close()


# ── persistence (canonical ReplayPlan JSON, per target) ──────────────────────


def _plan_path(target: str, storage_dir: str | Path) -> Path:
    slug = target.replace('/', '_').replace(':', '')
    return Path(storage_dir) / f'plan_{slug}.json'


def save_plan(plan: ReplayPlan, storage_dir: str | Path) -> Path:
    """Persist a ReplayPlan as JSON, per target."""
    Path(storage_dir).mkdir(parents=True, exist_ok=True)
    path = _plan_path(plan.target, storage_dir)
    path.write_text(plan.model_dump_json(indent=2), encoding='utf-8')
    return path


def load_plan(target: str, storage_dir: str | Path) -> ReplayPlan | None:
    """Load a persisted ReplayPlan for a target, or None."""
    path = _plan_path(target, storage_dir)
    return ReplayPlan.model_validate_json(path.read_text(encoding='utf-8')) if path.exists() else None
