"""Rating type for Yosoi contracts."""

import re
from typing import Any

from yosoi.types.registry import register_coercion

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


@register_coercion('rating', description='A rating or review score', as_float=False, scale=5)
def Rating(v: object, config: dict[str, Any], source_url: str | None = None) -> float | str:
    """Configure a rating field with optional numeric conversion and scale validation.

    Example::

        class Shop(Contract):
            rating: float = ys.Rating(as_float=True, scale=10)
            stars: str = ys.Rating()
    """
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
