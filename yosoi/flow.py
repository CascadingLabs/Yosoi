"""Manually-authored A3Node Flow declarations and live execution."""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from typing import Any, cast

import pydantic.fields
from pydantic import BaseModel, TypeAdapter

from yosoi.executor import InputRef, bind_executor_action, resolve_refs
from yosoi.models.replay import ActKind, AssertKind, ReplayAct, ReplayCondition, ReplayNode, ReplayPlan
from yosoi.models.selectors import SelectorEntry


@dataclass(frozen=True)
class _Condition:
    kind: AssertKind
    target: SelectorEntry | None = None
    value: Any = None
    timeout_ms: int = 5000
    quiet_ms: int | None = None


@dataclass(frozen=True)
class _NearestScrollParent:
    anchor: SelectorEntry


@dataclass(frozen=True)
class _Action:
    kind: ActKind
    targets: tuple[SelectorEntry, ...] = ()
    repeat: bool = False
    max_repeats: int | InputRef = 1
    dwell_ms: int = 0
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class _FlowStep:
    value: Any
    expectation: Any


@dataclass(frozen=True)
class _Declaration:
    name: str
    value: Any
    annotation: Any
    expectation: Any = None


class FlowResult(BaseModel):
    """Validated outputs and acquisition evidence from one live Flow run."""

    url: str
    values: dict[str, Any]
    html: str | None = None
    fetch_time: float


class _FlowMeta(type):
    def __new__(mcls, name: str, bases: tuple[type[Any], ...], namespace: dict[str, Any]) -> type[Any]:
        cls: Any = super().__new__(mcls, name, bases, namespace)
        inherited: list[_Declaration] = []
        for base in bases:
            inherited.extend(getattr(base, '_flow_declarations', ()))

        try:
            annotations = inspect.get_annotations(cls, eval_str=True)
        except (NameError, TypeError, ValueError):
            annotations = dict(namespace.get('__annotations__', {}))

        local: list[_Declaration] = []
        for attr_name, value in namespace.items():
            if attr_name.startswith('_'):
                continue
            expectation = None
            if isinstance(value, _FlowStep):
                value, expectation = value.value, value.expectation
            if isinstance(value, (_Action, pydantic.fields.FieldInfo)):
                local.append(_Declaration(attr_name, value, annotations.get(attr_name), expectation))

        local_names = {item.name for item in local}
        cls._flow_declarations = [item for item in inherited if item.name not in local_names] + local
        return cast(type[Any], cls)


class Flow(metaclass=_FlowMeta):
    """Ordered class declaration compiled directly into an A3 ReplayPlan."""

    _flow_declarations: list[_Declaration]

    @classmethod
    def compile(cls, url: str, *, inputs: dict[str, Any] | None = None) -> ReplayPlan:
        """Compile this class into the existing deterministic ReplayPlan model."""
        bound_inputs = dict(inputs or {})
        nodes = [
            ReplayNode(
                id='navigate',
                intent='navigate',
                act=ReplayAct(kind=ActKind.NAVIGATE, url=url),
            )
        ]
        nodes.extend(_compile_declaration(declaration, bound_inputs) for declaration in cls._flow_declarations)
        return ReplayPlan(nodes=nodes)

    @classmethod
    async def run(
        cls,
        url: str,
        *,
        inputs: dict[str, Any] | None = None,
        fetcher_type: str = 'headless',
        timeout: int = 45,
        quiet: bool = True,
        warmup: int = 0,
    ) -> FlowResult:
        """Execute this Flow on a live VoidCrawl browser and validate outputs."""
        from rich.console import Console

        from yosoi.core.fetcher.voiddriver import HeadfulFetcher, HeadlessFetcher

        if fetcher_type not in {'headless', 'headful'}:
            raise ValueError("Flow.run fetcher_type must be 'headless' or 'headful'")
        if warmup < 0:
            raise ValueError('Flow.run warmup must be >= 0')
        fetcher_cls = HeadlessFetcher if fetcher_type == 'headless' else HeadfulFetcher
        plan = cls.compile(url, inputs=inputs)
        fetcher = fetcher_cls(
            timeout=timeout,
            max_concurrent=1,
            lightweight_fetch=True,
            experimental_replay_plan=True,
            console=Console(quiet=quiet),
        )
        async with fetcher:
            for _ in range(warmup):
                warmed = await fetcher.fetch(url)
                if not warmed.success:
                    raise RuntimeError(warmed.block_reason or f'Flow warm-up failed for {url}')
            fetched = await fetcher.fetch_with_plan(plan)
        if not fetched.success:
            raise RuntimeError(fetched.block_reason or f'Flow acquisition failed for {url}')
        values = cls.validate_outputs(fetched.js_outputs or {})
        return FlowResult(url=url, values=values, html=fetched.html, fetch_time=fetched.fetch_time)

    @classmethod
    def validate_outputs(cls, outputs: dict[str, Any]) -> dict[str, Any]:
        """Validate captured Executor outputs against Flow annotations."""
        validated = dict(outputs)
        for declaration in cls._flow_declarations:
            if not isinstance(declaration.value, pydantic.fields.FieldInfo):
                continue
            if declaration.annotation is None:
                continue
            if declaration.name not in outputs:
                raise ValueError(f'Flow executor produced no output for {declaration.name}')
            validated[declaration.name] = TypeAdapter(declaration.annotation).validate_python(outputs[declaration.name])
        return validated


