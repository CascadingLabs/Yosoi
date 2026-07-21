"""Fail-fast runtime for executing persisted replay plans."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from yosoi.core.replay._captcha_js import CAPTURE_JS, inject_token_js
from yosoi.models.replay import (
    ActKind,
    AssertKind,
    NodeKind,
    ReactionState,
    ReplayAct,
    ReplayCondition,
    ReplayPlan,
    TeleportSpec,
    TreeNode,
    VerifyReport,
)
from yosoi.models.results import JsOutputs
from yosoi.models.selectors import SelectorEntry
from yosoi.utils.retry import get_async_retryer


class ReplayExecutionError(RuntimeError):
    """Raised when a replay plan cannot be executed safely."""

    def __init__(self, message: str, report: VerifyReport | None = None) -> None:
        """Initialise the error with the verification report available so far."""
        super().__init__(message)
        self.report = report or VerifyReport(failed=1, failures=[message])


@dataclass
class ReplayResult:
    """Result of executing a replay plan, including any captured eval outputs.

    Delegates ``score``, ``passed``, ``failed``, and ``failures`` to the
    inner ``report`` so callers that previously received a ``VerifyReport``
    directly continue to work without changes.
    """

    report: VerifyReport = field(default_factory=VerifyReport)
    extracted_actions: JsOutputs = field(default_factory=dict)
    # Behavior-tree walk state (W1): REACTION nodes currently in scope, innermost last.
    active_reactions: list[TreeNode] = field(default_factory=list)
    # Guard ids currently inside their own recovery tick — suppresses re-entrant
    # firing (the recovery subtree ticks while its trigger may still hold).
    _recovering: set[str] = field(default_factory=set)

    @property
    def score(self) -> float:
        """Pass ratio from the inner VerifyReport."""
        return self.report.score

    @property
    def passed(self) -> int:
        """Passed count from the inner VerifyReport."""
        return self.report.passed

    @property
    def failed(self) -> int:
        """Failed count from the inner VerifyReport."""
        return self.report.failed

    @property
    def failures(self) -> list[str]:
        """Failure messages from the inner VerifyReport."""
        return self.report.failures


class _StrictParams(dict[str, str]):
    """A ``format_map`` mapping that fail-fasts on any missing key.

    The default ``str.format_map`` raises ``KeyError`` on a missing field, but
    only lazily and with an opaque message. Subclassing makes the failure mode
    explicit and lets us raise a replay-grade error: a parametrized plan that
    references ``{d}`` with no ``d`` in ``params`` is a hard authoring/wiring
    bug, never something to paper over with an empty substitution (that would
    silently produce a garbage URL and violate the no-garbage fail-fast rule).
    """

    def __missing__(self, key: str) -> str:
        raise ReplayExecutionError(f'replay param {{{key}}} is missing from params')


def _bind(act: ReplayAct, params: dict[str, str]) -> ReplayAct:
    """Substitute ``params`` into templated act fields — pure string templating.

    NO model call: substitution is ``str.format_map`` only, so this preserves
    CAS-87 replay determinism. Crucially, templating is confined to ``act.url``
    and ``act.text`` — the only fields where ``{d}``/``{q}`` actually live on the
    hotpath. ``act.script`` is NEVER templated: real extraction JS is dense with
    literal braces (arrow funcs, object literals, regex quantifiers like
    ``{0,40}``) and ``format_map`` would either raise on or corrupt the first
    brace. A brace-heavy script must round-trip untouched.
    """
    if not params:
        return act
    strict = _StrictParams(params)

    def sub(value: str | None) -> str | None:
        return value.format_map(strict) if value else value

    return act.model_copy(update={'url': sub(act.url), 'text': sub(act.text)})


async def execute_plan(
    tab: Any,
    plan: ReplayPlan,
    params: dict[str, str] | None = None,
    resolver: Any = None,
) -> ReplayResult:
    """Execute a replay plan against a browser tab.

    The runtime is deliberately fail-fast: a failed assess condition, action,
    or expected assertion raises :class:`ReplayExecutionError` instead of
    guessing alternate behavior.
    When a ReplayAct has ``output_field`` set and kind is EVAL, the return
    value of the JS expression is captured in ``ReplayResult.extracted_actions``.

    ``params`` parametrizes the plan at dispatch time: ``{d}``/``{q}`` tokens in
    ``act.url`` / ``act.text`` are substituted via a strict ``format_map`` that
    raises on any missing key (see :func:`_bind`). This is what lets ONE
    engine/tool program (e.g. ``similarweb.com/website/{d}/``) replay across N
    target domains by passing ``params={'d': domain}`` — without any model call
    on the hot path. ``act.script`` is deliberately never templated.

    ``resolver`` is the OFF-hot-path (PLANE B) :class:`~yosoi.core.replay.reactions.
    ReactionResolver` reached when an UNLEARNED REACTION fires (W1): it resolves the
    reaction's description into a recovery subtree, hot-swaps it in, and the run
    resumes. Left ``None`` (the default), an UNLEARNED reaction fails fast with
    ``ReactionMiss`` — the deterministic hot path never imports a model itself, so
    forwarding the resolver here is the single seam that connects the public replay
    entrypoint to concurrent discovery.
    """
    params = params or {}
    # Teleport-before-first-paint: install the CDP geolocation/locale override BEFORE
    # the node loop so it is live before the first NAVIGATE's goto. Lifting the spoof to
    # a per-plan field (rather than a free-floating TELEPORT node) makes "after a
    # navigate" structurally impossible — the override is sticky across the navigations
    # that follow (page.rs:set_geolocation issues a session-level Emulation override).
    if plan.teleport is not None:
        await _apply_teleport(tab, plan.teleport)
    # Single execution form: a flat plan compiles to one SEQUENCE-of-LEAF tree, so
    # execute_plan and execute_tree share the same fail-fast walker (W1).
    result = ReplayResult()
    await execute_tree(tab, plan.compile(), result, params=params, resolver=resolver)
    return result


async def verify_plan(tab: Any, plan: ReplayPlan) -> ReplayResult:
    """Execute a plan and convert fail-fast errors into a report."""
    try:
        return await execute_plan(tab, plan)
    except ReplayExecutionError as exc:
        return ReplayResult(report=exc.report)


# === Behavior-tree walker (W1) ===================================================
# PLANE A: deterministic, LLM-free tick over composite nodes whose leaves are ONLY
# the existing _EXECUTORS act kinds plus the fixed _RECOVERY_LEAVES primitives. A
# mid-flow captcha is a normal tick event (a fired REACTION guard), not a fatal
# error — the walker ticks the recovery subtree and resumes the guarded child.


async def execute_tree(
    tab: Any,
    node: TreeNode,
    ctx: ReplayResult,
    params: dict[str, str] | None = None,
    resolver: Any = None,
) -> bool:
    """Tick one behavior-tree node against *tab*, returning success.

    Deterministic and LLM-free (CAS-87): leaf dispatch only ever reaches
    ``_EXECUTORS`` or ``_RECOVERY_LEAVES``. The only place a model may run is the
    OFF-hot-path ``resolver`` (PLANE B), invoked when an UNLEARNED reaction fires.

    Returns ``True`` on success. A failed LEAF raises ``ReplayExecutionError``
    (fail-fast); composites translate that into SEQUENCE/SELECTOR control flow.
    """
    params = params or {}
    # Active reaction guards fire BEFORE the wrapped subtree ticks — a captcha that
    # popped during a prior sibling's nav is caught here, not scraped through.
    await _check_reactions(tab, ctx, params, resolver)

    if node.kind is NodeKind.LEAF:
        assert node.leaf is not None  # model_validator guarantees this
        return await _tick_leaf(tab, node.leaf, ctx, params)
    if node.kind is NodeKind.SEQUENCE:
        return await _tick_sequence(tab, node, ctx, params, resolver)
    if node.kind is NodeKind.SELECTOR:
        return await _tick_selector(tab, node, ctx, params, resolver)
    if node.kind is NodeKind.REACTION:
        return await _tick_reaction(tab, node, ctx, params, resolver)
    raise ReplayExecutionError(f'unsupported tree node kind: {node.kind}')


async def _tick_leaf(tab: Any, leaf: Any, ctx: ReplayResult, params: dict[str, str]) -> bool:
    """Run one ReplayNode (assess/act/expect) — today's flat-node semantics."""
    if not await _condition_holds(tab, leaf.assess):
        _fail(ctx.report, f'assess failed for {leaf.id}: {leaf.intent}')
    output = await _execute_act(tab, _bind(leaf.act, params), leaf.expect)
    # Gate capture on output_field alone (see execute_plan's original comment): a
    # producer that legitimately yields None must still be captured AS None.
    if leaf.act.output_field is not None:
        ctx.extracted_actions[leaf.act.output_field] = output
    if not await _condition_holds(tab, leaf.expect):
        _fail(ctx.report, f'assert failed for {leaf.id}: {leaf.intent}')
    ctx.report.passed += 1
    return True


