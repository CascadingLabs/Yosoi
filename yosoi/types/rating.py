"""Rating type for Yosoi contracts."""

import re
from typing import Any

from yosoi.types.field import Field

_WORD_MAP = {
    'one': 1,
    'two': 2,
    'three': 3,
    'four': 4,
    'five': 5,
    'six': 6,
    'seven': 7,
    'eight': 8,
    'nine': 9,
    'ten': 10,
}


def coerce_rating(v: object, config: dict[str, Any]) -> float | str:
    """Coerce a raw scraped value into a rating (float or cleaned string)."""
    as_float: bool = config.get('as_float', False)
    scale: int = config.get('scale', 5)

    raw = str(v).strip()

    if not as_float:
        return raw

    lower = raw.lower()
    for word, num in _WORD_MAP.items():
        if lower.startswith(word):
            return float(num)

    match = re.search(r'(\d+(?:\.\d+)?)', raw)
    if match:
        val = float(match.group(1))
        if val > scale:
            raise ValueError(f'Extracted rating {val} exceeds configured scale of {scale}')
        return val

    raise ValueError(f'Could not extract numeric rating from: {raw!r}')


def Rating(
    as_float: bool = False,
    scale: int = 5,
    description: str = 'A rating or review score',
    **kwargs: Any,
) -> Any:
    """Configure a rating field with optional numeric conversion and scale validation.

    Args:
        as_float: Convert word/fraction ratings to float. Defaults to False (returns cleaned str).
        scale: Max expected rating value. Defaults to 5.
        description: Field description for schema/manifest.
        **kwargs: Additional arguments forwarded to Field.

    Example::

        class Shop(Contract):
            rating: float = ys.Rating(as_float=True, scale=10)
            stars: str = ys.Rating()
    """
    return Field(
        description=description,
        json_schema_extra={
            'yosoi_type': 'rating',
            'as_float': as_float,
            'scale': scale,
        },
        **kwargs,
    )
