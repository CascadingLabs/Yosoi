"""Deterministic, network-free per-row extraction primitives.

Extractor fields are deliberately separate from selector discovery and browser actions.
An extractor receives only :class:`ExtractionRow`, may return a value or awaitable, and is
validated against the contract field annotation before its value is accepted.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import inspect
import json
import types
import typing
from collections.abc import Callable, Coroutine, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Generic, Literal, TypeVar, get_args, get_origin

from parsel import Selector
from pydantic import BaseModel, ConfigDict, Field

ExtractorSource = Literal['explicit', 'method', 'annotation', 'registry', 'generalized']
EvidenceSource = Literal['dom', 'attribute', 'text', 'json_ld', 'raw_html', 'runtime']
ValidationResult = Literal['valid', 'no_match', 'invalid', 'error']

T = TypeVar('T')


class ExtractorNoMatch(Exception):
    """Expected extractor abstention; this is not an implementation failure."""

    def __init__(self, reason: str = 'no matching value') -> None:
        """Initialize an expected abstention with a content-free reason."""
        super().__init__(reason)
        self.reason = reason


class ExtractorResolutionError(TypeError):
    """Raised before acquisition when an extractor field cannot be bound safely."""


class ExtractorFieldError(ValueError):
    """Raised when one row cannot satisfy a deterministic extractor field."""

    def __init__(self, field: str, row_index: int, resolver_id: str, category: str, detail: str) -> None:
        """Initialize a row/field-scoped deterministic extraction failure."""
        super().__init__(
            f'extractor field {field!r} failed on row {row_index} ({category}, resolver={resolver_id}): {detail}'
        )
        self.field = field
        self.row_index = row_index
        self.resolver_id = resolver_id
        self.category = category


class ExtractionEvidence(BaseModel):
    """Content-free evidence emitted by an instrumented row operation."""

    model_config = ConfigDict(frozen=True)

    source: EvidenceSource
    operation: str = Field(min_length=1)
    target_fingerprint: str = Field(min_length=1)


@dataclass(frozen=True)
class ExtractionOutcome(Generic[T]):
    """An extracted value with optional explicit, content-free evidence."""

    value: T
    evidence: tuple[ExtractionEvidence, ...] = ()


class ExtractorSpec(BaseModel):
    """Serializable identity and configuration for one deterministic strategy."""

    model_config = ConfigDict(frozen=True)

    resolver_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    source: ExtractorSource
    reference: str = Field(min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)
    plan: dict[str, Any] | None = None
    batch_fields: tuple[str, ...] = ()
    portable: bool = True
    opaque: bool = False

    @property
    def fingerprint(self) -> str:
        """Return a stable identity hash without extracted values."""
        payload = json.dumps(self.model_dump(mode='json'), sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


class RowFingerprint(BaseModel):
    """Small-fragment structural identity independent of visible content and attributes values."""

    model_config = ConfigDict(frozen=True)

    scheme: str = 'yrf1'
    structure: str = Field(min_length=1)
    node_count_band: str
    depth_band: str

    @classmethod
    def of(cls, html: str) -> RowFingerprint:
        """Fingerprint a row using tag/depth/attribute-key/child-count structure only."""
        root = Selector(text=html).root
        features: list[str] = []
        max_depth = 0
        try:
            iterator = root.iter()
        except AttributeError:
            iterator = ()
        for element in iterator:
            tag = element.tag if isinstance(element.tag, str) else 'node'
            depth = 0
            parent = element.getparent()
            while parent is not None:
                depth += 1
                parent = parent.getparent()
            max_depth = max(max_depth, depth)
            attr_keys = ','.join(sorted(str(key).casefold() for key in element.attrib))
            child_count = len(element)
            child_band = '0' if child_count == 0 else '1' if child_count == 1 else '2-4' if child_count <= 4 else '5+'
            features.append(f'{depth}:{tag.casefold()}:{attr_keys}:{child_band}')
        digest = hashlib.sha256('\n'.join(features).encode()).hexdigest()[:24]
        return cls(
            structure=digest,
            node_count_band=_cardinality_band(len(features)),
            depth_band=_cardinality_band(max_depth),
        )

    def similarity(self, other: RowFingerprint) -> float:
        """Return conservative exact-shape similarity for row strategy proposals."""
        if self.structure == other.structure:
            return 1.0
        return 0.0


class ExtractorFingerprint(BaseModel):
    """Content-free runtime fingerprint for a validated extractor execution."""

    model_config = ConfigDict(frozen=True)

    scheme: str = 'yef1'
    page_structure: str = Field(min_length=1)
    row: RowFingerprint
    route_template: str
    root_scope: str
    field_fingerprint: str = Field(min_length=1)
    resolver_id: str = Field(min_length=1)
    resolver_version: str = Field(min_length=1)
    resolver_source: ExtractorSource
    evidence_sources: tuple[EvidenceSource, ...] = ()
    operations: tuple[str, ...] = ()
    validation_result: ValidationResult
    cardinality_band: str
    opaque: bool = False


def _freeze_context_value(value: Any) -> Any:
    """Recursively freeze extractor configuration exposed through a row context."""
    if isinstance(value, Mapping):
        return types.MappingProxyType({key: _freeze_context_value(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_context_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_context_value(item) for item in value)
    return value


class ExtractionRow:
    """Immutable, network-free context for one contract row.

    CSS/XPath/text/attribute/JSON-LD helpers record content-free operation evidence.
    Reading :attr:`raw_html` is supported as an escape hatch and marks the execution
    opaque unless the extractor also emits explicit structured evidence.
    """

    __slots__ = (
        '_config',
        '_evidence',
        '_html',
        '_index',
        '_root_scope',
        '_runtime_evidence',
        '_selector',
        '_url',
    )

    def __init__(
        self,
        html: str,
        *,
        url: str = '',
        index: int = 0,
        root_scope: str = 'rootless',
        config: Mapping[str, Any] | None = None,
        runtime_evidence: Mapping[str, Sequence[str]] | None = None,
        _evidence: list[ExtractionEvidence] | None = None,
    ) -> None:
        """Initialize one immutable row context from already-acquired evidence."""
        self._html = html
        self._url = url
        self._index = index
        self._root_scope = root_scope
        self._config = {key: _freeze_context_value(value) for key, value in (config or {}).items()}
        self._runtime_evidence: dict[str, tuple[str, ...]] = {}
        for channel, values in (runtime_evidence or {}).items():
            if not isinstance(channel, str):
                raise TypeError('runtime evidence channel names must be strings')
            items = (values,) if isinstance(values, str) else tuple(values)
            if not all(isinstance(value, str) for value in items):
                raise TypeError(f'runtime evidence channel {channel!r} must contain only strings')
            self._runtime_evidence[channel] = items
        self._evidence = _evidence if _evidence is not None else []
        self._selector: Selector | None = None

    @property
    def url(self) -> str:
        """Source URL for this already-acquired row."""
        return self._url

    @property
    def index(self) -> int:
        """Zero-based row index within the acquired page."""
        return self._index

    @property
    def root_scope(self) -> str:
        """Content-free identity for the root that produced this row."""
        return self._root_scope

    @property
    def config(self) -> Mapping[str, Any]:
        """Read-only extractor configuration supplied by ``ys.Extractor``."""
        return types.MappingProxyType(self._config)

    @property
    def raw_html(self) -> str:
        """Return row HTML and mark this execution as opaque."""
        self._record('raw_html', 'read', 'row')
        return self._html

    @property
    def html(self) -> str:
        """Alias for :attr:`raw_html`."""
        return self.raw_html

    @property
    def evidence(self) -> tuple[ExtractionEvidence, ...]:
        """Return evidence emitted so far, never extracted values."""
        return tuple(self._evidence)

    @property
    def selector(self) -> Selector:
        """Return the parsed row selector without exposing a browser/network handle."""
        if self._selector is None:
            self._selector = Selector(text=self._html)
        return self._selector

    def css(self, query: str) -> Any:
        """Run a CSS query scoped to this row and record DOM evidence."""
        self._record('dom', 'css', query)
        return self.selector.css(query)

    def xpath(self, query: str) -> Any:
        """Run an XPath query scoped to this row and record DOM evidence."""
        self._record('dom', 'xpath', query)
        return self.selector.xpath(query)

    def attribute(self, query: str, name: str, *, xpath: bool = False) -> list[str]:
        """Return matching attribute values while recording only operation identity."""
        self._record('attribute', 'xpath_attr' if xpath else 'css_attr', f'{query}\x1f{name}')
        matches = self.selector.xpath(query) if xpath else self.selector.css(query)
        return [value for node in matches if (value := node.attrib.get(name)) is not None]

    def text(self, query: str | None = None, *, xpath: bool = False, all: bool = False) -> str | list[str]:
        """Return normalized descendant text for the row or selected nodes."""
        target = query or 'row'
        self._record('text', 'xpath_text' if xpath else 'css_text', target)
        nodes = (
            self.selector.xpath(query)
            if query is not None and xpath
            else self.selector.css(query)
            if query is not None
            else [self.selector]
        )
        values = [' '.join(node.xpath('.//text()').getall()).strip() for node in nodes]
        values = [value for value in values if value]
        return values if all else (values[0] if values else '')

    def json_ld(self, path: str | None = None) -> list[Any]:
        """Return JSON-LD payloads or values traversed by a dotted path.

        ``*`` traverses every list item or mapping value. Malformed scripts abstain
        individually. Evidence stores only a hash of the requested path.
        """
        self._record('json_ld', 'json_ld', path or '$')
        scripts = self.selector.xpath(
            '//script[contains(translate(@type, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), '
            '"ld+json")]/text()'
        ).getall()
        payloads: list[Any] = []
        for script in scripts:
            try:
                payloads.append(json.loads(script))
            except (json.JSONDecodeError, TypeError):  # noqa: PERF203 — malformed scripts abstain independently
                continue
        if path is None or path in {'', '$'}:
            return payloads
        parts = [part for part in path.removeprefix('$.').split('.') if part]
        values: list[Any] = payloads
        for part in parts:
            next_values: list[Any] = []
            for value in values:
                if part == '*':
                    if isinstance(value, dict):
                        next_values.extend(value.values())
                    elif isinstance(value, list):
                        next_values.extend(value)
                elif isinstance(value, dict) and part in value:
                    next_values.append(value[part])
                elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
                    next_values.append(value[int(part)])
            values = next_values
        return values

    def json_ld_mappings(self) -> list[dict[str, Any]]:
        """Return every mapping recursively contained in the row's JSON-LD payloads."""
        self._record('json_ld', 'json_ld_walk', '$')
        out: list[dict[str, Any]] = []

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                out.append(value)
                for child in value.values():
                    if isinstance(child, (dict, list)):
                        visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        for payload in self.json_ld():
            visit(payload)
        return out

    def runtime_values(self, channel: str | None = None) -> list[str]:
        """Return pre-fetched runtime values without exposing a browser or network handle.

        ``channel`` is application-defined (for example ``resource_urls`` or
        ``endpoints``). Omitting it returns every channel in insertion order. Runtime
        values are never included in operation evidence or fingerprints.
        """
        channels = (channel,) if channel is not None else tuple(self._runtime_evidence)
        self._record('runtime', 'runtime_values', '\x1f'.join(channels) or 'all')
        return [value for name in channels for value in self._runtime_evidence.get(name, ())]

    def _for_extractor(self, config: Mapping[str, Any]) -> ExtractionRow:
        return ExtractionRow(
            self._html,
            url=self.url,
            index=self.index,
            root_scope=self.root_scope,
            config=config,
            runtime_evidence=self._runtime_evidence,
            _evidence=self._evidence,
        )

    def _record(self, source: EvidenceSource, operation: str, target: str) -> None:
        target_fp = hashlib.sha256(target.encode()).hexdigest()[:16]
        self._evidence.append(ExtractionEvidence(source=source, operation=operation, target_fingerprint=target_fp))