async def _tick_sequence(tab: Any, node: TreeNode, ctx: ReplayResult, params: dict[str, str], resolver: Any) -> bool:
    """Tick children left-to-right, fail-fast on the first failure (flat semantics)."""
    for child in node.children:
        if not await execute_tree(tab, child, ctx, params, resolver):
            return False
    return True


async def _tick_selector(tab: Any, node: TreeNode, ctx: ReplayResult, params: dict[str, str], resolver: Any) -> bool:
    """Tick children left-to-right, succeed on the FIRST child that succeeds.

    A SELECTOR is the fallback composite: try the logged-in path, then a
    profile-rotation path, etc. A child's fail-fast ``ReplayExecutionError`` is
    caught and treated as "this branch failed, try the next" — only when EVERY
    branch fails does the SELECTOR raise (genuine fail-fast, no garbage).
    """
    errors: list[str] = []
    for child in node.children:
        try:
            if await execute_tree(tab, child, ctx, params, resolver):
                return True
        except ReplayExecutionError as exc:  # noqa: PERF203 — fallback control flow, not a tight loop
            errors.append(str(exc))
    _fail(ctx.report, f'selector {node.id}: all branches failed: {"; ".join(errors)}')
    return False


async def _tick_reaction(tab: Any, node: TreeNode, ctx: ReplayResult, params: dict[str, str], resolver: Any) -> bool:
    """Tick a REACTION decorator: register its guard, then tick the guarded child."""
    assert node.child is not None  # model_validator guarantees this
    ctx.active_reactions.append(node)
    try:
        return await execute_tree(tab, node.child, ctx, params, resolver)
    finally:
        if ctx.active_reactions and ctx.active_reactions[-1] is node:
            ctx.active_reactions.pop()


