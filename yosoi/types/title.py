"""Title type alias for Yosoi contracts."""

from typing import Annotated

from pydantic.functional_validators import BeforeValidator

from yosoi.types.field import Field


def _clean_str(v: object) -> str:
    return str(v).strip() if v is not None else ''


Title = Annotated[
    str,
    BeforeValidator(_clean_str),
    Field(description='A title or heading', json_schema_extra={'yosoi_type': 'title'}),
]
