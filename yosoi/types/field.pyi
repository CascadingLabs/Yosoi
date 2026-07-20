from collections.abc import Callable, Mapping
from typing import Any

from typing_extensions import Self

class ExtractorPlanField:
    def map(self, using: Callable[[Any], Any] | str) -> Self: ...
    def compact(self) -> Self: ...

def extractor_plan_field(selector: Any, *, operation: str, attribute: str | None = ...) -> ExtractorPlanField: ...
def Extractor(
    default: Any = ...,
    *,
    default_factory: Callable[[], Any] | None = ...,
    using: Callable[[Any], Any] | str | None = ...,
    key: str | None = ...,
    version: str | None = ...,
    config: Mapping[str, Any] | None = ...,
    **kwargs: Any,
) -> Any: ...
def js(script: str | None = ..., *, description: str | None = ..., **kwargs: Any) -> Any: ...
def Field(
    frozen: bool = ...,
    selector: str | None = ...,
    delimiter: str | None = ...,
    **kwargs: Any,
) -> Any: ...
