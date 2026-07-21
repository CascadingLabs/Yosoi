"""Manually-authored A3Node Flow declarations and live execution."""

from __future__ import annotations

import inspect
import math
import re
from dataclasses import dataclass
from typing import Any, ClassVar, Generic, TypeVar, cast

import pydantic.fields
from pydantic import BaseModel, TypeAdapter

from yosoi.executor import InputRef, bind_executor_action, resolve_refs
from yosoi.models.replay import ActKind, AssertKind, ReplayAct, ReplayCondition, ReplayNode, ReplayPlan
from yosoi.models.selectors import SelectorEntry


@dataclass(frozen=True)
class _Expectation:
    condition: Any


class State:
    """Named, reusable post-action browser state for typed Flow transitions."""

    condition: ClassVar[Any]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Require every concrete state to declare one supported condition."""
        super().__init_subclass__(**kwargs)
        condition = getattr(cls, 'condition', None)
        if not isinstance(condition, (SelectorEntry, _Condition)):
            raise TypeError(f'{cls.__name__}: State.condition must be a selector or Flow condition')


_StateT = TypeVar('_StateT', bound=State)


class Expect(Generic[_StateT]):
    """Flow annotation mapping a named State to one post-action A3 condition."""

    def __class_getitem__(cls, state: Any) -> _Expectation:
        """Build annotation metadata from one State class."""
        if not isinstance(state, type) or not issubclass(state, State):
            raise TypeError('Expect[...] requires a ys.State subclass')
        return _Expectation(state.condition)


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
class _Declaration:
    name: str
    value: Any
    annotation: Any


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
        inherited_names: set[str] = set()
        for base in bases:
            for declaration in getattr(base, '_flow_declarations', ()):
                if declaration.name not in inherited_names:
                    inherited.append(declaration)
                    inherited_names.add(declaration.name)

        try:
            annotations = inspect.get_annotations(cls, eval_str=True)
        except (NameError, TypeError, ValueError) as exc:
            raise TypeError(f'{name}: Flow annotations must resolve at class definition time: {exc}') from exc

        local: list[_Declaration] = []
        for attr_name, value in namespace.items():
            if attr_name.startswith('_'):
                continue
            if isinstance(value, (_Action, pydantic.fields.FieldInfo)):
                local.append(_Declaration(attr_name, value, annotations.get(attr_name)))

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
            if isinstance(declaration.annotation, _Expectation) or declaration.annotation is None:
                continue
            if declaration.name not in outputs:
                raise ValueError(f'Flow executor produced no output for {declaration.name}')
            validated[declaration.name] = TypeAdapter(declaration.annotation).validate_python(outputs[declaration.name])
        return validated


def _compile_declaration(declaration: _Declaration, inputs: dict[str, Any]) -> ReplayNode:
    expectation = _expectation(declaration.annotation, inputs)
    value = declaration.value
    if isinstance(value, _Action):
        if value.repeat and expectation.kind == AssertKind.NONE:
            raise TypeError(f'{declaration.name}: repeated actions require ys.Expect[...]')
        max_repeats = _resolve_number(value.max_repeats, inputs)
        metadata = resolve_refs(value.metadata or {}, inputs)
        if metadata.get('click_all'):
            metadata['limit'] = _positive_int(metadata.get('limit'), name='click_all limit')
        act = ReplayAct(
            kind=value.kind,
            targets=list(value.targets),
            repeat=value.repeat,
            max_repeats=max_repeats,
            dwell_ms=value.dwell_ms,
            metadata=metadata,
        )
    else:
        if declaration.annotation is None:
            raise TypeError(f'{declaration.name}: Flow Executor.js fields require an output annotation')
        extra = value.json_schema_extra
        config = extra.get('yosoi_action') if isinstance(extra, dict) else None
        if not isinstance(config, dict) or config.get('type') != 'js':
            raise TypeError(f'unsupported Flow field descriptor: {declaration.name}')
        settle = config.get('settle')
        settle_timeout = float(settle.get('timeout', 0)) if isinstance(settle, dict) else 0.0
        settle_poll = float(settle.get('poll_interval', 0.25)) if isinstance(settle, dict) else 0.25
        should_settle = isinstance(settle, dict)
        act = ReplayAct(
            kind=ActKind.EVAL,
            script=bind_executor_action(config, inputs),
            output_field=declaration.name,
            repeat=should_settle,
            max_repeats=max(1, math.floor(settle_timeout / settle_poll) + 1)
            if should_settle and settle_poll > 0
            else 1,
            dwell_ms=max(0, int(settle_poll * 1000)) if should_settle else 0,
            metadata={'until_non_null': True} if should_settle else {},
        )
    return ReplayNode(
        id=declaration.name,
        intent=declaration.name.replace('_', ' '),
        act=act,
        expect=expectation,
    )


def _resolve_number(value: int | InputRef, inputs: dict[str, Any]) -> int:
    if isinstance(value, InputRef):
        if value.name not in inputs:
            raise ValueError(f'missing required Flow input: {value.name}')
        value = inputs[value.name]
    return _positive_int(value, name='Flow repeat limits')


def _expectation(annotation: Any, inputs: dict[str, Any]) -> ReplayCondition:
    if not isinstance(annotation, _Expectation):
        return ReplayCondition()
    condition = annotation.condition
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
    if condition.kind == AssertKind.COUNT:
        value = _non_negative_int(value, name='count at_least')
    return ReplayCondition(
        kind=condition.kind,
        selector=condition.target,
        value=value,
        timeout_ms=condition.timeout_ms,
        quiet_ms=condition.quiet_ms,
    )


def _strict_int(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f'{name} must be an integer')
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f'{name} must be an integer') from exc


def _positive_int(value: Any, *, name: str) -> int:
    resolved = _strict_int(value, name=name)
    if resolved < 1:
        raise ValueError(f'{name} must be >= 1')
    return resolved


def _non_negative_int(value: Any, *, name: str) -> int:
    resolved = _strict_int(value, name=name)
    if resolved < 0:
        raise ValueError(f'{name} must be >= 0')
    return resolved


def click(target: SelectorEntry | tuple[SelectorEntry, ...] | list[SelectorEntry]) -> _Action:
    """Create one A3 CLICK act; target descriptions are positional."""
    targets = tuple(target) if isinstance(target, (tuple, list)) else (target,)
    return _Action(ActKind.CLICK, targets=targets)


def click_all(
    target: SelectorEntry,
    *,
    limit: int | InputRef,
    within: SelectorEntry | None = None,
) -> _Action:
    """Click matching targets up to a limit, or one target per bounded row scope."""
    if not isinstance(target, SelectorEntry):
        raise TypeError('click_all requires exactly one selector target')
    if isinstance(limit, int):
        _positive_int(limit, name='click_all limit')
    if within is not None and within.type != 'css':
        raise TypeError('click_all within currently requires a CSS selector')
    return _Action(
        ActKind.CLICK,
        targets=(target,),
        metadata={
            'click_all': True,
            'limit': {'$input': limit.name} if isinstance(limit, InputRef) else limit,
            'within_selector': within.value if within is not None else None,
        },
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
) -> _Action:
    """Create a repeated A3 SCROLL act gated by the annotated expectation."""
    if stop_when != 'expectation':
        raise ValueError("scroll_until stop_when currently supports only 'expectation'")
    return _Action(
        ActKind.SCROLL,
        repeat=True,
        max_repeats=max_scrolls,
        metadata={'anchor_selector': container.anchor.value},
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
