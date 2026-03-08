"""Central coercion dispatch for Yosoi semantic types."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from yosoi.types.datetime import coerce_datetime
from yosoi.types.price import coerce_price
from yosoi.types.rating import coerce_rating
from yosoi.types.url import coerce_url


def _clean_str(v: object, _config: dict[str, Any]) -> str:
    return str(v).strip() if v is not None else ''


# Maps yosoi_type -> coercion function(value, config) -> coerced_value
# URL is handled specially because it needs source_url context.
_COERCERS: dict[str, Callable[..., Any]] = {
    'price': coerce_price,
    'datetime': coerce_datetime,
    'rating': coerce_rating,
    'title': _clean_str,
    'author': _clean_str,
    'body_text': _clean_str,
}


def dispatch(
    yosoi_type: str,
    value: object,
    config: dict[str, Any],
    source_url: str | None = None,
) -> Any:
    """Dispatch coercion for a given yosoi_type.

    Args:
        yosoi_type: The semantic type identifier (e.g. 'price', 'url').
        value: Raw scraped value to coerce.
        config: Full json_schema_extra dict with coercion parameters.
        source_url: Optional source URL for resolving relative URLs.

    Returns:
        The coerced value.

    Raises:
        ValueError: If the value cannot be coerced.

    """
    if value is None:
        return value

    if yosoi_type == 'url':
        return coerce_url(value, config, source_url=source_url)

    coercer = _COERCERS.get(yosoi_type)
    if coercer is None:
        return value
    return coercer(value, config)
