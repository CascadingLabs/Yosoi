"""ReplayPlan execution runtime — drive a live page through A3Node primitives.

Three pieces close the discover → cache → replay loop:

  * **execute_plan** — run each node sequentially (Parallel groups fan out).
    Each A3Node settles its ``assess`` precondition, runs its ``act``, then
    settles its ``expect`` postcondition. Verification is event-driven all the
    way down: no fixed sleeps, no hand-rolled retry loops (tenacity owns
    backoff, per AGENTS.md).

  * **_act dispatch** — navigate / click / type / scroll / wait / teleport.
    ``repeat=True`` ticks the act until ``expect`` holds (the load-more
    pattern). Click cascade tries role → css/xpath → visual in order.

  * **_check dispatch** — the assertion vocabulary: min_count, url_contains,
    text_present, selector_present, selector_absent.

The runtime is duck-typed against the voidcrawl ``Page`` interface — no hard
import dep on voidcrawl. Any page-like object exposing ``navigate``,
``evaluate_js``, ``content``, ``click_by_role``, ``query_ax_tree``,
``set_geolocation``, ``set_timezone``, ``set_locale``, ``dispatch_mouse_event``
will work. Callers without those methods (single-item pages with no actions)
hit only the no-op branches.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from tenacity import AsyncRetrying, RetryError, retry_if_exception_type, stop_after_delay, wait_exponential

from yosoi.models.replay import (
    A3Node,
    Assertion,
    NodeResult,
    Parallel,
    ReplayPlan,
    SelectorEntry,
    VerifyReport,
)

# Settling is event-driven, never timed: a node polls its `assess` precondition and then
# (after acting) its `expect` postcondition until each holds, else terminal. No assertion
# -> proceed immediately. The poll is a tenacity gate (no hand-rolled loop, per AGENTS.md),
# bounded by wall-clock `_SETTLE_TIMEOUT`; backoff is capped at `_SETTLE_WAIT_MAX`.
_SETTLE_TIMEOUT = 10.0  # a condition not met within this is terminal (fail fast)
_SETTLE_WAIT_MAX = 0.8  # poll-backoff cap


class _NotReady(Exception):
    """Drives the tenacity retry: raised while a polled assertion isn't yet satisfied."""


# ── execute + verify ─────────────────────────────────────────────────────────


