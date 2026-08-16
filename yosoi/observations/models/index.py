"""Flat indexed-observation contracts built from modality-specific views."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from yosoi.observations.models.artifact import OBSERVATION_SCHEMA_VERSION, ArtifactRef, EvidenceKind
from yosoi.observations.models.view import Pagination, RegionCoverage, RegionRef


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
    bound_to_previous: bool = False
    """Whether this entry and the one immediately before it form one render-routing unit."""

    ref_id: str | None = None
    """Snapshot-independent identity, or None when this address has not earned one.

    `ref` locates bytes inside one exact capture and can never compare equal across captures —
    two of its four fields are the snapshot id and the artifact digest. `ref_id` is what
    survives: it is derived from the page's own anchors, shapes, and keys, so an unchanged page
    yields the same id on the next capture. It is None for positional or unanchored addresses,
    because "probably the same thing" is not an identity.
    """

    @model_validator(mode='after')
    def _validate_identity(self) -> IndexEntry:
        from yosoi.observations.index.addressing import ref_id

        expected = ref_id(self.ref.modality, self.ref.locator)
        if self.ref_id is not None and self.ref_id != expected:
            raise ValueError('index entry identity disagrees with the identity its own address implies')
        return self


class ObservationIndex(BaseModel):
    """Small flat address space spanning all available evidence modalities."""

    model_config = ConfigDict(frozen=True)

    schema_version: str = OBSERVATION_SCHEMA_VERSION
    snapshot_id: str = Field(min_length=1)
    sources: tuple[ArtifactRef, ...] = ()
    modalities: tuple[EvidenceKind, ...] = ()
    entries: tuple[IndexEntry, ...] = ()
    page: Pagination | None = None
    """Which window of the underlying reductions these entries are, when they are a window.

    None only for an index compiled from no views. Carried so the renderer can state the true
    candidate population: an index that reports omission relative to its own entry count tells a
    reader that 937 of 1,000 are missing when the reduction proposed 271,134.
    """

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
