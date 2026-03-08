"""Title type alias for Yosoi contracts."""

from typing import Annotated

from yosoi.types.field import Field

Title = Annotated[
    str,
    Field(description='A title or heading', json_schema_extra={'yosoi_type': 'title'}),
]
