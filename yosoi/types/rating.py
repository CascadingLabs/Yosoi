"""Rating type for Yosoi contracts."""

import re

from yosoi.types.registry import KIND_NUMERIC, CoercionConfig, SemanticRule, matches_word, register_coercion

# Default English number-word map. A DEFAULT, not the source of truth: override per field
# via ys.Rating(word_map={'trois': 3, ...}) for non-English review sites.
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


@register_coercion(
    'rating',
    description='A rating or review score',
    semantic=SemanticRule(kind=KIND_NUMERIC, max_chars=50),
    as_float=False,
    scale=5,
    word_map=_WORD_MAP,
)
def Rating(v: object, config: CoercionConfig, source_url: str | None = None) -> float | str:
    """Configure a rating field with optional numeric conversion and scale validation.

    Example::

        class Shop(Contract):
            rating: float = ys.Rating(as_float=True, scale=10)
            stars: str = ys.Rating()
    """
    as_float: bool = config.get('as_float', False)
    scale: int = config.get('scale', 5)
    word_map: dict[str, int] = config.get('word_map', _WORD_MAP)

    raw = str(v).strip()

    if not as_float:
        return raw

    lower = raw.lower()
    for word, num in word_map.items():
        # Whole-word match — `startswith` wrongly matched "tens of reviews" → 10.
        # `matches_word` escapes the word and handles non-ASCII (CJK) keys safely.
        if matches_word(lower, word):
            return float(num)

    match = re.search(r'(\d+(?:\.\d+)?)', raw)
    if match:
        val = float(match.group(1))
        if val > scale:
            raise ValueError(f'Extracted rating {val} exceeds configured scale of {scale}')
        return val

    raise ValueError(f'Could not extract numeric rating from: {raw!r}')
