"""Declarative field and model validators for Contract subclasses."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def validator(*fields: str) -> Callable[[Any], Any]:
    """Mark a method as a Yosoi field or model validator.

    Field validators (with field names):
        Receive a single value and return the transformed/validated value.
        Must be ``@classmethod`` methods. Run after type coercion but before
        pydantic's core validation. Can be used during discovery to test-drive
        selectors.

        @ys.validator("sku")
        @classmethod
        def validate_sku(cls, v: str) -> str: ...

    Model validators (no field names):
        Receive ``self`` (the fully-constructed instance) and return it.
        Run after pydantic validation. Can only be used during extraction.

        @ys.validator()
        def check_logic(self) -> 'MyContract': ...

    """

    def decorator(fn: Any) -> Any:
        target: Any = fn.__func__ if isinstance(fn, classmethod) else fn
        if fields:
            target._yosoi_field_validator = fields
        else:
            target._yosoi_model_validator = True
        return fn

    return decorator
