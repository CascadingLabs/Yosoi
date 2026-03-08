"""BodyText type alias for Yosoi contracts."""

from typing import Annotated

from yosoi.types.field import Field

BodyText = Annotated[
    str,
    Field(description='Main body text content', json_schema_extra={'yosoi_type': 'body_text'}),
]