def _compile_declaration(declaration: _Declaration, inputs: dict[str, Any]) -> ReplayNode:
    expectation = _expectation(declaration.expectation, inputs)
    value = declaration.value
    if isinstance(value, _Action):
        max_repeats = _resolve_number(value.max_repeats, inputs)
        metadata = resolve_refs(value.metadata or {}, inputs)
        act = ReplayAct(
            kind=value.kind,
            targets=list(value.targets),
            repeat=value.repeat,
            max_repeats=max_repeats,
            dwell_ms=value.dwell_ms,
            metadata=metadata,
        )
    else:
        extra = value.json_schema_extra
        config = extra.get('yosoi_action') if isinstance(extra, dict) else None
        if not isinstance(config, dict):
            raise TypeError(f'unsupported Flow field descriptor: {declaration.name}')
        if config.get('type') == 'js':
            act = ReplayAct(
                kind=ActKind.EVAL,
                script=bind_executor_action(config, inputs),
                metadata={'settle': config.get('settle')},
                output_field=declaration.name,
            )
        elif config.get('type') == 'collect_each':
            evaluator = config.get('evaluator')
            if not isinstance(evaluator, dict):
                raise TypeError('collect_each requires one Executor.js evaluator')
            act = ReplayAct(
                kind=ActKind.COLLECT_EACH,
                targets=[SelectorEntry.model_validate(config['target'])],
                script=bind_executor_action(evaluator, inputs),
                metadata={
                    'ready_target': config['ready_target'],
                    'close_targets': config['close_targets'],
                    'limit': _resolve_number(config['limit'], inputs),
                    'dedupe_by': config.get('dedupe_by'),
                    'allow_empty': bool(config.get('allow_empty')),
                },
                output_field=declaration.name,
            )
        else:
            raise TypeError(f'unsupported Flow field descriptor: {declaration.name}')
    return ReplayNode(
        id=declaration.name,
        intent=declaration.name.replace('_', ' '),
        act=act,
        expect=expectation,
    )


def _resolve_number(value: int | InputRef | dict[str, str], inputs: dict[str, Any]) -> int:
    if isinstance(value, dict):
        value = InputRef(value['$input'])
    if isinstance(value, InputRef):
        if value.name not in inputs:
            raise ValueError(f'missing required Flow input: {value.name}')
        value = int(inputs[value.name])
    if value < 1:
        raise ValueError('Flow repeat limits must be >= 1')
    return value


def _expectation(condition: Any, inputs: dict[str, Any]) -> ReplayCondition:
    if condition is None:
        return ReplayCondition()
    if isinstance(condition, SelectorEntry):
        kind = AssertKind.AX_TARGET if condition.type == 'role' else AssertKind.SELECTOR
        return ReplayCondition(kind=kind, selector=condition)
    if not isinstance(condition, _Condition):
        raise TypeError(f'unsupported Flow expectation: {condition!r}')
    value = condition.value
    if isinstance(value, InputRef):
        if value.name not in inputs:
            raise ValueError(f'missing required Flow input: {value.name}')
        value = inputs[value.name]
    return ReplayCondition(
        kind=condition.kind,
        selector=condition.target,
        value=value,
        timeout_ms=condition.timeout_ms,
        quiet_ms=condition.quiet_ms,
    )


def expect(action: Any, condition: Any) -> Any:
    """Attach a post-action condition without abusing Python type annotations."""
    if isinstance(action, _FlowStep):
        raise TypeError('expect() cannot wrap an already wrapped Flow step')
    if not isinstance(action, (_Action, pydantic.fields.FieldInfo)):
        raise TypeError('expect() requires a Flow action or executor descriptor')
    return _FlowStep(action, condition)


def click(target: SelectorEntry | tuple[SelectorEntry, ...] | list[SelectorEntry]) -> _Action:
    """Create one A3 CLICK act; target descriptions are positional."""
    targets = tuple(target) if isinstance(target, (tuple, list)) else (target,)
    return _Action(ActKind.CLICK, targets=targets)


