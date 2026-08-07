"""Bounded canonical-detail inspection contracts and fail-closed scaffold."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from yosoi.observations.models.view import RegionRef


class InspectionBudget(BaseModel):
    """Hard limits for one direct retrieval from canonical evidence."""

    model_config = ConfigDict(frozen=True)

    max_bytes: int = Field(default=32_000, gt=0)
    max_items: int = Field(default=500, gt=0)
    allow_restricted: bool = False


class InspectionResult(BaseModel):
    """Bounded detail returned for one exact observation reference."""

    model_config = ConfigDict(frozen=True)

    ref: RegionRef
    media_type: str = Field(min_length=1)
    content: bytes
    returned_bytes: int = Field(ge=0)
    returned_items: int = Field(ge=0)
    truncated: bool = False


class ObservationInspector:
    """Future resolver from a region reference to bounded canonical detail."""

    def inspect(self, ref: RegionRef, budget: InspectionBudget) -> InspectionResult:
        """Refuse retrieval until modality resolvers and permissions are implemented."""
        raise NotImplementedError('bounded observation inspection is not implemented; see observations/ROADMAP.md')


__all__ = ['InspectionBudget', 'InspectionResult', 'ObservationInspector']
