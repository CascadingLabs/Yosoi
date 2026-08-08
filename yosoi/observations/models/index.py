"""Flat indexed-observation contracts built from modality-specific views."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from yosoi.observations.models.artifact import OBSERVATION_SCHEMA_VERSION, ArtifactRef, EvidenceKind
from yosoi.observations.models.view import RegionCoverage, RegionRef


class IndexEntry(BaseModel):
    """Compact overview entry pointing to exact recoverable evidence.

    Carries the region's coverage verbatim: the index is what a consumer actually holds, so
    dropping incompleteness here would let partial evidence read as total no matter how
    carefully the pruner stated it.
    """

    model_config = ConfigDict(frozen=True)

    ordinal: int = Field(ge=0)
    ref: RegionRef
    label: str = Field(min_length=1)
    summary: str
    coverage: RegionCoverage | None = None


class ObservationIndex(BaseModel):
    """Small flat address space spanning all available evidence modalities."""

    model_config = ConfigDict(frozen=True)

    schema_version: str = OBSERVATION_SCHEMA_VERSION
    snapshot_id: str = Field(min_length=1)
    sources: tuple[ArtifactRef, ...] = ()
    modalities: tuple[EvidenceKind, ...] = ()
    entries: tuple[IndexEntry, ...] = ()

    @model_validator(mode='after')
    def _validate_snapshot_scope(self) -> ObservationIndex:
        if any(source.snapshot_id != self.snapshot_id for source in self.sources):
            raise ValueError('every index source must belong to the indexed snapshot')
        if any(entry.ref.snapshot_id != self.snapshot_id for entry in self.entries):
            raise ValueError('every index entry must belong to the indexed snapshot')
        source_digests = {source.sha256 for source in self.sources}
        if any(entry.ref.artifact_sha256 not in source_digests for entry in self.entries):
            raise ValueError('every index entry must reference a declared source artifact')
        return self


__all__ = ['IndexEntry', 'ObservationIndex']