@dataclass(frozen=True)
class ExtractorBinding:
    """Resolved callable and portable strategy identity for one contract field."""

    field_name: str
    fn: Callable[[ExtractionRow], Any]
    spec: ExtractorSpec
    batch_fields: tuple[str, ...] = ()

    async def execute(
        self,
        row: ExtractionRow,
        *,
        batch_cache: dict[str, tuple[Any, tuple[ExtractionEvidence, ...]] | BaseException] | None = None,
    ) -> tuple[Any, tuple[ExtractionEvidence, ...]]:
        """Execute and await one strategy, preserving abstention separately from errors."""
        batch_key = self.spec.fingerprint if self.batch_fields else None
        if batch_key is not None and batch_cache is not None and batch_key in batch_cache:
            cached = batch_cache[batch_key]
            if isinstance(cached, BaseException):
                raise cached
            value, evidence = cached
        else:
            scoped_row = row._for_extractor(self.spec.config)
            before = len(scoped_row.evidence)
            try:
                value = self.fn(scoped_row)
                if inspect.isawaitable(value):
                    value = await value
                explicit: tuple[ExtractionEvidence, ...] = ()
                if isinstance(value, ExtractionOutcome):
                    explicit = value.evidence
                    value = value.value
                if isinstance(value, ExtractorNoMatch):
                    raise value
                evidence = (*scoped_row.evidence[before:], *explicit)
            except BaseException as exc:
                if batch_key is not None and batch_cache is not None:
                    batch_cache[batch_key] = exc
                raise
            if batch_key is not None and batch_cache is not None:
                batch_cache[batch_key] = value, evidence

        if self.batch_fields:
            value = self._select_batch_output(value)
        return value, evidence

    def _select_batch_output(self, value: Any) -> Any:
        """Validate one shared batch result and select this binding's field."""
        if not isinstance(value, Mapping):
            raise TypeError(
                f'batch extractor {self.spec.resolver_id!r} must return a mapping or ys.values(...), '
                f'got {type(value).__name__}'
            )
        unexpected = set(value) - set(self.batch_fields)
        if unexpected:
            rendered = ', '.join(sorted(repr(key) for key in unexpected))
            raise TypeError(f'batch extractor {self.spec.resolver_id!r} returned unexpected field(s): {rendered}')
        if self.field_name not in value:
            raise ExtractorNoMatch(f'batch extractor omitted {self.field_name!r}')
        return value[self.field_name]


