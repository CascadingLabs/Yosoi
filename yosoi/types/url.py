"""Url type alias for Yosoi contracts."""

from typing import Annotated

from pydantic.functional_validators import BeforeValidator

from yosoi.types.field import Field


def _clean_str(v: object) -> str:
    return str(v).strip() if v is not None else ''


# TODO ensure http or https. add config for https only must but .com etc.
Url = Annotated[
    str,
    BeforeValidator(_clean_str),
    Field(description='A URL or href', json_schema_extra={'yosoi_type': 'url'}),
]