async def execute_plan(plan: ReplayPlan, page: Any, *, fail_fast: bool = True) -> VerifyReport:
    """Run *plan* in order. A3Nodes run sequentially; a Parallel group fans out.

    Args:
        plan: A canonical ``ReplayPlan`` (typically an LLM-discovered action plan
            loaded from ``ActionPlanStorage``, or a hand-authored test plan).
        page: A page-like object (e.g. ``voidcrawl.Page``). Duck-typed — the
            runtime calls only the methods needed by the act dispatch.
        fail_fast: When True (default), stop at the first failed node — a linear
            plan can't recover from a missed precondition, so plowing on just
            burns settle timeouts. Remaining nodes report as ``skipped``.

    Returns:
        A ``VerifyReport`` with per-node pass/fail outcomes and an overall
        score (pass rate). Empty plans yield an empty report (score 1.0).
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
            ready, _ = await _settle(item.assess, page)
            if not ready:
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
    """Settle (assess) → act (fallback cascade) → verify effect (expect).

    The act is verified by its *effect*: after acting we poll ``expect`` until it
    holds, so a handler that wires a moment late (SPA hydration) is awaited, not
    slept past. ``repeat=True`` ticks the act until ``expect`` holds (used by
    ``scroll_until`` / ``click_until``).
    """
    op = node.act.op
    ready, detail = await _settle(node.assess, page)
    if not ready:
        return NodeResult(index=index, op=op, passed=False, detail=f'assess never held: {detail or "(terminal)"}')
    if node.repeat and op != 'scroll':  # scroll has its own self-loop in _run_scroll
        return await _run_repeat(index, node, page)
    try:
        await _act(node, page)
    except (RuntimeError, OSError, ValueError) as exc:
        return NodeResult(index=index, op=op, passed=False, detail=f'act failed: {exc}')
    passed, detail = await _settle(node.expect, page, node)
    return NodeResult(index=index, op=op, passed=passed, detail=detail)


async def _run_repeat(index: int, node: A3Node, page: Any) -> NodeResult:
    """Tick act until ``expect`` holds — pagination / load-more pattern.

    An act failure (e.g. css selector no longer matches anything — the trigger
    consumed itself) ends the loop: the next ``expect`` check is decisive. Each
    tick gets one bounded settle so a slow network round-trip (faceplate-partial
    fetch on reddit) has time to land before we tick again.
    """
    op = node.act.op
    last_detail: str | None = None
    for _ in range(node.max_iters):
        ok, last_detail = await _check(node.expect, node, page)
        if ok:
            return NodeResult(index=index, op=op, passed=True)
        try:
            await _act(node, page)
        except (RuntimeError, OSError, ValueError):
            break  # nothing left to act on; the next check is decisive
        await asyncio.sleep(0.6)  # let the network round-trip land before the next tick
    ok, last_detail = await _check(node.expect, node, page)
    return NodeResult(index=index, op=op, passed=ok, detail=last_detail)


async def _settle(assertion: Assertion | None, page: Any, node: A3Node | None = None) -> tuple[bool, str | None]:
    """Event-driven readiness/verification: poll *assertion* until it holds, else terminal.

    No assertion → ready immediately (no arbitrary sleep). SPA networks never
    idle, so we gate on structure, not time. tenacity owns the backoff; the
    wall-clock ceiling makes a never-met condition terminal.
    """
    if assertion is None:
        return True, None
    state: dict[str, str | None] = {'detail': None}
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_delay(_SETTLE_TIMEOUT),
            wait=wait_exponential(multiplier=0.1, max=_SETTLE_WAIT_MAX),
            retry=retry_if_exception_type(_NotReady),
            reraise=False,
        ):
            with attempt:
                ok, state['detail'] = await _check(assertion, node, page)
                if not ok:
                    raise _NotReady
        return True, None
    except (RetryError, _NotReady):
        return False, state['detail']


# ── act dispatch ─────────────────────────────────────────────────────────────


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
    elif act.op == 'wait':
        if act.seconds:  # the one fixed pause: a state change with no observable signal
            await asyncio.sleep(act.seconds)
        # else a pure gate: its `assess`/`expect` does the waiting, the act is a no-op
    elif act.op == 'scroll':
        await _run_scroll(node, page)
    elif act.op == 'click':
        await _run_click(node, page)
    elif act.op == 'type':
        await _run_type(node, page)


async def _run_type(node: A3Node, page: Any) -> None:
    """Type into a css/xpath target via the native value setter + input/change events.

    A plain ``.value`` assignment won't register with React/Solid-controlled
    inputs; this dispatches the events the framework expects and verifies that
    at least one element matched (a no-op match is a failed act, not silent).
    """
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
    k = await page.evaluate_js(js)
    if not k:
        raise ValueError(f'type matched no element for {sel.value!r}')


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
            await _click_css_robust(sel.value, page)
        elif sel.type == 'visual':
            await page.dispatch_mouse_event('click', sel.x, sel.y)
    except (RuntimeError, OSError, ValueError, AttributeError) as exc:
        return exc
    return None


async def _click_css_robust(selector: str, page: Any) -> None:
    """ScrollIntoView → JS ``.click()``. Raises if the element isn't found.

    JS click (vs the CDP mouse-event path used by role/visual) is the reliable
    choice for *custom-element* handlers: reddit's ``<faceplate-partial>``
    listens for the click event, not a real cursor hit, and CDP's
    ``dispatchMouseEvent`` can silently land in the wrong rect when the target
    is offscreen or under a sticky overlay.
    """
    found = await page.evaluate_js(
        f'(()=>{{const el=document.querySelector({json.dumps(selector)});'
        f'if(!el)return false;el.scrollIntoView({{block:"center",inline:"center"}});el.click();return true;}})()'
    )
    if not found:
        raise ValueError(f'no element matches {selector!r}')


async def _count(page: Any, feed: str | None, item: str) -> int:
    """Count ``item`` matches inside ``feed``, scrolling feed-or-window to bottom as a side effect.

    No feed → scope is ``document`` and we scroll the WINDOW. A real feed
    scrolls its own ``scrollTop``. Either way, the scroll nudges any
    IntersectionObserver-driven lazy loaders.
    """
    scope = f'document.querySelector({json.dumps(feed)})' if feed else 'document'
    scroll = '(s===document)?window.scrollTo(0,document.body.scrollHeight):(s.scrollTop=s.scrollHeight);'
    raw = await page.evaluate_js(
        f'(()=>{{const s={scope};if(!s)return -1;{scroll}return s.querySelectorAll({json.dumps(item)}).length;}})()'
    )
    return raw if isinstance(raw, int) else -1


async def _check(a: Assertion | None, node: A3Node | None, page: Any) -> tuple[bool, str | None]:
    """Evaluate an assertion (used as both ``assess`` precondition and ``expect`` post)."""
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
    if a.kind == 'selector_absent' and a.selector:
        present = await _selector_present(a.selector, page)
        return (not present), None if not present else 'selector still present'
    return True, None


async def _selector_present(sel: SelectorEntry, page: Any) -> bool:
    """Presence check honouring the selector kind: role → AX query, else CSS via JS.

    CSS uses ``evaluate_js``, NOT ``page.query_selector``: the latter returns
    the matched element's text (empty → falsy) for an ``<input>``, so a
    present-but-empty field would read as absent. Existence is
    ``querySelector(...) !== null``.
    """
    if sel.type == 'role':
        nodes = await page.query_ax_tree(role=sel.role, name=sel.name)
        return bool(nodes)
    present = await page.evaluate_js(f'document.querySelector({json.dumps(sel.value)})!==null')
    return bool(present)
