"""Fail-fast runtime for executing persisted replay plans."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from yosoi.models.replay import ActKind, AssertKind, ReplayAct, ReplayCondition, ReplayPlan, VerifyReport
from yosoi.models.results import JsOutputs
from yosoi.models.selectors import SelectorEntry


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


async def execute_plan(tab: Any, plan: ReplayPlan, params: dict[str, str] | None = None) -> ReplayResult:
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
    """
    params = params or {}
    report = VerifyReport()
    captured: JsOutputs = {}
    for node in plan.nodes:
        if not await _condition_holds(tab, node.assess):
            _fail(report, f'assess failed for {node.id}: {node.intent}')

        output = await _execute_act(tab, _bind(node.act, params), node.expect)
        # Gate capture on output_field alone: only producer acts (EVAL/DOWNLOAD) set it,
        # so this never captures a mutator's None. A producer that legitimately yields
        # None (JS returning null, an empty projection) must be captured AS None — dropping
        # it would silently omit the field and read as success on a replay-grade substrate.
        if node.act.output_field is not None:
            captured[node.act.output_field] = output

        if not await _condition_holds(tab, node.expect):
            _fail(report, f'assert failed for {node.id}: {node.intent}')
        report.passed += 1
    return ReplayResult(report=report, extracted_actions=captured)


async def verify_plan(tab: Any, plan: ReplayPlan) -> ReplayResult:
    """Execute a plan and convert fail-fast errors into a report."""
    try:
        return await execute_plan(tab, plan)
    except ReplayExecutionError as exc:
        return ReplayResult(report=exc.report)


def _fail(report: VerifyReport, message: str) -> None:
    report.failed += 1
    report.failures.append(message)
    raise ReplayExecutionError(message, report)


async def _execute_act(tab: Any, act: ReplayAct, expect: ReplayCondition) -> Any:
    repeats = act.max_repeats if act.repeat else 1
    last_output: Any = None
    for idx in range(repeats):
        last_output = await _execute_once(tab, act)
        if act.dwell_ms:
            await asyncio.sleep(act.dwell_ms / 1000)
        if not act.repeat or await _condition_holds(tab, expect):
            return last_output
        if idx == repeats - 1:
            return last_output
    return last_output


async def _execute_once(tab: Any, act: ReplayAct) -> Any:
    """Dispatch a single act to its in-tab executor via :data:`_EXECUTORS`.

    An act kind with no registered executor fails fast — the same loud default the
    previous if-chain gave, now structural: a new ``ActKind`` cannot silently fall
    through (see ``tests/unit/core/replay/test_runtime_dispatch.py``, which asserts
    the table stays in sync with the enum).
    """
    executor = _EXECUTORS.get(act.kind)
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
    await _click_first(tab, act.targets)
    return None


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
    if condition.kind == AssertKind.AX_TARGET:
        if condition.selector is None:
            return False
        return await _ax_target_exists(tab, condition.selector)
    # DOWNLOAD_OK: the DOWNLOAD act fails-fast internally (allowed_types/min-size via
    # run_download), so reaching the expect step means a verified download was captured.
    # FUTURE: thread the captured result here to assert content-type/min-size vs condition.value.
    return condition.kind == AssertKind.DOWNLOAD_OK


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
    if selector.type != 'role':
        raise ReplayExecutionError(f'{selector.type} AX conditions are not supported by replay runtime')
    if not hasattr(tab, 'get_full_ax_tree'):
        return False
    nodes = await _call(tab, 'get_full_ax_tree')
    name = (selector.name or '').lower()
    for node in nodes or []:
        role = _ax_value(node, 'role')
        node_name = _ax_value(node, 'name').lower()
        if role == selector.value and name in node_name:
            return True
    return False


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
    await _eval(tab, f'window.scrollBy(0, {pixels})')


async def _teleport(tab: Any, metadata: dict[str, Any]) -> None:
    if 'latitude' in metadata and 'longitude' in metadata:
        await _call(tab, 'set_geolocation', metadata['latitude'], metadata['longitude'])
    if timezone := metadata.get('timezone'):
        await _call(tab, 'set_timezone', timezone)
    if locale := metadata.get('locale'):
        await _call(tab, 'set_locale', locale)


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