async def _check_reactions(tab: Any, ctx: ReplayResult, params: dict[str, str], resolver: Any) -> None:
    """Evaluate every active reaction guard; recover any that fired.

    Iterates a snapshot so a recovery that mutates ``active_reactions`` (it does
    not today) cannot corrupt the walk. Innermost-first so a captcha guarding the
    current subtree is handled before an outer drift guard.
    """
    for guard in reversed(list(ctx.active_reactions)):
        assert guard.trigger is not None
        if guard.id in ctx._recovering:
            continue  # don't re-fire a guard while ticking its own recovery subtree
        if await _condition_holds(tab, guard.trigger):
            await _recover(tab, guard, ctx, params, resolver)


async def _recover(tab: Any, guard: TreeNode, ctx: ReplayResult, params: dict[str, str], resolver: Any) -> None:
    """Handle a fired reaction guard: learned recovery inline, else resolve OFF-path.

    LEARNED  → tick the pinned recovery subtree under a tenacity resume loop.
    UNLEARNED → resolve description->recovery via the OFF-hot-path resolver (PLANE
    B, LLM allowed), hot-swap the learned recovery into the in-memory tree, then
    tick it. With no resolver wired, raise ``ReactionMiss`` (fail-fast).
    """
    from yosoi.core.replay.reactions import ReactionMiss

    assert guard.trigger is not None  # _check_reactions only calls us on a guard with a trigger
    if guard.state is ReactionState.UNLEARNED:
        info = await _capture_captcha(tab)
        learned = None
        if resolver is not None:
            domain = str(params.get('domain') or _domain_hint(tab))
            learned = await resolver.resolve(domain, guard.description or '', info)
        if learned is None:
            raise ReactionMiss(guard.trigger, guard.description, info)
        # Hot-swap: the reaction is now LEARNED for the rest of THIS run and beyond.
        guard.recovery = learned
        guard.state = ReactionState.LEARNED

    if guard.recovery is None:  # pragma: no cover - defensive; LEARNED implies recovery
        raise ReplayExecutionError(f'reaction {guard.id} is learned but has no recovery')

    await _run_recovery_loop(tab, guard, ctx, params)


async def _run_recovery_loop(tab: Any, guard: TreeNode, ctx: ReplayResult, params: dict[str, str]) -> None:
    """Tick the recovery subtree under a tenacity resume loop until the trigger clears.

    Bounded by ``stop_after_attempt`` (the fail-fast cap): a trigger that never
    clears exhausts the retryer and re-raises ``ReplayExecutionError`` — it does
    NOT degrade to a partial/garbage result. ``async for`` is mandatory:
    ``get_async_retryer`` returns an ``AsyncRetrying`` (not a plain iterator).
    """
    assert guard.trigger is not None
    assert guard.recovery is not None
    ctx._recovering.add(guard.id)
    try:
        async for attempt in get_async_retryer(max_attempts=3, exceptions=(ReplayExecutionError,)):
            with attempt:
                await execute_tree(tab, guard.recovery, ctx, params)
                if await _condition_holds(tab, guard.trigger):
                    raise ReplayExecutionError(f'reaction {guard.id} recovery ran but trigger still holds')
    finally:
        ctx._recovering.discard(guard.id)


def _domain_hint(tab: Any) -> str:
    """Best-effort domain for bus keying from the tab's current URL."""
    from urllib.parse import urlparse

    url = str(getattr(tab, 'url', '') or '')
    return urlparse(url).netloc or 'replay'