@dataclass(frozen=True)
class _RegistryEntry:
    fn: Callable[[ExtractionRow], Any]
    spec: ExtractorSpec


_EXTRACTOR_REGISTRY: dict[str, _RegistryEntry] = {}
_RUNTIME_EXTRACTORS: dict[str, Callable[[ExtractionRow], Any]] = {}
_PLAN_CONFIG_KEY = '__yosoi_plan__'
_EXTRACTION_TARGET_ATTR = '__yosoi_extraction_targets__'
_EXTRACTION_BATCH_ATTR = '__yosoi_extraction_batch__'
_BINDING_TOKEN_KEY = '__yosoi_binding_token__'


def _decorator_target_token(target: Any, *, decorator: str) -> str:
    """Attach a temporary stable token to one extractor marker."""
    extra = getattr(target, 'json_schema_extra', None)
    marker = extra.get('yosoi_extractor') if isinstance(extra, dict) else None
    if not isinstance(marker, dict):
        raise TypeError(f'{decorator} requires a field declared with ys.Extractor()')
    token = marker.get(_BINDING_TOKEN_KEY)
    if not isinstance(token, str):
        token = f'field:{id(marker):x}'
        marker[_BINDING_TOKEN_KEY] = token
    return token


def extraction(target: Any) -> Callable[[Callable[..., Any]], staticmethod[Any, Any]]:
    """Bind one method to an ``ys.Extractor()`` field without a naming convention."""
    token = _decorator_target_token(target, decorator='@ys.extraction(...)')

    def decorate(fn: Callable[..., Any]) -> staticmethod[Any, Any]:
        setattr(fn, _EXTRACTION_TARGET_ATTR, (token,))
        setattr(fn, _EXTRACTION_BATCH_ATTR, False)
        return staticmethod(fn)

    return decorate


