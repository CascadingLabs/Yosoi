"""Datetime type for Yosoi contracts."""

from __future__ import annotations

import datetime as dt_module
import re

import dateparser

from yosoi.types.registry import KIND_TEXT, CoercionConfig, SemanticRule, register_coercion

# Language-agnostic "Label:" prefix (dateparser returns None on any labelled date, in any
# language). Matches up to ~4 leading letter-words then a colon — a digit anywhere before
# the colon breaks the match, so real dates with times ("Jan 5 2020 10:30") are never eaten.
_LABEL_RE = re.compile(r'^(?:[^\W\d_]+\s+){0,3}[^\W\d_]+\s*[:：]\s*')

# No-colon label idioms dateparser can't strip itself. A DEFAULT, not the SSoT: override
# per field via ys.Datetime(strip_prefixes=(...)). Empty tuple disables it entirely.
_DEFAULT_STRIP_PREFIXES = ('posted on',)


@register_coercion(
    'datetime',
    description='A date or datetime value',
    semantic=SemanticRule(kind=KIND_TEXT, max_chars=80),
    assume_utc=True,
    past_only=False,
    as_iso=True,
    strip_prefixes=_DEFAULT_STRIP_PREFIXES,
)
def Datetime(v: object, config: CoercionConfig, source_url: str | None = None) -> dt_module.datetime | str:
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

    # Strip a leading "Label:" segment in any language (dateparser can't).
    raw = _LABEL_RE.sub('', raw, count=1).strip()

    # Strip no-colon label idioms (overridable default, never the source of truth).
    strip_prefixes: tuple[str, ...] = config.get('strip_prefixes', _DEFAULT_STRIP_PREFIXES)
    lower = raw.lower()
    for prefix in strip_prefixes:
        if lower.startswith(prefix):
            raw = raw[len(prefix) :].strip()
            break

    # Split on · separator (e.g. "Author · date") and take last segment
    if '·' in raw:
        raw = raw.split('·')[-1].strip()

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
