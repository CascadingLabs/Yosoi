"""Yosoi-aware Field wrapper."""

from typing import Any, cast

import pydantic
import pydantic.fields


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