def extractions(*targets: Any) -> Callable[[Callable[..., Any]], staticmethod[Any, Any]]:
    """Bind one row callback to several extractor fields and execute it once per row."""
    if not targets:
        raise TypeError('@ys.extractions(...) requires at least one ys.Extractor() field')
    tokens = tuple(_decorator_target_token(target, decorator='@ys.extractions(...) targets') for target in targets)

    def decorate(fn: Callable[..., Any]) -> staticmethod[Any, Any]:
        setattr(fn, _EXTRACTION_TARGET_ATTR, tokens)
        setattr(fn, _EXTRACTION_BATCH_ATTR, True)
        return staticmethod(fn)

    return decorate


def values(**outputs: Any) -> dict[str, Any]:
    """Return named outputs from a multi-field ``@ys.extractions`` callback."""
    return outputs


def _resolve_decorator_fields(
    contract: type[Any],
    method_name: str,
    targets: Iterable[str],
    tokens_to_fields: Mapping[str, list[str]],
    claimed: set[str],
) -> list[str]:
    """Resolve decorator tokens and reject ambiguous or duplicate field claims."""
    field_names: list[str] = []
    for token in targets:
        matched_fields = tokens_to_fields.get(token)
        if matched_fields is None:
            raise TypeError(f'{contract.__name__}.{method_name}: extraction target is not a field on this contract')
        if len(matched_fields) != 1:
            rendered = ', '.join(matched_fields)
            raise TypeError(
                f'{contract.__name__}.{method_name}: one ys.Extractor() marker was reused by fields '
                f'{rendered}; declare a separate marker for each decorated field'
            )
        field_name = matched_fields[0]
        if field_name in claimed:
            raise TypeError(f'{contract.__name__}.{field_name}: multiple @ys.extraction bindings are not allowed')
        marker = contract.extractor_fields()[field_name]
        if marker.get('reference') or _PLAN_CONFIG_KEY in dict(marker.get('config') or {}):
            raise TypeError(
                f'{contract.__name__}.{field_name}: a decorator cannot be combined with an explicit extractor strategy'
            )
        claimed.add(field_name)
        field_names.append(field_name)
    return field_names


def bind_extraction_methods(contract: type[Any]) -> None:
    """Resolve decorator targets to field names after Pydantic has built the model."""
    tokens_to_fields: dict[str, list[str]] = {}
    for field_name, marker in contract.extractor_fields().items():
        token = marker.get(_BINDING_TOKEN_KEY)
        if isinstance(token, str):
            tokens_to_fields.setdefault(token, []).append(field_name)
    claimed: set[str] = set()
    for method_name, raw in list(contract.__dict__.items()):
        fn = raw.__func__ if isinstance(raw, (staticmethod, classmethod)) else raw
        targets = getattr(fn, _EXTRACTION_TARGET_ATTR, None)
        if not targets:
            continue
        field_names = _resolve_decorator_fields(contract, method_name, targets, tokens_to_fields, claimed)
        is_batch = bool(getattr(fn, _EXTRACTION_BATCH_ATTR, False))
        if is_batch:
            configs = [dict(contract.extractor_fields()[name].get('config') or {}) for name in field_names]
            if any(config != configs[0] for config in configs[1:]):
                raise TypeError(f'{contract.__name__}.{method_name}: batch extractor fields must use identical config')
        for field_name in field_names:
            marker = contract.extractor_fields()[field_name]
            marker['bound_method'] = method_name
            marker['batch_fields'] = tuple(field_names) if is_batch else ()
    for marker in contract.extractor_fields().values():
        marker.pop(_BINDING_TOKEN_KEY, None)


