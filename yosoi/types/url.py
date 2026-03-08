"""Url type alias for Yosoi contracts."""

from typing import Annotated

from yosoi.types.field import Field

Url = Annotated[
    str,
    Field(description='A URL or href', json_schema_extra={'yosoi_type': 'url'}),
]