def _fail(report: VerifyReport, message: str) -> None:
    report.failed += 1
    report.failures.append(message)
    raise ReplayExecutionError(message, report)


async def _execute_act(tab: Any, act: ReplayAct, expect: ReplayCondition) -> Any:
    repeats = act.max_repeats if act.repeat else 1
    until_non_null = bool(act.metadata.get('until_non_null'))
    last_output: Any = None
    for _idx in range(repeats):
        last_output = await _execute_once(tab, act)
        if until_non_null and last_output is not None:
            return last_output
        if not act.repeat:
            return last_output
        if act.dwell_ms:
            await asyncio.sleep(act.dwell_ms / 1000)
        if not until_non_null and await _condition_holds(tab, expect):
            return last_output
    if until_non_null:
        raise ReplayExecutionError(f'{act.kind.value} output remained null after {repeats} settle attempt(s)')
    return last_output


async def _execute_once(tab: Any, act: ReplayAct) -> Any:
    """Dispatch a single act to its in-tab executor via :data:`_EXECUTORS`.

    An act kind with no registered executor fails fast — the same loud default the
    previous if-chain gave, now structural: a new ``ActKind`` cannot silently fall
    through (see ``tests/unit/core/replay/test_runtime_dispatch.py``, which asserts
    the table stays in sync with the enum).
    """
    executor = _EXECUTORS.get(act.kind) or _RECOVERY_LEAVES.get(act.kind)
    if executor is None:
        raise ReplayExecutionError(f'unsupported act kind: {act.kind}')
    return await executor(tab, act)


async def _download(tab: Any, act: ReplayAct) -> Any:
    """Execute a DOWNLOAD act by reusing the explicit-lane downloader.

    Builds a ``DownloadSpec`` from the act (first CSS target → click trigger, or ``url`` for
    refetch; ``metadata`` carries allowed_types / output view / max_bytes / domain) and runs
    the same ``run_download`` the live fetch lane uses — so replay inherits content-addressing,
    the allowed_types gate, and sha256 provenance. Returns the projected field value, captured
    into ``output_field`` by :func:`execute_plan` like an EVAL output.

    NOTE: latent today — nothing calls ``execute_plan`` yet (FUTURE: CAS-103 wires the executor,
    Phase 6 makes discovery emit DOWNLOAD nodes). FUTURE: honour the full SelectorEntry cascade
    rather than just ``targets[0]``.
    """
    from yosoi.core.fetcher.downloads import quarantine_dir, run_download
    from yosoi.models.download import DownloadSpec
    from yosoi.utils.exceptions import DownloadError

    meta = act.metadata or {}
    trigger = act.targets[0].value if act.targets and act.targets[0].type == 'css' else None
    spec = DownloadSpec(
        field=act.output_field or 'download',
        mode=meta.get('mode') or ('refetch' if act.url else 'retrigger'),
        trigger=trigger,
        url=act.url,
        allowed_types=tuple(meta.get('allowed_types') or ()),
        output=meta.get('output', 'record'),
        max_bytes=meta.get('max_bytes'),
    )
    try:
        result = await run_download(tab, spec, quarantine_dir(str(meta.get('domain') or 'replay')))
    except DownloadError as exc:
        raise ReplayExecutionError(str(exc)) from exc
    return result.value


# --- Act executors -----------------------------------------------------------------
# Each executor runs one act against a LIVE browser tab and returns either None (a
# page-mutating act like click/navigate) or a value to capture into ``output_field``
# (eval/download). The thin wrappers below adapt the existing helpers to the uniform
# ``(tab, act) -> Any`` shape the dispatch table requires.


async def _exec_navigate(tab: Any, act: ReplayAct) -> Any:
    response = await _call(tab, 'goto', act.url)
    _raise_if_challenged(response, act.url)
    return None


def _raise_if_challenged(response: Any, url: str | None) -> None:
    """Fail-fast on an antibot/captcha challenge surfaced by ``goto``.

    ``PooledTab.goto`` returns a ``PageResponse`` whose ``antibot.challenged``
    flag is the substrate's existing captcha signal — no ``Page.detect_captcha``
    (which is not bound on a pooled tab) and no new ``AssertKind`` needed. When a
    challenge is present we raise :class:`ReplayExecutionError` so the off-hotpath
    orchestrator can rotate proxy/profile via tenacity, rather than proceeding to
    scrape a challenge page and returning garbage. Defensive ``getattr``: older
    VoidCrawl builds expose no ``antibot`` field, in which case there is simply no
    challenge signal to act on (absence is not a challenge — we do not fail-closed).
    """
    antibot = getattr(response, 'antibot', None)
    if antibot is not None and getattr(antibot, 'challenged', False):
        raise ReplayExecutionError(f'antibot challenge detected at {url}')


