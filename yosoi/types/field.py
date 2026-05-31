"""Yosoi-aware Field wrapper."""

from collections.abc import Iterable
from typing import Any, cast

import pydantic
import pydantic.fields

from yosoi.types.filetypes import SUPPORTED_PARSE, normalize_allowed_types


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
    parse: str | None = None,
    max_bytes: int | None = None,
    **kwargs: Any,
) -> pydantic.fields.FieldInfo:
    """Declare a contract field whose value is a file downloaded in the live browser tab.

    Like :func:`js`, this is an *action field* (excluded from CSS discovery) — its value
    is produced by performing an action during fetch, not by a selector over static HTML.

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
        parse: Optional post-download transform — ``'csv'`` → ``list[dict]``,
            ``'json'`` → parsed object. ``None`` keeps the raw ``DownloadRecord``.
        max_bytes: Per-file size cap; the download aborts past it.
        **kwargs: Forwarded to ``pydantic.Field``.

    Returns:
        A pydantic FieldInfo with ``yosoi_action`` (``type='file'``) metadata.

    Raises:
        ValueError: When the trigger source / ``parse`` / ``allowed_types`` are invalid.
    """
    sources = {'trigger': trigger, 'href': href, 'url': url, 'description': description}
    given = [name for name, value in sources.items() if value]
    if len(given) != 1:
        raise ValueError(
            'ys.File() requires exactly one of trigger= (click), href= (link selector), '
            'url= (literal URL), or description= (discovery-driven); got: ' + (', '.join(given) or 'none')
        )
    if parse is not None and parse not in SUPPORTED_PARSE:
        raise ValueError(f'ys.File(parse={parse!r}) is unsupported; use one of {SUPPORTED_PARSE} or None')
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
        'parse': parse,
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
