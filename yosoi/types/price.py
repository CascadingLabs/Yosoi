"""Price type for Yosoi contracts."""

import re

from yosoi.types.registry import CoercionConfig, register_coercion

_ZERO_VALUE_WORDS = ('free', 'complimentary', 'gratis')


@register_coercion('price', description='A monetary price value', currency_symbol=None, require_decimals=False)
def Price(v: object, config: CoercionConfig, source_url: str | None = None) -> float | None:
    """Configure a price field with optional currency and decimal enforcement.

    Example::

        class Shop(Contract):
            price: float = ys.Price(currency_symbol='€', require_decimals=True)
    """
    currency_symbol: str | None = config.get('currency_symbol')
    require_decimals: bool = config.get('require_decimals', False)

    if not isinstance(v, str):
        return float(str(v))

    cleaned = v.strip().lower()

    if any(word in cleaned for word in _ZERO_VALUE_WORDS):
        return 0.0

    if currency_symbol and currency_symbol not in v:
        raise ValueError(f'Price missing required currency symbol: {currency_symbol!r}')

    match = re.search(r'\d+[.,\d]*', cleaned)
    if not match:
        return None

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
