"""Fail-fast runtime for executing persisted replay plans."""

from __future__ import annotations

import asyncio
import inspect
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


async def execute_plan(tab: Any, plan: ReplayPlan) -> ReplayResult:
    """Execute a replay plan against a browser tab.

    The runtime is deliberately fail-fast: a failed assess condition, action,
    or expected assertion raises :class:`ReplayExecutionError` instead of
    guessing alternate behavior.
    When a ReplayAct has ``output_field`` set and kind is EVAL, the return
    value of the JS expression is captured in ``ReplayResult.extracted_actions``.
    """
    report = VerifyReport()
    captured: JsOutputs = {}
    for node in plan.nodes:
        if not await _condition_holds(tab, node.assess):
            _fail(report, f'assess failed for {node.id}: {node.intent}')

        output = await _execute_act(tab, node.act, node.expect)
        if node.act.output_field is not None and output is not None:
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
    if act.kind == ActKind.NAVIGATE:
        await _call(tab, 'goto', act.url)
        return None
    if act.kind == ActKind.CLICK:
        await _click_first(tab, act.targets)
        return None
    if act.kind == ActKind.TYPE:
        await _type_first(tab, act.targets, act.text or '')
        return None
    if act.kind == ActKind.SCROLL:
        await _scroll(tab, act)
        return None
    if act.kind == ActKind.WAIT:
        if act.dwell_ms:
            await asyncio.sleep(act.dwell_ms / 1000)
        return None
    if act.kind == ActKind.EVAL:
        return await _eval(tab, act.script or '')
    if act.kind == ActKind.TELEPORT:
        await _teleport(tab, act.metadata)
        return None
    raise ReplayExecutionError(f'unsupported act kind: {act.kind}')


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
    return False


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
    if hasattr(tab, 'evaluate_js'):
        return await _call(tab, 'evaluate_js', script)
    if hasattr(tab, 'eval_js'):
        return await _call(tab, 'eval_js', script)
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
