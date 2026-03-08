"""BodyText type alias for Yosoi contracts."""

from typing import Annotated

from pydantic.functional_validators import BeforeValidator

from yosoi.types.field import Field


def _clean_str(v: object) -> str:
    return str(v).strip() if v is not None else ''


BodyText = Annotated[
    str,
    BeforeValidator(_clean_str),
    Field(description='Main body text content', json_schema_extra={'yosoi_type': 'body_text'}),
]