async def _exec_click(tab: Any, act: ReplayAct) -> Any:
    if act.metadata.get('click_all'):
        return await _click_all(tab, act)
    await _click_first(tab, act.targets)
    return None


async def _click_all(tab: Any, act: ReplayAct) -> int:
    """Click matching elements in bounded CSS row scopes through one JS act."""
    if len(act.targets) != 1:
        raise ReplayExecutionError('click_all requires exactly one target')
    target = act.targets[0]
    within = act.metadata.get('within_selector')
    raw_limit = act.metadata.get('limit')
    if raw_limit is None:
        raise ReplayExecutionError('click_all limit must be an integer')
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError) as exc:
        raise ReplayExecutionError('click_all limit must be an integer') from exc
    if limit < 1:
        raise ReplayExecutionError('click_all limit must be >= 1')
    if target.type == 'role':
        candidate_selector = 'button,[role="button"]' if target.value == 'button' else f'[role="{target.value}"]'
        name = (target.name or '').casefold()
        predicate = (
            f"((el.getAttribute('aria-label') || el.innerText || '').trim().toLowerCase().includes({json.dumps(name)}))"
        )
    elif target.type == 'css':
        candidate_selector = target.value
        predicate = 'true'
    else:
        raise ReplayExecutionError(f'{target.type} click_all targets are not supported')
    if within:
        scopes = f'Array.from(document.querySelectorAll({json.dumps(str(within))})).slice(0, {limit})'
        script = f"""(() => {{
          const scopes = {scopes};
          let clicked = 0;
          for (const scope of scopes) {{
            for (const el of scope.querySelectorAll({json.dumps(candidate_selector)})) {{
              if ({predicate}) {{ el.click(); clicked += 1; break; }}
            }}
          }}
          return clicked;
        }})()"""
    else:
        script = f"""(() => {{
          let clicked = 0;
          for (const el of document.querySelectorAll({json.dumps(candidate_selector)})) {{
            if ({predicate}) {{
              el.click();
              clicked += 1;
              if (clicked >= {limit}) return clicked;
            }}
          }}
          return clicked;
        }})()"""
    result = await _eval(tab, script)
    return int(result or 0)


async def _exec_type(tab: Any, act: ReplayAct) -> Any:
    await _type_first(tab, act.targets, act.text or '')
    return None


async def _exec_scroll(tab: Any, act: ReplayAct) -> Any:
    await _scroll(tab, act)
    return None


async def _exec_wait(tab: Any, act: ReplayAct) -> Any:
    if act.dwell_ms:
        await asyncio.sleep(act.dwell_ms / 1000)
    return None


async def _exec_eval(tab: Any, act: ReplayAct) -> Any:
    return await _eval(tab, act.script or '')


async def _exec_teleport(tab: Any, act: ReplayAct) -> Any:
    await _teleport(tab, act.metadata)
    return None


# --- Recovery leaf executors (W1) --------------------------------------------------
# These run on the deterministic hot path (CAS-87): each is eval_js / dispatch-only,
# never a solver or model call. The SOLVE (obtaining a token, or recording a
# humanized-click recipe) happens OFF the hot path in PLANE B and is injected here
# as a PRE-RESOLVED literal payload (act.metadata['token'] / act.metadata recipe).


async def _exec_captcha_probe(tab: Any, act: ReplayAct) -> Any:
    """Run the ported CAPTURE_JS via eval_js; return the CaptchaInfo dict or None.

    PooledTab has no ``capture_captcha`` binding, so we eval the pure-JS port. When
    ``output_field`` is set the result is captured like any EVAL output.
    """
    return await _eval(tab, CAPTURE_JS)


async def _exec_inject_token(tab: Any, act: ReplayAct) -> Any:
    """Inject a PRE-RESOLVED captcha token via eval_js — never fetches a token.

    The token + kind are literal payloads in ``act.metadata`` (resolved in PLANE B).
    Absent a token this fails fast rather than injecting an empty/garbage value.
    """
    meta = act.metadata or {}
    kind = meta.get('kind')
    token = meta.get('token')
    if not kind or not token:
        raise ReplayExecutionError('inject_token requires metadata kind and token (pre-resolved)')
    return await _eval(tab, inject_token_js(str(kind), str(token)))


