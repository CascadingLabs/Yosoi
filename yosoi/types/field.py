"""Yosoi-aware Field wrapper."""

from typing import Any, cast

import pydantic
import pydantic.fields


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


def Field(
    hint: str | None = None,
    frozen: bool = False,
    selector: str | None = None,
    delimiter: str | None = None,
    **kwargs: Any,
) -> pydantic.fields.FieldInfo:
    """Yosoi-aware Field wrapper that stores hints in json_schema_extra.

    Args:
        hint: Optional scraping hint that guides the AI selector discovery.
        frozen: If True, marks the field as frozen (selector won't be re-discovered).
        selector: Optional CSS selector override. When set, AI discovery is skipped
            for this field and the provided selector is used directly.
        delimiter: Optional regex pattern for splitting delimited strings in list fields.
            Defaults to comma/semicolon/and splitting when not set.
        **kwargs: Additional arguments forwarded to pydantic.Field.

    Returns:
        A pydantic FieldInfo with Yosoi-specific metadata in json_schema_extra.

    """
    extra: dict[str, Any] = dict(kwargs.pop('json_schema_extra', {}) or {})
    if hint:
        extra['yosoi_hint'] = hint
    if frozen:
        extra['yosoi_frozen'] = True
    if selector:
        extra['yosoi_selector'] = selector
    if delimiter:
        extra['yosoi_delimiter'] = delimiter
    return cast(pydantic.fields.FieldInfo, pydantic.Field(json_schema_extra=extra or None, **kwargs))
