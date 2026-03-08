"""Datetime type for Yosoi contracts."""

from __future__ import annotations

import datetime as dt_module
from typing import Any

import dateparser  # type: ignore[import-untyped]

from yosoi.types.field import Field

_STRIP_PREFIXES = ('published:', 'updated:', 'posted on')


def coerce_datetime(v: object, config: dict[str, Any]) -> dt_module.datetime | str:
    """Coerce a raw scraped value into a datetime or ISO 8601 string."""
    assume_utc: bool = config.get('assume_utc', True)
    past_only: bool = config.get('past_only', False)
    as_iso: bool = config.get('as_iso', True)

    raw = str(v).strip()

    lower = raw.lower()
    for prefix in _STRIP_PREFIXES:
        if lower.startswith(prefix):
            raw = raw[len(prefix) :].strip()
            break

    settings: dict[str, object] = {'RETURN_AS_TIMEZONE_AWARE': True}
    if assume_utc:
        settings['TIMEZONE'] = 'UTC'

    parsed = dateparser.parse(raw, settings=settings)
    if not parsed:
        raise ValueError(f'Could not parse datetime from string: {raw!r}')

    if past_only and parsed > dt_module.datetime.now(dt_module.timezone.utc):
        raise ValueError(f'Temporal hallucination: extracted date {parsed} is in the future')

    if as_iso:
        return parsed.isoformat()  # type: ignore[no-any-return]
    return parsed  # type: ignore[no-any-return]


def Datetime(
    assume_utc: bool = True,
    past_only: bool = False,
    as_iso: bool = True,
    description: str = 'A date or datetime value',
    **kwargs: Any,
) -> Any:
    """Configure a datetime field with timezone, tense, and format options.

    Args:
        assume_utc: Treat ambiguous timestamps as UTC. Defaults to True.
        past_only: Raise if parsed datetime is in the future. Defaults to False.
        as_iso: Return ISO 8601 string. Set False to return a datetime object. Defaults to True.
        description: Field description for schema/manifest.
        **kwargs: Additional arguments forwarded to Field.

    Example::

        class Blog(Contract):
            published: str = ys.Datetime(past_only=True)
            updated: datetime = ys.Datetime(as_iso=False)
    """
    return Field(
        description=description,
        json_schema_extra={
            'yosoi_type': 'datetime',
            'assume_utc': assume_utc,
            'past_only': past_only,
            'as_iso': as_iso,
        },
        **kwargs,
    )
