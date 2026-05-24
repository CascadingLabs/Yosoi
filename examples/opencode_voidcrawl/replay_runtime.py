"""Run + verify a canonical ReplayPlan over voidcrawl, and capture one from MCP parts.

EXPERIMENTAL — lives in the example while the executor's voidcrawl-call mapping
settles; promote to the package once stable. Three pieces close the loop:

  * capture:  plan_from_tool_parts() — MCP tool-call transcript (ground truth) -> A3Nodes
  * execute:  execute_plan() — run each node, trying its selector fallback cascade
  * verify:   each node's `expect` is checked after it runs -> VerifyReport (pass rate)

Assumptions (see module-level discussion in the chat that produced this):
  - navigate settles with a fixed sleep; Maps' network never idles.
  - min_count counts the scroll node's own act.item (a schema refinement is noted).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from yosoi.models.replay import (
    A3Node,
    Act,
    Assertion,
    NodeResult,
    ReplayPlan,
    Selector,
    VerifyReport,
    click,
    css,
    navigate,
    role,
    teleport,
)

_PREFIX = 'voidcrawl_'
# Settling is event-driven, not network-based: a node waits until its `assess`
# precondition holds (the previous step settled enough to proceed), polling at
# `_SETTLE_POLL` up to `_SETTLE_TIMEOUT` — past that the node is terminal. Nodes
# with no assess fall back to a small fixed sleep.
_SETTLE_POLL = 0.4
_SETTLE_TIMEOUT = 20.0
_NO_ASSESS_SLEEP = 1.0
# A navigate needs a fixed dwell after it: an SPA like Maps resolves geolocation
# asynchronously with NO DOM signal, so "feed present" alone fires before the
# teleported location is applied. This is the deliberate small-sleep fallback for
# the case where structure can't tell us readiness; the NEXT node's `assess` still
# gates structural readiness on top.
_NAV_DWELL = 3.0


# ── capture: MCP tool parts -> A3Nodes (ground truth) ────────────────────────


def plan_from_tool_parts(tool_parts: list[dict[str, Any]], *, target: str, task: str) -> ReplayPlan:
    """Build a ReplayPlan from an MCP agent's *completed* voidcrawl tool calls.

    Mirrors the A3Node ethos: only successful calls become nodes (an errored click
    that the agent corrected never enters the plan). Read-only / lifecycle tools
    (session_open/close, ax_tree, title, extract, screenshot) are skipped.
    """
    nodes: list[A3Node] = []
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
        return click(Selector(by='visual', x=inp.get('x'), y=inp.get('y')))
    if name == 'wait_for_network_idle':
        return A3Node(act=Act(op='wait'))
    return None  # session_open/close, ax_tree, title, extract, eval_js, screenshot, ...


# ── execute + verify ─────────────────────────────────────────────────────────


async def execute_plan(plan: ReplayPlan, page: Any) -> VerifyReport:
    """Run every node in order; record whether each node's `expect` held."""
    results: list[NodeResult] = []
    for i, node in enumerate(plan.nodes):
        results.append(await run_node(i, node, page))
    return VerifyReport(results=results)


async def run_node(index: int, node: A3Node, page: Any) -> NodeResult:
    """Settle (assess) -> act (fallback cascade) -> assert (expect)."""
    op = node.act.op
    if not await _settle(node, page):
        return NodeResult(index=index, op=op, passed=False, detail='assess never held (terminal)')
    try:
        await _act(node, page)
    except (RuntimeError, OSError, ValueError) as exc:
        return NodeResult(index=index, op=op, passed=False, detail=f'act failed: {exc}')
    passed, detail = await _check(node.expect, node, page)
    return NodeResult(index=index, op=op, passed=passed, detail=detail)


async def _settle(node: A3Node, page: Any) -> bool:
    """Event-driven readiness: wait until this node's `assess` holds, else terminal.

    The network never idles on an SPA, so we gate on the structure: a node is ready
    when its precondition is satisfiable. No assess -> a small fixed-sleep fallback.
    """
    if node.assess is None:
        await asyncio.sleep(_NO_ASSESS_SLEEP)
        return True
    waited = 0.0
    while waited < _SETTLE_TIMEOUT:
        ok, _ = await _check(node.assess, node, page)
        if ok:
            return True
        await asyncio.sleep(_SETTLE_POLL)
        waited += _SETTLE_POLL
    return False


async def _act(node: A3Node, page: Any) -> None:
    act = node.act
    if act.op == 'teleport':
        await page.set_geolocation(act.lat, act.lon, 50.0)
        if act.timezone:
            await page.set_timezone(act.timezone)
        if act.locale:
            await page.set_locale(act.locale)
    elif act.op == 'navigate':
        await page.navigate(act.url or 'about:blank')
        await asyncio.sleep(_NAV_DWELL)  # geo resolution has no DOM signal; dwell (see _NAV_DWELL)
    elif act.op == 'wait':
        await asyncio.sleep(_NO_ASSESS_SLEEP)
    elif act.op == 'scroll':
        await _run_scroll(node, page)
    elif act.op == 'click':
        await _run_click(node, page)


async def _run_scroll(node: A3Node, page: Any) -> None:
    target = node.expect.count if (node.expect and node.expect.count) else 0
    for _ in range(node.max_iters):
        count = await _count(page, node.act.feed, node.act.item or '')
        if count >= target:
            return
        await asyncio.sleep(1.3)


async def _run_click(node: A3Node, page: Any) -> None:
    """Try each target in order — durable role first, then css, then visual."""
    last: Exception | None = None
    for sel in node.act.targets:
        last = await _attempt_click(sel, page)
        if last is None:
            return
    if last is not None:
        raise last


async def _attempt_click(sel: Selector, page: Any) -> Exception | None:
    """Try one selector; return the exception on failure, or None on success."""
    try:
        if sel.by == 'role':
            await page.click_by_role(sel.role, sel.name or '', sel.nth)
        elif sel.by == 'css':
            await page.click_element(sel.value)
        elif sel.by == 'visual':
            await page.dispatch_mouse_event('click', sel.x, sel.y)
    except (RuntimeError, OSError, ValueError, AttributeError) as exc:
        return exc
    return None


async def _count(page: Any, feed: str | None, item: str) -> int:
    scope = f'document.querySelector({json.dumps(feed)})' if feed else 'document'
    raw = await page.evaluate_js(
        f'(()=>{{const s={scope};if(!s)return -1;'
        f'(s.scrollTop!==undefined)&&(s.scrollTop=s.scrollHeight);'
        f'return s.querySelectorAll({json.dumps(item)}).length;}})()'
    )
    return raw if isinstance(raw, int) else -1


async def _check(a: Assertion | None, node: A3Node, page: Any) -> tuple[bool, str | None]:
    """Evaluate an assertion (used as both `assess` precondition and `expect` post)."""
    if a is None:
        return True, None
    if a.kind == 'min_count':
        item = a.selector.value if (a.selector and a.selector.value) else node.act.item
        count = await _count(page, node.act.feed, item or '')
        ok = count >= (a.count or 0)
        return ok, None if ok else f'{count} < {a.count}'
    if a.kind == 'url_contains':
        href = str(await page.evaluate_js('location.href'))
        ok = (a.text or '') in href
        return ok, None if ok else f'{a.text!r} not in url'
    if a.kind == 'text_present':
        content = str(await page.content())
        ok = (a.text or '') in content
        return ok, None if ok else f'{a.text!r} not on page'
    if a.kind == 'selector_present' and a.selector:
        present = await page.query_selector(a.selector.value)
        return bool(present), None if present else 'selector absent'
    return True, None


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
