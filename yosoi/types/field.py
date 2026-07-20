"""Yosoi-aware Field wrapper."""

import json
from collections.abc import Callable, Iterable, Mapping
from typing import Any, cast

import pydantic
import pydantic.fields
from pydantic_core import PydanticUndefined
from typing_extensions import Self

from yosoi.types.filetypes import normalize_allowed_types

_PLAN_CONFIG_KEY = '__yosoi_plan__'


class ExtractorPlanField(pydantic.fields.FieldInfo):
    """FieldInfo carrying fluent plan operations until Pydantic copies the field."""

    # Pydantic marks FieldInfo final for static consumers. This private implementation
    # subtype is required so fluent methods remain available while the assigned value is
    # still genuine field metadata rather than a model default.
    def __init__(self, plan: Mapping[str, Any]) -> None:
        """Create required Pydantic field metadata from one plan snapshot."""
        super().__init__(
            default=PydanticUndefined,
            json_schema_extra={
                'yosoi_extractor': {
                    'reference': None,
                    'key': None,
                    'version': '1',
                    'config': {_PLAN_CONFIG_KEY: dict(plan)},
                }
            },
        )

    @property
    def plan(self) -> dict[str, Any]:
        """Return a copy of the serialized extraction plan."""
        extra = self.json_schema_extra
        marker = extra.get('yosoi_extractor') if isinstance(extra, dict) else None
        config = marker.get('config') if isinstance(marker, dict) else None
        plan = config.get(_PLAN_CONFIG_KEY) if isinstance(config, dict) else None
        return dict(plan) if isinstance(plan, dict) else {}

    def map(self, using: Callable[[Any], Any] | str) -> Self:
        """Map each selected value through one importable deterministic callable."""
        from yosoi.models.extraction import callable_reference

        reference = using if isinstance(using, str) else callable_reference(using)
        plan = self.plan
        maps = list(plan.get('maps') or [])
        maps.append(reference)
        plan['maps'] = maps
        return type(self)(plan)

    def compact(self) -> Self:
        """Discard ``None`` values after mapping; an empty collection remains valid."""
        plan = self.plan
        plan['compact'] = True
        return type(self)(plan)


def extractor_plan_field(
    selector: Any,
    *,
    operation: str,
    attribute: str | None = None,
) -> ExtractorPlanField:
    """Build fluent extractor metadata from a CSS/XPath selector terminal."""
    if getattr(selector, 'type', None) not in {'css', 'xpath'}:
        raise TypeError('fluent extractor plans currently support only ys.css() and ys.xpath()')
    return ExtractorPlanField(
        {
            'selector': selector.model_dump(mode='json'),
            'operation': operation,
            'attribute': attribute,
            'maps': [],
            'compact': False,
        }
    )


