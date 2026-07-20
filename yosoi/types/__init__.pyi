"""Type stubs for yosoi.types sub-package."""

from collections.abc import Iterable
from typing import Any

from yosoi.types.field import Extractor as Extractor
from yosoi.types.field import Field as Field
from yosoi.types.field import js as js
from yosoi.types.registry import register_coercion as register_coercion

# Semantic type factories — return Any to match pydantic.Field() convention
def Title(description: str = ..., **kwargs: Any) -> Any: ...
def Price(
    description: str = ..., *, currency_symbol: str | None = ..., require_decimals: bool = ..., **kwargs: Any
) -> Any: ...
def Rating(description: str = ..., *, as_float: bool = ..., scale: int = ..., **kwargs: Any) -> Any: ...
def BodyText(description: str = ..., **kwargs: Any) -> Any: ...
def Author(description: str = ..., **kwargs: Any) -> Any: ...
def Url(description: str = ..., *, require_https: bool = ..., strip_tracking: bool = ..., **kwargs: Any) -> Any: ...
def Datetime(
    description: str = ..., *, assume_utc: bool = ..., past_only: bool = ..., as_iso: bool = ..., **kwargs: Any
) -> Any: ...
def File(
    *,
    trigger: str | None = ...,
    href: str | None = ...,
    url: str | None = ...,
    description: str | None = ...,
    allowed_types: Iterable[str] | None = ...,
    max_bytes: int | None = ...,
    **kwargs: Any,
) -> Any: ...
def RelatedContent(description: str = ..., **kwargs: Any) -> Any: ...

__all__: list[str]
