"""Run + verify a canonical ReplayPlan over voidcrawl, and capture one from MCP parts.

EXPERIMENTAL — lives in the example while the executor's voidcrawl-call mapping
settles; promote to the package once stable. Three pieces close the loop:

  * capture:  plan_from_tool_parts() — MCP tool-call transcript (ground truth) -> A3Nodes
  * execute:  execute_plan() — run each node, trying its selector fallback cascade
  * verify:   each node's `expect` is checked after it runs -> VerifyReport (pass rate)

Settling model:
  - Readiness is assertion-driven: a node waits for its `assess` precondition to hold
    (the network never idles on an SPA, so we gate on structure, not time). No assess
    means proceed immediately — no arbitrary sleep.
  - The one fixed wait is an explicit per-node `dwell`, for the rare no-DOM-signal case
    (Maps geolocation; SPA hydration that wires a handler with no observable marker).
  - execute_plan is fail_fast by default: a linear plan can't recover from a missed
    precondition, so it stops at the first failure rather than burning settle timeouts.
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
    Parallel,
    ReplayPlan,
    SelectorEntry,
    VerifyReport,
    click,
    css,
    navigate,
    role,
    teleport,
    visual,
)

_PREFIX = 'voidcrawl_'
# Settling is purely assertion-driven: a node waits until its `assess` precondition
# holds (polled at `_SETTLE_POLL` up to `_SETTLE_TIMEOUT`, then terminal). A node with
# NO assess proceeds immediately — no arbitrary sleep. The one fixed wait is an
# explicit per-node `dwell`, for the rare no-DOM-signal case (e.g. Maps geolocation).
_SETTLE_POLL = 0.3
_SETTLE_TIMEOUT = 8.0  # a precondition that isn't met in ~8s is treated as terminal (fail fast)


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


# ── execute + verify ─────────────────────────────────────────────────────────


async def execute_plan(plan: ReplayPlan, page: Any, *, fail_fast: bool = True) -> VerifyReport:
    """Run the plan in order. A3Nodes run sequentially; a Parallel group fans out.

    fail_fast (default): stop at the first failed node — a linear plan can't recover
    from a missed precondition, so plowing on just burns settle timeouts. The remaining
    nodes are reported as skipped so the report still shows where it stopped.
    """
    results: list[NodeResult] = []
    i = 0
    stopped = False
    for item in plan.nodes:
        count = len(item.nodes) if isinstance(item, Parallel) else 1
        if stopped:
            results.extend(
                NodeResult(index=i + k, op='skipped', passed=False, detail='skipped (prior node failed)')
                for k in range(count)
            )
            i += count
            continue
        if isinstance(item, Parallel):
            if not await _settle_assert(item.assess, page):  # group precondition, checked once
                results.append(NodeResult(index=i, op='parallel', passed=False, detail='group assess never held'))
                stopped = fail_fast
                i += 1
                continue
            fanned = await asyncio.gather(*(run_node(i + k, child, page) for k, child in enumerate(item.nodes)))
            results.extend(fanned)
            i += count
        else:
            result = await run_node(i, item, page)
            results.append(result)
            stopped = fail_fast and not result.passed
            i += 1
    return VerifyReport(results=results)


async def run_node(index: int, node: A3Node, page: Any) -> NodeResult:
    """Settle (assess) -> act (fallback cascade) -> [dwell] -> assert (expect)."""
    op = node.act.op
    if not await _settle_assert(node.assess, page):
        return NodeResult(index=index, op=op, passed=False, detail='assess never held (terminal)')
    try:
        await _act(node, page)
    except (RuntimeError, OSError, ValueError) as exc:
        return NodeResult(index=index, op=op, passed=False, detail=f'act failed: {exc}')
    if node.dwell:  # explicit no-DOM-signal wait (e.g. geo); 0 by default
        await asyncio.sleep(node.dwell)
    passed, detail = await _check(node.expect, node, page)
    return NodeResult(index=index, op=op, passed=passed, detail=detail)


async def _settle_assert(assertion: Assertion | None, page: Any) -> bool:
    """Assertion-driven readiness: poll until `assertion` holds, else terminal.

    No assertion -> ready immediately (no arbitrary sleep). The network never idles on
    an SPA, so readiness is gated on the structure (the assertion), not time.
    """
    if assertion is None:
        return True
    waited = 0.0
    while waited < _SETTLE_TIMEOUT:
        ok, _ = await _check(assertion, None, page)
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
        await page.navigate(act.url or 'about:blank')  # settling is the next step's assess (or node.dwell)
    elif act.op == 'wait':
        pass  # a pure gate: its `assess` does the waiting, the act is a no-op
    elif act.op == 'scroll':
        await _run_scroll(node, page)
    elif act.op == 'click':
        await _run_click(node, page)
    elif act.op == 'type':
        await _run_type(node, page)


async def _run_type(node: A3Node, page: Any) -> None:
    """Type into a css/xpath target. Sets value on ALL matches via the native setter +
    input/change events — robust to duplicated DOM and framework-controlled inputs
    (a plain .value assignment won't register with React/Solid)."""
    sel = next((t for t in node.act.targets if t.type in ('css', 'xpath')), None)
    if sel is None:
        return
    text = node.act.text or ''
    js = (
        '(()=>{const set=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"value").set;let k=0;'
        f'document.querySelectorAll({json.dumps(sel.value)}).forEach(el=>{{set.call(el,{json.dumps(text)});'
        'el.dispatchEvent(new Event("input",{bubbles:true}));el.dispatchEvent(new Event("change",{bubbles:true}));k++;});'
        'return k;})()'
    )
    await page.evaluate_js(js)


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


async def _attempt_click(sel: SelectorEntry, page: Any) -> Exception | None:
    """Try one selector; return the exception on failure, or None on success."""
    try:
        if sel.type == 'role':
            await page.click_by_role(sel.role, sel.name or '', sel.nth)
        elif sel.type in ('css', 'xpath'):
            await page.click_element(sel.value)
        elif sel.type == 'visual':
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


async def _check(a: Assertion | None, node: A3Node | None, page: Any) -> tuple[bool, str | None]:
    """Evaluate an assertion (used as both `assess` precondition and `expect` post).

    `node` is the owning A3Node when available (for min_count's feed/item context); it
    is None when checking a Parallel group's or a poll's standalone assertion.
    """
    if a is None:
        return True, None
    if a.kind == 'min_count':
        item = a.selector.value if (a.selector and a.selector.value) else (node.act.item if node else None)
        feed = node.act.feed if node else None
        count = await _count(page, feed, item or '')
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
        present = await _selector_present(a.selector, page)
        return present, None if present else 'selector absent'
    return True, None


async def _selector_present(sel: SelectorEntry, page: Any) -> bool:
    """Presence check that honours the selector kind: role -> AX query, else css.

    css uses evaluate_js, NOT page.query_selector: the latter returns the matched
    element's text (empty -> falsy) for an <input>, so a present-but-empty field would
    read as absent. existence is `querySelector(...) !== null`.
    """
    if sel.type == 'role':
        nodes = await page.query_ax_tree(role=sel.role, name=sel.name)
        return bool(nodes)
    present = await page.evaluate_js(f'document.querySelector({json.dumps(sel.value)})!==null')
    return bool(present)


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
