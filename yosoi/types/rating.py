"""Rating type alias for Yosoi contracts."""

from typing import Annotated

from yosoi.types.field import Field

Rating = Annotated[
    str,
    Field(description='A rating or review score', json_schema_extra={'yosoi_type': 'rating'}),
]