async def _exec_human_click(tab: Any, act: ReplayAct) -> Any:
    """Replay a recorded dispatch_mouse_event recipe — a humanized checkbox click.

    Offsets are stored RELATIVE to the captcha widget rect (re-probed at replay via
    CAPTURE_JS) so they survive layout shifts, mirroring VoidCrawl's solve_captcha
    rect-relative click. ``act.metadata`` carries ``offset_x``/``offset_y`` (0..1
    fractions of the widget box). No new binding: dispatch_mouse_event is already on
    PooledTab.
    """
    meta = act.metadata or {}
    info = await _capture_captcha(tab)
    rect = (info or {}).get('widget_rect') if isinstance(info, dict) else None
    if not isinstance(rect, dict):
        raise ReplayExecutionError('human_click could not re-probe a rendered captcha widget rect')
    fx = float(meta.get('offset_x', 0.5))
    fy = float(meta.get('offset_y', 0.5))
    x = float(rect.get('x', 0)) + float(rect.get('width', 0)) * fx
    y = float(rect.get('y', 0)) + float(rect.get('height', 0)) * fy
    await _call(tab, 'dispatch_mouse_event', 'mouseMoved', x, y)
    await _call(tab, 'dispatch_mouse_event', 'mousePressed', x, y)
    await _call(tab, 'dispatch_mouse_event', 'mouseReleased', x, y)
    return None


async def _capture_captcha(tab: Any) -> Any:
    """Best-effort CAPTURE_JS probe used by guards/recovery; never raises."""
    try:
        return await _eval(tab, CAPTURE_JS)
    except ReplayExecutionError:
        return None


# Dispatch table for in-tab, deterministic browser acts — the composition spine for a
# per-domain replay program (CAS-87). New browser act kind → add an executor + one entry.
#
# DELIBERATELY browser-acts-only. Out-of-band evals do NOT belong here:
#   * ys.python (ActKind.EVAL_PYTHON) runs in a Pyodide sandbox over already-extracted
#     data — it has no live tab, so it is a post-``execute_plan`` transform, not an act.
#   * ys.llm (ActKind.EVAL_LLM) is a non-deterministic model call — adding it here would
#     put the LLM back on the replay hot path and break replay-grade determinism.
#   * ys.wasm is a future codec behind ``_eval``, not a new kind.
# Keeping this table deterministic and LLM-free is what lets the discovery layer be the
# signal-driven brain without contaminating replay. See CAS-87 for the full decision.
_EXECUTORS: dict[ActKind, Callable[[Any, ReplayAct], Awaitable[Any]]] = {
    ActKind.NAVIGATE: _exec_navigate,
    ActKind.CLICK: _exec_click,
    ActKind.TYPE: _exec_type,
    ActKind.SCROLL: _exec_scroll,
    ActKind.WAIT: _exec_wait,
    ActKind.EVAL: _exec_eval,
    ActKind.DOWNLOAD: _download,
    ActKind.TELEPORT: _exec_teleport,
}


# Recovery-leaf dispatch table — parallel to _EXECUTORS, same no-silent-fallthrough
# invariant (see tests/unit/core/replay/test_runtime_dispatch.py). A REACTION's
# recovery subtree may compose ONLY these kinds: each is eval_js / dispatch-only and
# carries a PRE-RESOLVED literal payload, so a learned recovery is as deterministic
# and LLM-free as any other replay leaf (CAS-87). The actual solve lives in PLANE B.
_RECOVERY_LEAVES: dict[ActKind, Callable[[Any, ReplayAct], Awaitable[Any]]] = {
    ActKind.CAPTCHA_PROBE: _exec_captcha_probe,
    ActKind.INJECT_TOKEN: _exec_inject_token,
    ActKind.HUMAN_CLICK: _exec_human_click,
}


async def _condition_holds(tab: Any, condition: ReplayCondition) -> bool:
    if condition.kind == AssertKind.NONE:
        return True
    if condition.kind == AssertKind.SELECTOR:
        return await _selector_condition(tab, condition)
    if condition.kind == AssertKind.COUNT:
        return await _count_condition(tab, condition)
    if condition.kind == AssertKind.TEXT:
        return await _text_condition(tab, condition)
    if condition.kind == AssertKind.URL:
        return await _url_condition(tab, condition)
    if condition.kind == AssertKind.DOM_STABLE:
        await _wait_for_dom_stable(tab, condition)
        return True
    if condition.kind in {AssertKind.AX_TARGET, AssertKind.ABSENT, AssertKind.ABSENT_AX_TARGET}:
        return await _target_condition(tab, condition)
    if condition.kind == AssertKind.CAPTCHA:
        return await _captcha_condition(tab)
    # DOWNLOAD_OK: the DOWNLOAD act fails-fast internally (allowed_types/min-size via
    # run_download), so reaching the expect step means a verified download was captured.
    # FUTURE: thread the captured result here to assert content-type/min-size vs condition.value.
    return condition.kind == AssertKind.DOWNLOAD_OK