async def _apply_plan_maps(value: Any, references: Iterable[Any]) -> Any:
    """Apply importable plan transforms sequentially and preserve input cardinality."""
    for reference in references:
        if not isinstance(reference, str):
            raise ExtractorResolutionError('extractor plan map references must be strings')
        mapper = _load_callable(reference)
        if isinstance(value, list):
            mapped: list[Any] = []
            for item in value:
                result = mapper(item)
                mapped.append(await result if inspect.isawaitable(result) else result)
            value = mapped
        else:
            result = mapper(value)
            value = await result if inspect.isawaitable(result) else result
    return value


async def _execute_plan(row: ExtractionRow, plan: Mapping[str, Any], *, many: bool) -> Any:
    """Evaluate a serialized selector plan against one already-acquired row."""
    selector = plan.get('selector')
    if not isinstance(selector, Mapping):
        raise ExtractorResolutionError('extractor plan is missing its selector')
    selector_type = selector.get('type')
    query = selector.get('value')
    if selector_type not in {'css', 'xpath'} or not isinstance(query, str) or not query:
        raise ExtractorResolutionError('extractor plan requires a non-empty CSS or XPath selector')
    use_xpath = selector_type == 'xpath'
    operation = plan.get('operation')
    if operation == 'text':
        value: Any = row.text(query, xpath=use_xpath, all=many)
    elif operation == 'attribute':
        attribute = plan.get('attribute')
        if not isinstance(attribute, str) or not attribute:
            raise ExtractorResolutionError('attribute extractor plan requires an attribute name')
        matches = row.attribute(query, attribute, xpath=use_xpath)
        if many:
            value = matches
        elif matches:
            value = matches[0]
        else:
            raise ExtractorNoMatch()
    else:
        raise ExtractorResolutionError(f'unknown extractor plan operation {operation!r}')

    if not many and (value is None or value == ''):
        raise ExtractorNoMatch()
    value = await _apply_plan_maps(value, plan.get('maps') or ())
    if plan.get('compact'):
        if isinstance(value, list):
            value = [item for item in value if item is not None]
        elif value is None:
            raise ExtractorNoMatch()
    return value


def register_extractor(
    target: Any,
    using: Callable[[ExtractionRow], Any] | None = None,
    *,
    key: str | None = None,
    version: str | None = None,
    config: Mapping[str, Any] | None = None,
) -> Any:
    """Register an exact deterministic extractor for an annotation or semantic type.

    This supports direct and decorator forms. String targets name a Yosoi semantic
    type; all other targets are normalized as complete Python annotations.
    """

    def register(fn: Callable[[ExtractionRow], Any]) -> Callable[[ExtractionRow], Any]:
        spec, resolved = extractor_spec_for_callable(
            fn,
            source='registry',
            key=key,
            version=version,
            config=config,
        )
        registry_key = f'semantic:{target}' if isinstance(target, str) else f'annotation:{annotation_identity(target)}'
        if registry_key in _EXTRACTOR_REGISTRY:
            raise ValueError(f'an extractor is already registered for {registry_key}')
        _EXTRACTOR_REGISTRY[registry_key] = _RegistryEntry(resolved, spec)
        return fn

    return register(using) if using is not None else register


def resolve_extractor_bindings(
    contract: type[Any], *, fail_required: bool = True
) -> dict[str, ExtractorBinding | None]:
    """Resolve every extractor field in precedence order before page acquisition."""
    bindings: dict[str, ExtractorBinding | None] = {}
    for field_name, marker in contract.extractor_fields().items():
        binding = _resolve_one(contract, field_name, marker)
        if binding is None and fail_required and contract.model_fields[field_name].is_required():
            annotation = annotation_identity(contract.model_fields[field_name].annotation)
            raise ExtractorResolutionError(
                f'{contract.__name__}.{field_name} has no exact deterministic extractor for {annotation}; '
                'provide a fluent ys.css()/ys.xpath() plan, ys.Extractor(using=...), '
                f'@ys.extraction(...), {contract.__name__}.extract_{field_name}, '
                'a __yosoi_extract__ hook, or an exact registry entry'
            )
        bindings[field_name] = binding
    return bindings


def annotation_identity(annotation: Any) -> str:
    """Return a stable recursive identity for complete output annotations."""
    origin = get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        return 'union[' + ','.join(annotation_identity(arg) for arg in get_args(annotation)) + ']'
    if origin is not None:
        return (
            f'{annotation_identity(origin)}[' + ','.join(annotation_identity(arg) for arg in get_args(annotation)) + ']'
        )
    if annotation is type(None):
        return 'builtins:None'
    module = getattr(annotation, '__module__', None)
    qualname = getattr(annotation, '__qualname__', None)
    if module and qualname:
        return f'{module}:{qualname}'
    return repr(annotation)


