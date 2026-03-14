"""Datetime type for Yosoi contracts."""

from __future__ import annotations

import datetime as dt_module
from typing import Any

import dateparser

from yosoi.types.registry import register_coercion

_STRIP_PREFIXES = ('published:', 'updated:', 'posted on')


@register_coercion('datetime', description='A date or datetime value', assume_utc=True, past_only=False, as_iso=True)
def Datetime(v: object, config: dict[str, Any], source_url: str | None = None) -> dt_module.datetime | str:
    """Configure a datetime field with timezone, tense, and format options.

    Example::

        class Blog(Contract):
            published: str = ys.Datetime(past_only=True)
            updated: datetime = ys.Datetime(as_iso=False)
    """
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

    parsed: dt_module.datetime | None = dateparser.parse(raw, settings=settings)
    if not parsed:
        raise ValueError(f'Could not parse datetime from string: {raw!r}')

    if past_only and parsed > dt_module.datetime.now(dt_module.timezone.utc):
        raise ValueError(f'Temporal hallucination: extracted date {parsed} is in the future')

    if as_iso:
        return parsed.isoformat()
    return parsed