async def _target_condition(tab: Any, condition: ReplayCondition) -> bool:
    """Evaluate present/absent DOM or accessibility targets."""
    if condition.selector is None:
        return False
    if condition.kind == AssertKind.AX_TARGET:
        return await _ax_target_exists(tab, condition.selector)
    if condition.kind == AssertKind.ABSENT_AX_TARGET:
        return not await _ax_target_exists(tab, condition.selector)
    return not await _selector_exists(tab, condition.selector)


async def _captcha_condition(tab: Any) -> bool:
    """Trigger guard: a RENDERED antibot/captcha wall is present (W1).

    Fires only when CAPTURE_JS returns a widget with ``widget_rendered`` true —
    a runtime-loaded-but-unmounted Turnstile (Ahrefs lazy mount) does NOT trip the
    guard, avoiding false-positive recoveries.
    """
    info = await _capture_captcha(tab)
    return isinstance(info, dict) and bool(info.get('widget_rendered'))


async def _selector_condition(tab: Any, condition: ReplayCondition) -> bool:
    if condition.selector is None:
        return False
    return await _selector_exists(tab, condition.selector)


async def _count_condition(tab: Any, condition: ReplayCondition) -> bool:
    if condition.selector is None or not isinstance(condition.value, int):
        return False
    return await _selector_count(tab, condition.selector) >= condition.value


async def _text_condition(tab: Any, condition: ReplayCondition) -> bool:
    if condition.value is None:
        return False
    content = await _content(tab)
    return str(condition.value) in content


async def _url_condition(tab: Any, condition: ReplayCondition) -> bool:
    if condition.value is None:
        return False
    current = str(getattr(tab, 'url', '') or await _eval(tab, 'location.href'))
    return str(condition.value) in current


async def _selector_exists(tab: Any, selector: SelectorEntry) -> bool:
    if selector.type == 'role':
        return await _ax_target_exists(tab, selector)
    if selector.type != 'css':
        raise ReplayExecutionError(f'{selector.type} conditions are not supported by replay runtime yet')
    return await _call(tab, 'query_selector', selector.value) is not None


async def _selector_count(tab: Any, selector: SelectorEntry) -> int:
    if selector.type != 'css':
        raise ReplayExecutionError(f'{selector.type} count conditions are not supported by replay runtime yet')
    matches = await _call(tab, 'query_selector_all', selector.value)
    return len(matches or [])


async def _ax_target_exists(tab: Any, selector: SelectorEntry) -> bool:
    return bool(await _matching_ax_targets(tab, selector))


async def _matching_ax_targets(tab: Any, selector: SelectorEntry) -> list[str]:
    """Return exact AX names matching one role/name substring selector."""
    if selector.type != 'role':
        raise ReplayExecutionError(f'{selector.type} AX conditions are not supported by replay runtime')
    if not hasattr(tab, 'get_full_ax_tree'):
        return []
    nodes = await _call(tab, 'get_full_ax_tree')
    name = (selector.name or '').lower()
    return [
        exact_name
        for node in nodes or []
        if _ax_value(node, 'role') == selector.value and name in (exact_name := _ax_value(node, 'name')).lower()
    ]


async def _click_first(tab: Any, targets: list[SelectorEntry]) -> None:
    errors: list[str] = []
    for target in targets:
        error = await _try_click_target(tab, target)
        if error is None:
            return
        errors.append(error)
    raise ReplayExecutionError(f'click failed for all targets: {"; ".join(errors)}')


async def _try_click_target(tab: Any, target: SelectorEntry) -> str | None:
    try:
        await _click_target(tab, target)
        return None
    except ReplayExecutionError as exc:
        return str(exc)


async def _click_target(tab: Any, target: SelectorEntry) -> None:
    if target.type == 'role':
        if hasattr(tab, 'get_full_ax_tree'):
            matches = await _matching_ax_targets(tab, target)
            index = target.nth or 0
            if matches:
                if index >= len(matches):
                    raise ReplayExecutionError(
                        f'no AX node with role={target.value!r} containing name={target.name!r} at index {index}'
                    )
                # VoidCrawl click_by_role performs exact accessible-name matching. Resolve
                # our resilient substring target through the AX tree, then preserve the
                # occurrence index when duplicate nodes share that exact accessible name.
                exact_name = matches[index]
                exact_index = matches[:index].count(exact_name)
                await _call(tab, 'click_by_role', target.value, exact_name, exact_index)
                return
        await _call(tab, 'click_by_role', target.value, target.name, target.nth or 0)
        return
    if target.type == 'css':
        if hasattr(tab, 'click_element'):
            await _call(tab, 'click_element', target.value)
            return
        await _call(tab, 'click', target.value)
        return
    if target.type == 'visual':
        await _call(tab, 'click_visual_coords', target.x, target.y)
        return
    raise ReplayExecutionError(f'{target.type} click targets are not supported by replay runtime yet')


