"""Price type for Yosoi contracts."""

import re

from yosoi.types.registry import KIND_NUMERIC, CoercionConfig, SemanticRule, register_coercion

# Default zero-price words. A DEFAULT, not the source of truth: override per field via
# ys.Price(zero_value_words=('無料', 'gratuit', ...)) for non-English locales.
_ZERO_VALUE_WORDS = ('free', 'complimentary', 'gratis')


@register_coercion(
    'price',
    description='A monetary price value',
    semantic=SemanticRule(kind=KIND_NUMERIC, max_chars=50),
    currency_symbol=None,
    require_decimals=False,
    zero_value_words=_ZERO_VALUE_WORDS,
)
def Price(v: object, config: CoercionConfig, source_url: str | None = None) -> float:
    """Configure a price field with optional currency and decimal enforcement.

    Example::

        class Shop(Contract):
            price: float = ys.Price(currency_symbol='€', require_decimals=True)
    """
    currency_symbol: str | None = config.get('currency_symbol')
    require_decimals: bool = config.get('require_decimals', False)
    zero_value_words: tuple[str, ...] = config.get('zero_value_words', _ZERO_VALUE_WORDS)

    if not isinstance(v, str):
        return float(str(v))

    cleaned = v.strip().lower()

    match = re.search(r'\d+[.,\d]*', cleaned)
    if not match:
        # No number present — honour an explicit zero-value word, matched whole-word so
        # "free shipping over $50" is NOT zero (that string has a number, handled below).
        if any(re.search(rf'\b{re.escape(word)}\b', cleaned.lower()) for word in zero_value_words):
            return 0.0
        raise ValueError(f'No numeric value found in: {v!r}')

    if currency_symbol and currency_symbol not in v:
        raise ValueError(f'Price missing required currency symbol: {currency_symbol!r}')

    num_str = match.group(0)

    if require_decimals and '.' not in num_str and ',' not in num_str:
        raise ValueError(f'Price lacks required decimal precision: {v!r}')

    if '.' in num_str and ',' in num_str:
        if num_str.rfind(',') > num_str.rfind('.'):
            # EU format: 1.234,56 -> 1234.56
            num_str = num_str.replace('.', '').replace(',', '.')
        else:
            # US format: 1,234.56 -> 1234.56
            num_str = num_str.replace(',', '')
    elif ',' in num_str:
        # Bare comma decimal: 49,99 -> 49.99
        num_str = num_str.replace(',', '.')

    return float(num_str)
