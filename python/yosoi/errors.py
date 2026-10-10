"""Failures to author or initialize a public SDK operation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from ._native import (
    ClosedResourceError as ClosedResourceError,
)
from ._native import (
    ContractError as ContractError,
)
from ._native import (
    DocumentError as DocumentError,
)
from ._native import (
    LocatorError as LocatorError,
)
from ._native import (
    MapError as MapError,
)
from ._native import (
    ParseError as ParseError,
)
from ._native import (
    PolicyError as PolicyError,
)
from ._native import (
    RequestError as RequestError,
)
from ._native import (
    SearchError as SearchError,
)
from ._native import (
    YosoiError as YosoiError,
)


@dataclass(frozen=True, slots=True)
class RustErrorDetails:
    """Exact Rust error identity and structured payload attached by the binding."""

    rust_type: str
    variant: str | None
    details: Mapping[str, Any]
    source_chain: tuple[str, ...] = ()


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    return value


def rust_error_details(error: BaseException) -> RustErrorDetails | None:
    """Read native Rust metadata, including through Pydantic validation errors.

    Pydantic keeps its public ``ValidationError`` category and stores the
    validator exception in each error context. This accessor follows those
    contexts and Python's explicit cause chain to find the original native
    exception without replacing the raised exception.
    """
    pending = [error]
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in visited:
            continue
        visited.add(id(current))

        rust_type = getattr(current, "rust_type", None)
        variant = getattr(current, "variant", None)
        details = getattr(current, "details", None)
        source_chain = getattr(current, "source_chain", ())
        if (
            isinstance(rust_type, str)
            and (isinstance(variant, str) or variant is None)
            and isinstance(details, Mapping)
            and isinstance(source_chain, (tuple, list))
        ):
            return RustErrorDetails(
                rust_type=rust_type,
                variant=variant,
                details=_freeze(details),
                source_chain=tuple(str(item) for item in source_chain),
            )

        cause = getattr(current, "__cause__", None)
        context = getattr(current, "__context__", None)
        if isinstance(cause, BaseException):
            pending.append(cause)
        if isinstance(context, BaseException):
            pending.append(context)

        validation_errors = getattr(current, "errors", None)
        if callable(validation_errors):
            try:
                entries = validation_errors()
            except Exception:
                entries = ()
            for entry in entries:
                if not isinstance(entry, Mapping):
                    continue
                context = entry.get("ctx")
                nested = context.get("error") if isinstance(context, Mapping) else None
                if isinstance(nested, BaseException):
                    pending.append(nested)
    return None
