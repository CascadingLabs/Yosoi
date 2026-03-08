"""Datetime type alias for Yosoi contracts."""

from typing import Annotated

from yosoi.types.field import Field

Datetime = Annotated[
    str,
    Field(description='A date or datetime string', json_schema_extra={'yosoi_type': 'datetime'}),
]
