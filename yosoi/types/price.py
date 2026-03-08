"""Price type alias for Yosoi contracts."""

from typing import Annotated

from yosoi.types.field import Field

Price = Annotated[
    float,
    Field(description='A monetary price value', json_schema_extra={'yosoi_type': 'price'}),
]
