"""Capture selectors / acts from an agent browse and persist them for replay.

This is the bridge from "an LLM agent clicked around" to Yosoi's "discover once,
scrape forever": we distil the agent's *successful* voidcrawl tool calls into an
ordered recipe of acts + selectors, and save it per-domain — the same record-what-
worked / replay-it idea as A3Node (yosoi/storage/a3node.py, CAS-13).

Loosely follows two tickets (not modified here):

  * CAS-27 — AX-tree as a SelectorLevel. Yosoi's SelectorEntry.type is currently
    Literal['css','xpath','regex','jsonld'] with a single `value`. The agent drives
    pages by role+name (click_by_role), so we add a 'role' selector type carrying
    (role, name, nth). Folding in = extend that Literal + add role/nth fields.
  * CAS-13 — A3Node (Assess/Act/Assert) replay. A3Node acts are {kind, cycles}
    stability triggers; browse acts are navigation/interaction. `to_a3node_acts()`
    shows the promotion path onto the existing schema.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

# voidcrawl MCP tools, namespaced by OpenCode as "voidcrawl_<tool>".
_PREFIX = 'voidcrawl_'


@dataclass
class Selector:
    """A selector the agent actually used. Shaped to match yosoi SelectorEntry + AX."""

    type: Literal['css', 'xpath', 'role']
    value: str  # css/xpath expression, or the accessible *name* when type=='role'
    role: str | None = None  # ARIA role, only when type=='role'
    nth: int | None = None


@dataclass
class Act:
    """One ordered, successful step of the browse."""

    kind: Literal['navigate', 'click', 'type', 'wait']
    selector: Selector | None = None
    url: str | None = None
    text: str | None = None


@dataclass
class BrowseRecipe:
    """An ordered, replayable recipe distilled from one browse. Saved per-domain."""

    domain: str
    start_url: str
    acts: list[Act] = field(default_factory=list)
    selectors: list[Selector] = field(default_factory=list)
    model: str = ''
    discovered_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def save(self, storage_dir: str | Path = '.yosoi/browse_recipes') -> Path:
        d = Path(storage_dir)
        d.mkdir(parents=True, exist_ok=True)
        path = d / f'recipe_{self.domain}.json'
        path.write_text(json.dumps(_clean(asdict(self)), indent=2), encoding='utf-8')
        return path

    def to_a3node_acts(self) -> list[dict[str, Any]]:
        """Promotion stub: collapse interaction acts onto A3Node's {kind, cycles}.

        A3Node replay is stability-oriented; here we just show the recipe is
        reducible to that shape (consecutive same-kind acts -> cycles).
        """
        out: list[dict[str, Any]] = []
        for a in self.acts:
            if out and out[-1]['kind'] == a.kind:
                out[-1]['cycles'] += 1
            else:
                out.append({'kind': a.kind, 'cycles': 1})
        return out


def _clean(obj: Any) -> Any:
    """Drop None fields so the saved JSON stays readable."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj


def acts_from_tool_parts(parts: list[dict[str, Any]], start_url: str) -> BrowseRecipe:
    """Distil the agent's *completed* voidcrawl tool calls into a recipe.

    Mirrors A3Node's "save what worked": errored tool calls are skipped, so a
    wrong click_by_role that 404s in the AX tree never enters the recipe — only
    the corrected one does. Session lifecycle and read-only perceive tools
    (session_open/close, ax_tree, title, eval_js) are not persisted as acts.
    """
    domain = urlparse(start_url).netloc or 'unknown'
    recipe = BrowseRecipe(domain=domain, start_url=start_url)
    for p in parts:
        if p.get('type') != 'tool':
            continue
        state = p.get('state') or {}
        if state.get('status') != 'completed':
            continue  # only persist acts that actually succeeded
        tool = p.get('tool', '')
        if not tool.startswith(_PREFIX):
            continue
        act = _act_for(tool[len(_PREFIX) :], state.get('input') or {})
        if act is None:
            continue
        recipe.acts.append(act)
        if act.selector is not None:
            recipe.selectors.append(act.selector)
    return recipe


def _act_for(name: str, inp: dict[str, Any]) -> Act | None:
    """Map a single voidcrawl tool name + input onto an Act, or None to skip."""
    if name in ('session_navigate', 'fetch'):
        return Act(kind='navigate', url=inp.get('url'))
    if name == 'click_by_role':
        sel = Selector(type='role', value=inp.get('name', ''), role=inp.get('role'), nth=inp.get('nth'))
        return Act(kind='click', selector=sel)
    if name == 'click':
        return Act(kind='click', selector=Selector(type='css', value=inp.get('selector', '')))
    if name == 'click_visual_coords':
        # No durable selector — record a positional click so replay stays honest.
        return Act(kind='click', selector=Selector(type='css', value=f'@coords({inp.get("x")},{inp.get("y")})'))
    if name == 'type_text':
        css_sel = inp.get('selector')
        return Act(
            kind='type',
            selector=Selector(type='css', value=str(css_sel)) if css_sel else None,
            text=inp.get('text'),
        )
    if name == 'wait_for_network_idle':
        return Act(kind='wait')
    return None  # session_open/close, ax_tree, title, extract, eval_js, screenshot, ...
