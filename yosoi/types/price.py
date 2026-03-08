"""Price type for Yosoi contracts."""

import re
from typing import Any

from yosoi.types.field import Field

_ZERO_VALUE_WORDS = ('free', 'complimentary', 'gratis')


def coerce_price(v: object, config: dict[str, Any]) -> float | None:
    """Coerce a raw scraped value into a numeric price."""
    currency_symbol: str | None = config.get('currency_symbol')
    require_decimals: bool = config.get('require_decimals', False)

    if not isinstance(v, str):
        return float(v)  # type: ignore[arg-type]

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


def Price(
    currency_symbol: str | None = None,
    require_decimals: bool = False,
    description: str = 'A monetary price value',
    **kwargs: Any,
) -> Any:
    """Configure a price field with optional currency and decimal enforcement.

    Args:
        currency_symbol: If set, raises if this symbol is absent from input.
        require_decimals: If True, raises if no decimal separator is found.
        description: Field description for schema/manifest. Defaults to 'A monetary price value'.
        **kwargs: Additional arguments forwarded to Field.

    Example::

        class Shop(Contract):
            price: float = ys.Price(currency_symbol='€', require_decimals=True)
    """
    return Field(
        description=description,
        json_schema_extra={
            'yosoi_type': 'price',
            'currency_symbol': currency_symbol,
            'require_decimals': require_decimals,
        },
        **kwargs,
    )
