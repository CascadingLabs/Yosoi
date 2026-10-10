"""Shared Pydantic configuration, without a parallel Python processing stack."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from types import MappingProxyType
from typing import Any, Self

from pydantic import BaseModel, ConfigDict


class Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        serialize_by_alias=True,
        validate_default=True,
    )

    def clone(self) -> Self:
        """Return an independent copy of this SDK value."""
        return self.model_copy(deep=True)

    def __deepcopy__(self, memo: dict[int, Any] | None = None) -> Self:
        if memo is None:
            memo = {}

        private = getattr(self, "__pydantic_private__", None)
        if isinstance(private, dict):
            handle = private.get("_handle")
            if type(handle).__module__ in {"_native", "yosoi._native"}:
                memo[id(handle)] = handle

        for value in self.__dict__.values():
            if isinstance(value, MappingProxyType) and id(value) not in memo:
                memo[id(value)] = MappingProxyType(deepcopy(dict(value), memo))

        return super().__deepcopy__(memo)


class ImmutableModel(Model):
    model_config = ConfigDict(frozen=True)


class NativeAuthoringModel(ImmutableModel):
    """Copies preserve immutable handles unless authored inputs change."""

    def model_copy(
        self, *, update: Mapping[str, Any] | None = None, deep: bool = False
    ) -> Self:
        if update:
            return type(self).model_validate({**self.model_dump(), **update})
        return super().model_copy(deep=deep)