def click_all(
    target: SelectorEntry | tuple[SelectorEntry, ...] | list[SelectorEntry],
    *,
    limit: int | InputRef,
    within: SelectorEntry | None = None,
) -> _Action:
    """Click every matching target once, optionally within bounded row scopes."""
    targets = tuple(target) if isinstance(target, (tuple, list)) else (target,)
    if within is not None and within.type != 'css':
        raise TypeError('click_all within currently requires a CSS selector')
    return _Action(
        ActKind.CLICK,
        targets=targets,
        metadata={
            'click_all': True,
            'limit': {'$input': limit.name} if isinstance(limit, InputRef) else limit,
            'within_selector': within.value if within is not None else None,
        },
    )


def collect_each(
    target: SelectorEntry,
    *,
    ready: SelectorEntry,
    collect: pydantic.fields.FieldInfo,
    close: SelectorEntry | tuple[SelectorEntry, ...] | list[SelectorEntry],
    limit: int | InputRef,
    dedupe_by: str | None = None,
    allow_empty: bool = False,
) -> Any:
    """Sequentially open matching UI items, collect typed values, and close each overlay."""
    extra = collect.json_schema_extra
    evaluator = extra.get('yosoi_action') if isinstance(extra, dict) else None
    if not isinstance(evaluator, dict) or evaluator.get('type') != 'js':
        raise TypeError('collect_each collect= must be an Executor.js descriptor')
    close_targets = tuple(close) if isinstance(close, (tuple, list)) else (close,)
    if not close_targets:
        raise ValueError('collect_each requires at least one close target')
    if dedupe_by is not None and not dedupe_by:
        raise ValueError('collect_each dedupe_by must not be empty')
    return cast(
        pydantic.fields.FieldInfo,
        pydantic.Field(
            ...,
            json_schema_extra={
                'yosoi_action': {
                    'type': 'collect_each',
                    'target': target.model_dump(mode='json'),
                    'ready_target': ready.model_dump(mode='json'),
                    'close_targets': [item.model_dump(mode='json') for item in close_targets],
                    'limit': {'$input': limit.name} if isinstance(limit, InputRef) else limit,
                    'dedupe_by': dedupe_by,
                    'allow_empty': allow_empty,
                    'evaluator': evaluator,
                }
            },
        ),
    )


def wait_until(*, max_attempts: int | InputRef = 20, interval_ms: int = 250) -> _Action:
    """Poll the annotated expectation with a repeated deterministic WAIT act."""
    if interval_ms < 0:
        raise ValueError('wait_until interval_ms must be >= 0')
    return _Action(
        ActKind.WAIT,
        repeat=True,
        max_repeats=max_attempts,
        dwell_ms=interval_ms,
    )


def nearest_scroll_parent(anchor: SelectorEntry) -> _NearestScrollParent:
    """Address the nearest scrollable ancestor of one CSS anchor."""
    if anchor.type != 'css':
        raise TypeError('nearest_scroll_parent currently requires a CSS anchor')
    return _NearestScrollParent(anchor)


def scroll_until(
    container: _NearestScrollParent,
    *,
    max_scrolls: int | InputRef,
    stop_when: str = 'expectation',
    stable_rounds: int = 3,
) -> _Action:
    """Create a repeated A3 SCROLL act gated by the annotated expectation."""
    if stop_when not in {'expectation', 'no_growth'}:
        raise ValueError("stop_when must be 'expectation' or 'no_growth'")
    if stable_rounds < 1:
        raise ValueError('scroll_until stable_rounds must be >= 1')
    return _Action(
        ActKind.SCROLL,
        repeat=True,
        max_repeats=max_scrolls,
        dwell_ms=1000 if stop_when == 'no_growth' else 0,
        metadata={
            'anchor_selector': container.anchor.value,
            'stop_when': stop_when,
            'stable_rounds': stable_rounds,
        },
    )


def count(target: SelectorEntry, *, at_least: int | InputRef) -> _Condition:
    """Require at least a number of CSS matches."""
    if target.type != 'css':
        raise TypeError('count currently requires a CSS selector')
    return _Condition(AssertKind.COUNT, target=target, value=at_least)


def absent(target: SelectorEntry) -> _Condition:
    """Require a target to be absent."""
    kind = AssertKind.ABSENT_AX_TARGET if target.type == 'role' else AssertKind.ABSENT
    return _Condition(kind, target=target)


def dom_stable(*, quiet_ms: int = 300, timeout_ms: int = 5000) -> _Condition:
    """Require the page network/DOM to settle after an act."""
    return _Condition(AssertKind.DOM_STABLE, timeout_ms=timeout_ms, quiet_ms=quiet_ms)


def matches(pattern: str) -> str:
    """Reduce a simple boundary regex to the AX substring supported by replay."""
    return re.sub(r'\\b', '', pattern)
