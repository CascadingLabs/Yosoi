"""Price type alias for Yosoi contracts."""

from typing import Annotated

from pydantic.functional_validators import BeforeValidator

from yosoi.types.field import Field


def _coerce_price(v: object) -> float:
    if isinstance(v, str):
        cleaned = v.strip()
        for sym in ('£', '$', '€', '¥', '₹', '₩', '₽', ','):
            cleaned = cleaned.replace(sym, '')
        return float(cleaned.strip())
    return float(v)  # type: ignore[arg-type]


Price = Annotated[
    float,
    BeforeValidator(_coerce_price),
    Field(description='A monetary price value', json_schema_extra={'yosoi_type': 'price'}),
]