def extractor_spec_for_callable(
    fn_or_ref: Callable[[ExtractionRow], Any] | str,
    *,
    source: ExtractorSource,
    key: str | None = None,
    version: str | None = None,
    config: Mapping[str, Any] | None = None,
) -> tuple[ExtractorSpec, Callable[[ExtractionRow], Any]]:
    """Validate a callable/ref and derive its serializable stable identity."""
    cfg = dict(config or {})
    try:
        json.dumps(cfg, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise TypeError('extractor config must be JSON-serializable') from exc

    portable = True
    if isinstance(fn_or_ref, str):
        reference = fn_or_ref
        if reference.startswith('runtime:'):
            runtime_key = reference.removeprefix('runtime:')
            try:
                fn = _RUNTIME_EXTRACTORS[runtime_key]
            except KeyError as exc:
                raise ExtractorResolutionError(
                    f'extractor {runtime_key!r} is process-local and has not been registered in this process'
                ) from exc
            portable = False
        else:
            fn = _load_callable(reference)
    else:
        fn = fn_or_ref
        try:
            reference = callable_reference(fn)
        except ExtractorResolutionError as exc:
            if not key or version is None:
                raise
            reference = f'runtime:{key}'
            _validate_callable(fn, reference)
            existing = _RUNTIME_EXTRACTORS.get(key)
            if existing is not None and existing is not fn:
                raise ExtractorResolutionError(
                    f'process-local extractor key {key!r} is already bound to a different callable'
                ) from exc
            _RUNTIME_EXTRACTORS[key] = fn
            portable = False

    _validate_callable(fn, reference)
    resolver_id = key or reference
    resolved_version = version or str(getattr(fn, '__yosoi_version__', '1'))
    return (
        ExtractorSpec(
            resolver_id=resolver_id,
            version=resolved_version,
            source=source,
            reference=reference,
            config=cfg,
            portable=portable,
            opaque=False,
        ),
        fn,
    )


def callable_reference(fn: Callable[..., Any]) -> str:
    """Return an importable ``module:qualname`` reference or fail clearly."""
    target = getattr(fn, '__func__', fn)
    module = getattr(target, '__module__', None)
    qualname = getattr(target, '__qualname__', None)
    if not module or not qualname or '<locals>' in qualname or getattr(target, '__name__', '') == '<lambda>':
        raise ExtractorResolutionError(
            'extractor callables must be importable module-level functions/methods; '
            'for a process-local closure provide explicit key= and version='
        )
    reference = f'{module}:{qualname}'
    loaded = _load_callable(reference)
    loaded_target = getattr(loaded, '__func__', loaded)
    if loaded_target is not target:
        raise ExtractorResolutionError(
            f'extractor reference {reference!r} does not resolve back to the supplied callable'
        )
    return reference


def validate_extraction_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize a data-only plan before any page acquisition."""
    from yosoi.models.selectors import SelectorEntry

    allowed_keys = {'selector', 'operation', 'attribute', 'maps', 'compact'}
    unexpected = set(plan) - allowed_keys
    if unexpected:
        rendered = ', '.join(sorted(repr(key) for key in unexpected))
        raise ExtractorResolutionError(f'extractor plan has unexpected key(s): {rendered}')
    selector_payload = plan.get('selector')
    if not isinstance(selector_payload, Mapping):
        raise ExtractorResolutionError('extractor plan is missing its selector')
    try:
        selector = SelectorEntry.model_validate(selector_payload)
    except (TypeError, ValueError) as exc:
        raise ExtractorResolutionError('extractor plan has an invalid selector') from exc
    if selector.type not in {'css', 'xpath'}:
        raise ExtractorResolutionError('extractor plan requires a CSS or XPath selector')
    operation = plan.get('operation')
    attribute = plan.get('attribute')
    if operation not in {'text', 'attribute'}:
        raise ExtractorResolutionError(f'unknown extractor plan operation {operation!r}')
    if operation == 'attribute' and (not isinstance(attribute, str) or not attribute):
        raise ExtractorResolutionError('attribute extractor plan requires an attribute name')
    if operation == 'text' and attribute is not None:
        raise ExtractorResolutionError('text extractor plans cannot configure an attribute name')
    maps = plan.get('maps', [])
    if not isinstance(maps, list) or not all(isinstance(reference, str) for reference in maps):
        raise ExtractorResolutionError('extractor plan maps must be a list of module:qualname references')
    for reference in maps:
        mapper = _load_callable(reference)
        _validate_callable(mapper, reference)
    compact = plan.get('compact', False)
    if not isinstance(compact, bool):
        raise ExtractorResolutionError('extractor plan compact must be a boolean')
    return {
        'selector': selector.model_dump(mode='json'),
        'operation': operation,
        'attribute': attribute,
        'maps': maps,
        'compact': compact,
    }


def _plan_has_many_outputs(annotation: Any) -> bool:
    """Return whether an annotation expects collection cardinality from a plan."""
    origin = get_origin(annotation)
    if isinstance(origin, type) and issubclass(origin, Iterable) and not issubclass(origin, (str, bytes, Mapping)):
        return True
    if origin in (typing.Union, types.UnionType):
        members = [member for member in get_args(annotation) if member is not type(None)]
        return len(members) == 1 and _plan_has_many_outputs(members[0])
    return False


def _resolve_one(contract: type[Any], field_name: str, marker: dict[str, Any]) -> ExtractorBinding | None:
    config = dict(marker.get('config') or {})
    plan = config.get(_PLAN_CONFIG_KEY)
    if isinstance(plan, Mapping):
        annotation = contract.model_fields[field_name].annotation
        many = _plan_has_many_outputs(annotation)
        plan_payload = validate_extraction_plan(plan)
        plan_fingerprint = hashlib.sha256(
            json.dumps(plan_payload, sort_keys=True, separators=(',', ':')).encode()
        ).hexdigest()[:16]

        async def execute_plan(row: ExtractionRow) -> Any:
            return await _execute_plan(row, plan_payload, many=many)

        spec = ExtractorSpec(
            resolver_id=f'plan:{plan_fingerprint}',
            version=str(marker.get('version') or '1'),
            source='explicit',
            reference=f'yosoi.plan:{plan_fingerprint}',
            config={key: value for key, value in config.items() if key != _PLAN_CONFIG_KEY},
            plan=plan_payload,
            portable=True,
        )
        return ExtractorBinding(field_name, execute_plan, spec)

    explicit = marker.get('reference')
    if isinstance(explicit, str):
        marker_source = marker.get('source', 'explicit')
        source: ExtractorSource = marker_source if marker_source in typing.get_args(ExtractorSource) else 'explicit'
        spec, fn = extractor_spec_for_callable(
            explicit,
            source=source,
            key=marker.get('key'),
            version=marker.get('version'),
            config=marker.get('config'),
        )
        batch_fields = marker.get('batch_fields')
        resolved_batch = tuple(batch_fields) if isinstance(batch_fields, (list, tuple)) else ()
        if resolved_batch:
            spec = spec.model_copy(update={'batch_fields': resolved_batch})
        return ExtractorBinding(field_name, fn, spec, batch_fields=resolved_batch)

    bound_method = marker.get('bound_method')
    method_name = bound_method if isinstance(bound_method, str) else f'extract_{field_name}'
    if hasattr(contract, method_name):
        fn = getattr(contract, method_name)
        spec, resolved = extractor_spec_for_callable(
            fn,
            source='method',
            key=marker.get('key'),
            version=marker.get('version'),
            config=marker.get('config'),
        )
        batch_fields = marker.get('batch_fields')
        resolved_batch = tuple(batch_fields) if isinstance(batch_fields, (list, tuple)) else ()
        if resolved_batch:
            spec = spec.model_copy(update={'batch_fields': resolved_batch})
        return ExtractorBinding(field_name, resolved, spec, batch_fields=resolved_batch)

    annotation = contract.model_fields[field_name].annotation
    hook_type = _hook_type(annotation)
    if hook_type is not None and hasattr(hook_type, '__yosoi_extract__'):
        fn = hook_type.__yosoi_extract__
        spec, resolved = extractor_spec_for_callable(
            fn,
            source='annotation',
            key=marker.get('key'),
            version=marker.get('version'),
            config=marker.get('config'),
        )
        return ExtractorBinding(field_name, resolved, spec)

    registry_keys = [f'annotation:{annotation_identity(annotation)}']
    extra = contract.model_fields[field_name].json_schema_extra
    yosoi_type = extra.get('yosoi_type') if isinstance(extra, dict) else None
    if isinstance(yosoi_type, str):
        registry_keys.append(f'semantic:{yosoi_type}')
    candidates = [_EXTRACTOR_REGISTRY[key] for key in registry_keys if key in _EXTRACTOR_REGISTRY]
    if len(candidates) > 1 and len({candidate.spec.fingerprint for candidate in candidates}) > 1:
        raise ExtractorResolutionError(
            f'{contract.__name__}.{field_name} has ambiguous exact registry extractors: '
            + ', '.join(candidate.spec.resolver_id for candidate in candidates)
        )
    if candidates:
        entry = candidates[0]
        spec = entry.spec.model_copy(update={'config': {**entry.spec.config, **dict(marker.get('config') or {})}})
        return ExtractorBinding(field_name, entry.fn, spec)
    return None


def _hook_type(annotation: Any) -> type[Any] | None:
    origin = get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        union_args = [arg for arg in get_args(annotation) if arg is not type(None)]
        return _hook_type(union_args[0]) if len(union_args) == 1 else None
    if origin is list:
        list_args = get_args(annotation)
        return list_args[0] if list_args and isinstance(list_args[0], type) else None
    return annotation if isinstance(annotation, type) else None


def _load_callable(reference: str) -> Callable[[ExtractionRow], Any]:
    if ':' not in reference:
        raise ExtractorResolutionError(f'extractor reference must be "module:qualname", got {reference!r}')
    module_name, qualname = reference.split(':', 1)
    try:
        obj: Any = importlib.import_module(module_name)
        for part in qualname.split('.'):
            obj = getattr(obj, part)
    except (ImportError, AttributeError) as exc:
        raise ExtractorResolutionError(f'cannot import extractor {reference!r}: {exc}') from exc
    if not callable(obj):
        raise ExtractorResolutionError(f'extractor reference {reference!r} is not callable')
    return typing.cast(Callable[[ExtractionRow], Any], obj)


def _validate_callable(fn: Callable[..., Any], label: str) -> None:
    call = typing.cast(Any, fn).__class__.__call__
    if inspect.isasyncgenfunction(fn) or (call is not None and inspect.isasyncgenfunction(call)):
        raise ExtractorResolutionError(f'extractor {label!r} is an async generator; return one awaitable value instead')
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError) as exc:
        raise ExtractorResolutionError(f'cannot inspect extractor {label!r}') from exc
    positional = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD)
    ]
    required_kwonly = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind == parameter.KEYWORD_ONLY and parameter.default is parameter.empty
    ]
    if len(positional) != 1 or required_kwonly:
        raise ExtractorResolutionError(
            f'extractor {label!r} must accept exactly one positional ExtractionRow argument; got {signature}'
        )


def run_extraction_sync(awaitable: Coroutine[Any, Any, T], *, async_name: str) -> T:
    """Run an async extraction boundary when no event loop is already active."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    close = getattr(awaitable, 'close', None)
    if callable(close):
        close()
    raise RuntimeError(f'cannot use this synchronous extraction API inside an event loop; await {async_name} instead')


def runtime_fingerprint(
    *,
    page_html: str,
    row_html: str,
    url: str,
    root_scope: str,
    field_fingerprint: str,
    binding: ExtractorBinding,
    evidence: Iterable[ExtractionEvidence],
    validation_result: ValidationResult,
    value: Any = None,
) -> ExtractorFingerprint:
    """Build a content-free execution fingerprint; ``value`` affects only a size band."""
    from yosoi.fingerprints.generalization import route_template
    from yosoi.generalization.fingerprint import PageFingerprint

    page_fp = PageFingerprint.of(page_html)
    evidence_tuple = tuple(evidence)
    sources = tuple(dict.fromkeys(item.source for item in evidence_tuple))
    operations = tuple(
        dict.fromkeys(
            hashlib.sha256(f'{item.source}:{item.operation}:{item.target_fingerprint}'.encode()).hexdigest()[:16]
            for item in evidence_tuple
        )
    )
    opaque = not evidence_tuple or (
        any(item.source == 'raw_html' for item in evidence_tuple)
        and not any(item.source != 'raw_html' for item in evidence_tuple)
    )
    return ExtractorFingerprint(
        page_structure=hashlib.sha256(
            ('\n'.join(sorted(page_fp.skeleton)) + '\n' + '\n'.join(sorted(page_fp.semantic))).encode()
        ).hexdigest()[:24],
        row=RowFingerprint.of(row_html),
        route_template=route_template(url),
        root_scope=root_scope,
        field_fingerprint=field_fingerprint,
        resolver_id=binding.spec.resolver_id,
        resolver_version=binding.spec.version,
        resolver_source=binding.spec.source,
        evidence_sources=sources,
        operations=operations,
        validation_result=validation_result,
        cardinality_band=_value_cardinality_band(value),
        opaque=opaque or binding.spec.opaque,
    )


def _value_cardinality_band(value: Any) -> str:
    if value is None:
        return '0'
    if isinstance(value, (str, bytes, dict)):
        return '1'
    if isinstance(value, Iterable):
        try:
            return _cardinality_band(len(value))  # type: ignore[arg-type]
        except TypeError:
            return 'many'
    return '1'


def _cardinality_band(count: int) -> str:
    if count <= 0:
        return '0'
    if count == 1:
        return '1'
    if count <= 4:
        return '2-4'
    if count <= 16:
        return '5-16'
    return '17+'


__all__ = [
    'ExtractionEvidence',
    'ExtractionOutcome',
    'ExtractionRow',
    'ExtractorBinding',
    'ExtractorFieldError',
    'ExtractorFingerprint',
    'ExtractorNoMatch',
    'ExtractorResolutionError',
    'ExtractorSpec',
    'RowFingerprint',
    'annotation_identity',
    'callable_reference',
    'extraction',
    'extractions',
    'extractor_spec_for_callable',
    'register_extractor',
    'resolve_extractor_bindings',
    'run_extraction_sync',
    'runtime_fingerprint',
    'values',
]