def Extractor(
    default: Any = PydanticUndefined,
    *,
    default_factory: Callable[[], Any] | None = None,
    using: Callable[[Any], Any] | str | None = None,
    key: str | None = None,
    version: str | None = None,
    config: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> pydantic.fields.FieldInfo:
    """Declare an async-capable, deterministic extractor field.

    The annotation remains the field's real value type. This marker stores only
    extraction configuration; it never becomes a model value and never performs
    fetching, browser actions, or LLM discovery.

    A fluent selector plan, ``using=`` callable, or ``@ys.extraction`` binding is
    explicit. Without one, resolution falls back to legacy ``extract_<field>``
    methods, output-type ``__yosoi_extract__`` hooks, then an exact registry entry.
    """
    from yosoi.models.extraction import extractor_spec_for_callable

    if default is not PydanticUndefined and default_factory is not None:
        raise TypeError('ys.Extractor() cannot specify both default and default_factory')

    resolved_config = dict(config or {})
    try:
        json.dumps(resolved_config, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise TypeError('extractor config must be JSON-serializable') from exc

    reference: str | None = None
    resolved_key = key
    resolved_version = version
    if using is not None:
        spec, _fn = extractor_spec_for_callable(
            using,
            source='explicit',
            key=key,
            version=version,
            config=config,
        )
        reference = spec.reference
        resolved_key = spec.resolver_id if key is not None else None
        resolved_version = spec.version

    extra: dict[str, Any] = dict(kwargs.pop('json_schema_extra', {}) or {})
    if 'yosoi_action' in extra or 'yosoi_selector' in extra:
        raise TypeError('ys.Extractor() cannot also be configured as an action or selector field')
    extra['yosoi_extractor'] = {
        'reference': reference,
        'key': resolved_key,
        'version': resolved_version,
        'config': resolved_config,
    }

    field_kwargs: dict[str, Any] = {**kwargs, 'json_schema_extra': extra}
    if default_factory is not None:
        field_kwargs['default_factory'] = default_factory
        return cast(pydantic.fields.FieldInfo, pydantic.Field(**field_kwargs))
    return cast(pydantic.fields.FieldInfo, pydantic.Field(default, **field_kwargs))


def _extractor_batch(*, batch_fields: tuple[str, ...], **kwargs: Any) -> pydantic.fields.FieldInfo:
    """Rehydrate recipe batch metadata without expanding the public ``Extractor`` API."""
    field_info = Extractor(**kwargs)
    extra = field_info.json_schema_extra
    marker = extra.get('yosoi_extractor') if isinstance(extra, dict) else None
    if not isinstance(marker, dict):  # pragma: no cover - Extractor invariant
        raise TypeError('batch extractor metadata could not be initialized')
    marker['batch_fields'] = batch_fields
    return field_info


def js(
    script: str | None = None,
    *,
    description: str | None = None,
    **kwargs: Any,
) -> pydantic.fields.FieldInfo:
    """Declare a contract field extracted by a JS program run in the live browser tab.

    Two modes:

    **Hand-authored** — provide ``script``. The expression is evaluated as-is
    on every fetch. No LLM involved::

        signals: dict = ys.js("(() => ({ has_alita: !!window.__alita__ }))()")

    **Discovery-driven** — omit ``script``, provide ``description``. Yosoi's
    :class:`JsDiscoveryOrchestrator` writes and verifies the script once per
    domain, then caches it (CAS-92)::

        signals: dict = ys.js(description="Detect Alita embed and competitor widgets")

    Args:
        script: JavaScript IIFE to evaluate. ``None`` triggers JS discovery.
        description: Human-readable description used by the LLM during discovery.
            Required when ``script`` is ``None``.
        **kwargs: Additional arguments forwarded to ``pydantic.Field``
            (e.g. ``default``, ``description`` as a pydantic field description).

    Returns:
        A pydantic FieldInfo with ``yosoi_action`` metadata.

    Raises:
        ValueError: When neither ``script`` nor ``description`` is provided.

    """
    if script is None and not description:
        raise ValueError('ys.js() requires either script= (hand-authored) or description= (discovery-driven)')
    extra: dict[str, Any] = dict(kwargs.pop('json_schema_extra', {}) or {})
    extra['yosoi_action'] = {
        'type': 'js',
        'script': script,
        'description': description,
    }
    # Propagate description to pydantic field if not already set
    if description and 'description' not in kwargs:
        kwargs['description'] = description
    return cast(pydantic.fields.FieldInfo, pydantic.Field(json_schema_extra=extra, **kwargs))


def File(
    *,
    trigger: str | None = None,
    href: str | None = None,
    url: str | None = None,
    description: str | None = None,
    allowed_types: Iterable[str] | None = None,
    max_bytes: int | None = None,
    **kwargs: Any,
) -> pydantic.fields.FieldInfo:
    """Declare a contract field whose value is a file downloaded in the live browser tab.

    Like :func:`js`, this is an *action field* (excluded from CSS discovery) — its value
    is produced by performing an action during fetch, not by a selector over static HTML.

    ── DESIGN DECISION: annotation-directed output (opinionated, ours) ──────────────────
    What you GET from a ys.File field is decided by the field's **declared Python type**,
    NOT by a parse= keyword. This is deliberate and load-bearing — it keeps ys.File
    consistent with the rest of the contract API, where the type already *is* the meaning
    (``title: str = ys.Title()``, ``price: float = ys.Price()``) and with ``ys.js()``,
    whose output is validated against its declared type (CAS-104). A separate ``parse=``
    knob would be a second source of truth for "what shape do I want" — so we don't have
    one. The supported annotations (resolved + enforced at contract-definition time by
    ``yosoi.models.download.output_view_for_annotation``; anything else raises there):

        report: ys.DownloadRecord = ys.File(...)   # provenance handle (path/sha256/size/ct)
        report: Path              = ys.File(...)   # the quarantined file path
        blob:   bytes             = ys.File(...)   # raw bytes
        text:   str               = ys.File(...)   # decoded text
        rows:   list[dict]        = ys.File(...)   # parsed (csv/json by content-type)
        rows:   list[MyRow]       = ys.File(...)   # parsed + per-row validated via MyRow
        obj:    dict | MyModel    = ys.File(...)   # parsed JSON, validated against the type

    For 'parsed' types the file is parsed (csv vs json chosen by content-type) and then run
    through the contract's TypeAdapter oracle (``Contract.coerce_field``), so a ``list[MyRow]``
    field yields typed, semantically-coerced rows for free. A ``DownloadRecord`` is always
    produced internally for provenance regardless of which view the annotation selects.
    Trade-off accepted: behavior keyed off the annotation is slightly less explicit than a
    kwarg, but Yosoi is opinionated and one-blessed-path beats two redundant knobs here.
    DOC FOLLOW-UP: this decision needs first-class docs (see CAS-106). FUTURE: a definition-
    time allowed_types↔annotation compatibility guard, and a codec hint for tsv/ndjson.
    ─────────────────────────────────────────────────────────────────────────────────────

    Exactly one trigger source must be given:

    - ``trigger`` — CSS selector to click; the resulting download is captured
      (``retrigger`` mode, the durable default — survives rotating/signed URLs and runs
      in the authenticated tab).
    - ``href`` — CSS selector whose element yields a link to download directly.
    - ``url`` — a literal URL to download (``refetch`` mode).
    - ``description`` — human description; the trigger is discovered once and cached.

    Safety (opt-in, default-deny): ``allowed_types`` names the file types you accept
    (friendly names like ``'csv'``/``'mp4'``, bare extensions, or explicit MIME types).
    A download whose magic bytes / content-type don't match is rejected and purged. With
    no ``allowed_types`` here and no run-wide allowlist, downloads fail fast — nothing is
    fetched "just in case". Downloads also require the run-level ``allow_downloads`` opt-in.

    Args:
        trigger: CSS selector to click to start the download.
        href: CSS selector whose element's link is downloaded directly.
        url: Literal URL to download.
        description: Description used to discover the trigger (cached after first run).
        allowed_types: Allowlist of accepted file types. Unknown names raise immediately.
        max_bytes: Per-file size cap; the download aborts past it.
        **kwargs: Forwarded to ``pydantic.Field``.

    Returns:
        A pydantic FieldInfo with ``yosoi_action`` (``type='file'``) metadata. The output
        view is resolved from the field's annotation later (definition-time), not here.

    Raises:
        ValueError: When the trigger source / ``allowed_types`` / ``max_bytes`` are invalid.
            (An unsupported field *type* raises later, at contract-definition time.)
    """
    sources = {'trigger': trigger, 'href': href, 'url': url, 'description': description}
    given = [name for name, value in sources.items() if value]
    if len(given) != 1:
        raise ValueError(
            'ys.File() requires exactly one of trigger= (click), href= (link selector), '
            'url= (literal URL), or description= (discovery-driven); got: ' + (', '.join(given) or 'none')
        )
    if max_bytes is not None and max_bytes <= 0:
        raise ValueError('ys.File(max_bytes=…) must be a positive byte count')
    normalized_allowed = normalize_allowed_types(allowed_types)  # validates names; raises on typo
    mode = 'refetch' if (href or url) else 'retrigger'
    extra: dict[str, Any] = dict(kwargs.pop('json_schema_extra', {}) or {})
    extra['yosoi_action'] = {
        'type': 'file',
        'mode': mode,
        'trigger': trigger,
        'href': href,
        'url': url,
        'description': description,
        'allowed_types': list(normalized_allowed),
        'max_bytes': max_bytes,
    }
    if description and 'description' not in kwargs:
        kwargs['description'] = description
    return cast(pydantic.fields.FieldInfo, pydantic.Field(json_schema_extra=extra, **kwargs))


def Field(
    frozen: bool = False,
    selector: str | None = None,
    delimiter: str | None = None,
    **kwargs: Any,
) -> pydantic.fields.FieldInfo:
    """Yosoi-aware Field wrapper that stores selector metadata in json_schema_extra.

    Per-field guidance for the LLM is supplied via the standard pydantic
    ``description=`` argument — there is no separate ``hint`` knob.

    Args:
        frozen: If True, marks the field as frozen (selector won't be re-discovered).
        selector: Optional CSS selector override. When set, AI discovery is skipped
            for this field and the provided selector is used directly.
        delimiter: Optional regex pattern for splitting delimited strings in list fields.
            Defaults to comma/semicolon/and splitting when not set.
        **kwargs: Additional arguments forwarded to pydantic.Field (e.g. ``description``).

    Returns:
        A pydantic FieldInfo with Yosoi-specific metadata in json_schema_extra.

    Raises:
        TypeError: If the removed ``hint`` argument is passed. Use ``description``.

    """
    if 'hint' in kwargs:
        raise TypeError('ys.Field(hint=...) was removed; pass per-field LLM guidance via description= instead')
    extra: dict[str, Any] = dict(kwargs.pop('json_schema_extra', {}) or {})
    if frozen:
        extra['yosoi_frozen'] = True
    if selector:
        extra['yosoi_selector'] = selector
    if delimiter:
        extra['yosoi_delimiter'] = delimiter
    return cast(pydantic.fields.FieldInfo, pydantic.Field(json_schema_extra=extra or None, **kwargs))