async def _type_first(tab: Any, targets: list[SelectorEntry], text: str) -> None:
    for target in targets:
        if target.type != 'css':
            continue
        # PooledTab (the object the BrowserPool yields) exposes only ``type_into``
        # — neither ``fill`` nor ``type``. Prefer it so SERP programs that type a
        # query can replay on the live pooled-tab substrate; the ``fill``/``type``
        # branches remain for bare Tab/JsTab variants used in discovery.
        if hasattr(tab, 'type_into'):
            await _call(tab, 'type_into', target.value, text)
            return
        if hasattr(tab, 'fill'):
            await _call(tab, 'fill', target.value, text)
            return
        await _call(tab, 'type', target.value, text)
        return
    raise ReplayExecutionError('type acts require a css target in the current replay runtime')


async def _scroll(tab: Any, act: ReplayAct) -> None:
    pixels = int(act.metadata.get('pixels', 1200))
    anchor_selector = act.metadata.get('anchor_selector')
    if isinstance(anchor_selector, str) and anchor_selector:
        selector = json.dumps(anchor_selector)
        await _eval(
            tab,
            f"""(() => {{
              const anchor = document.querySelector({selector});
              if (!anchor) return false;
              let node = anchor;
              while (node) {{
                if (node.scrollHeight > node.clientHeight + 100) {{
                  node.scrollTop = node.scrollHeight;
                  return true;
                }}
                node = node.parentElement;
              }}
              return false;
            }})()""",
        )
        return
    await _eval(tab, f'window.scrollBy(0, {pixels})')


async def _teleport(tab: Any, metadata: dict[str, Any]) -> None:
    if 'latitude' in metadata and 'longitude' in metadata:
        await _call(tab, 'set_geolocation', metadata['latitude'], metadata['longitude'])
    if timezone := metadata.get('timezone'):
        await _call(tab, 'set_timezone', timezone)
    if locale := metadata.get('locale'):
        await _call(tab, 'set_locale', locale)


async def _apply_teleport(tab: Any, spec: TeleportSpec) -> None:
    """Install the geolocation/timezone/locale override for a per-plan TeleportSpec.

    Called by :func:`execute_plan` BEFORE the node loop so the CDP override is live
    before first paint. NO ``example.com`` secure-context prime here: that proof-read
    is DISCOVERY-TIME verification (it confirms the override mechanism landed once when
    the lesson was learned), not a replay hot-path ritual. ``set_geolocation`` is a
    sticky session-level override (page.rs), so one install survives the navigations
    that follow — the double-load the notes blamed on teleport is an engine-side
    one-zone-lag effect, modeled separately, not a reload teleport itself needs.
    """
    await _call(tab, 'set_geolocation', spec.latitude, spec.longitude)
    if spec.timezone:
        await _call(tab, 'set_timezone', spec.timezone)
    if spec.locale:
        await _call(tab, 'set_locale', spec.locale)


async def _wait_for_dom_stable(tab: Any, condition: ReplayCondition) -> None:
    timeout = condition.timeout_ms / 1000
    if hasattr(tab, 'wait_for_network_idle'):
        await _call(tab, 'wait_for_network_idle', timeout=timeout)
        return
    if condition.quiet_ms:
        await asyncio.sleep(condition.quiet_ms / 1000)


async def _content(tab: Any) -> str:
    return str(await _call(tab, 'content'))


async def _eval(tab: Any, script: str) -> Any:
    """Evaluate *script* on a voidcrawl tab — the single eval chokepoint.

    ``eval_js`` is Yosoi's canonical name for live-DOM JS evaluation and is the
    method present on the pooled tabs we actually acquire. ``evaluate_js`` and
    the legacy ``evaluate`` are kept only as compatibility fallbacks for bare
    ``Tab``/``JsTab`` variants that expose just the longer alias.
    """
    if hasattr(tab, 'eval_js'):
        return await _call(tab, 'eval_js', script)
    if hasattr(tab, 'evaluate_js'):
        return await _call(tab, 'evaluate_js', script)
    return await _call(tab, 'evaluate', script)


async def _call(obj: Any, name: str, *args: Any, **kwargs: Any) -> Any:
    method = getattr(obj, name, None)
    if method is None:
        raise ReplayExecutionError(f'tab does not support {name}')
    try:
        value = method(*args, **kwargs)
        if inspect.isawaitable(value):
            return await value
        return value
    except (RuntimeError, OSError, ValueError) as exc:
        raise ReplayExecutionError(f'{name} failed: {exc}') from exc


def _ax_value(node: dict[str, Any], key: str) -> str:
    value = node.get(key)
    if isinstance(value, dict):
        inner = value.get('value')
        return inner if isinstance(inner, str) else ''
    return value if isinstance(value, str) else ''
