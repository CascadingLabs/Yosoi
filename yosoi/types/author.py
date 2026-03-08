"""Author type alias for Yosoi contracts."""

from typing import Annotated

from yosoi.types.field import Field

Author = Annotated[
    str,
    Field(description='Author or creator name', json_schema_extra={'yosoi_type': 'author'}),
]
