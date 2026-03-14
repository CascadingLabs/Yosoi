"""Central coercion dispatch for Yosoi semantic types."""

from __future__ import annotations

from collections.abc import Mapping

from yosoi.types.registry import CoercedValue, _registry


def dispatch(
    yosoi_type: str,
    value: object,
    config: Mapping[str, object],
    source_url: str | None = None,
) -> CoercedValue | object:
    """Dispatch coercion for a given yosoi_type.

    Args:
        yosoi_type: The semantic type identifier (e.g. 'price', 'url').
        value: Raw scraped value to coerce.
        config: Full json_schema_extra dict with coercion parameters.
        source_url: Optional source URL for resolving relative URLs.

    Returns:
        The coerced value, or the raw value unchanged if no coercer is registered.

    Raises:
        ValueError: If the value cannot be coerced.

    """
    if value is None:
        return None

    coercer = _registry.get(yosoi_type)
    if coercer is None:
        return value
    return coercer(value, config, source_url=source_url)
