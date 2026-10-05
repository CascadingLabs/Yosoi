"""Shared Pydantic configuration, without a parallel Python processing stack."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Self

from pydantic import BaseModel, ConfigDict


class Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        serialize_by_alias=True,
        validate_default=True,
    )


class ImmutableModel(Model):
    model_config = ConfigDict(frozen=True)


class NativeAuthoringModel(ImmutableModel):
    """Copies preserve immutable handles unless authored inputs change."""

    def model_copy(
        self, *, update: Mapping[str, Any] | None = None, deep: bool = False
    ) -> Self:
        if update:
            return type(self).model_validate({**self.model_dump(), **update})
        # Scalar authoring and the immutable native request can safely be shared.
        # Deep-copying a PyO3 object would require pickling it and lose identity.
        return super().model_copy(deep=False)
