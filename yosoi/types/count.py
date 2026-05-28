"""Count type for Yosoi contracts — non-negative integer counters.

The canonical "number of X" field: upvotes, comments, reviews, views, likes,
followers, replies. Distinct from :func:`Rating` (capped scale, decimals
allowed) and :func:`Price` (currency unit, decimals, may be negative for
refunds): Count is unbounded, must be non-negative, and is always an integer.

Coercion handles the formats real-world scrapers see:
  * plain digits: ``'42'`` → ``42``
  * thousands separators: ``'12,345'`` → ``12345``
  * SI suffixes: ``'4.2K'`` / ``'1.3M'`` / ``'2B'`` → ``4200`` / ``1300000`` / ``2000000000``
  * whitespace / labels: ``'  9 comments'`` → ``9`` (numeric prefix wins)
  * explicit zero: ``'0'``, ``'none'`` → ``0``

Validation rejects anything that resolves to a negative number — a "count of
-3" is almost always wrong-selector output, not real data.
"""

import re

from yosoi.types.registry import CoercionConfig, register_coercion

# SI-style multipliers seen on reddit/YouTube/Twitter etc.
_SUFFIX_MULTIPLIERS: dict[str, int] = {
    'k': 1_000,
    'm': 1_000_000,
    'b': 1_000_000_000,
    'g': 1_000_000_000,  # some sites use G for billion
}

_NUMERIC_PREFIX = re.compile(r'^\s*([-+]?\d+(?:[.,]\d+)?)\s*([kmbgKMBG])?', re.IGNORECASE)


@register_coercion('count', description='Non-negative integer counter (upvotes, comments, views, …)')
def Count(v: object, config: CoercionConfig, source_url: str | None = None) -> int:
    """Coerce a Count value to a non-negative ``int``.

    Args:
        v: Raw extracted value — may be an int, str, or anything stringifiable.
        config: Reserved for future knobs (e.g. ``allow_negative=False`` is
            the implicit default; we may surface ``min_value`` / ``max_value``
            later if a smoke test needs it).
        source_url: Unused; present for the registered-coercion signature.

    Returns:
        The parsed integer count.

    Raises:
        ValueError: If the value contains no parseable number or resolves to
            a negative value (almost always wrong-selector output).

    Example::

        class RedditPost(Contract):
            score: int = ys.Count()
            comment_count: int = ys.Count()
    """
    if v is None:
        raise ValueError('Count cannot coerce None')
    if isinstance(v, bool):
        # bool is an int subclass — guard so True/False don't silently coerce to 1/0.
        raise ValueError(f'Count cannot coerce bool value {v!r}')
    if isinstance(v, int):
        if v < 0:
            raise ValueError(f'Count must be non-negative, got {v}')
        return v
    if isinstance(v, float):
        if v != v or v < 0:  # NaN or negative
            raise ValueError(f'Count must be non-negative integer-shaped, got {v}')
        return int(v)

    raw = str(v).strip()
    if not raw:
        raise ValueError('Count cannot coerce empty value')

    # Special-case "none"/"no"/etc. → 0, common on count-of-replies fields.
    if raw.lower() in ('none', 'no', 'no comments', 'no replies', '-'):
        return 0

    match = _NUMERIC_PREFIX.match(raw)
    if not match:
        raise ValueError(f'Could not parse a Count from: {raw!r}')

    number_part = match.group(1).replace(',', '')
    multiplier_part = (match.group(2) or '').lower()

    try:
        base = float(number_part)
    except ValueError as exc:
        raise ValueError(f'Could not parse a Count from: {raw!r}') from exc

    multiplier = _SUFFIX_MULTIPLIERS.get(multiplier_part, 1)
    value = int(base * multiplier)
    if value < 0:
        raise ValueError(f'Count must be non-negative, got {value} from {raw!r}')
    return value
