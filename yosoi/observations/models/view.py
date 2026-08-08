"""Structured semantic reductions and separately budgeted renderings."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from yosoi.observations.models.artifact import OBSERVATION_SCHEMA_VERSION, ArtifactRef, EvidenceKind


class RegionRef(BaseModel):
    """Stable snapshot-local address into one exact canonical artifact."""

    model_config = ConfigDict(frozen=True)

    snapshot_id: str = Field(min_length=1)
    artifact_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    modality: EvidenceKind
    locator: str = Field(min_length=1)


class RegionCoverage(BaseModel):
    """How much of a repeat region this snapshot actually observed.

    A collapsed region says "N members". Without this, a region where 20 of 10,000 members were
    ever in the DOM is indistinguishable from one that is genuinely complete, and a
    consumer reads partial evidence as total. Incompleteness is stated, never inferred.
    """

    model_config = ConfigDict(frozen=True)

    observed: int = Field(ge=0)
    declared: int | None = None
    complete: bool

    @model_validator(mode='after')
    def _validate_coverage(self) -> RegionCoverage:
        if self.declared is not None and self.observed > self.declared:
            raise ValueError('a region cannot observe more members than it declares')
        if self.complete and self.declared is not None and self.observed != self.declared:
            raise ValueError('a complete region must observe every declared member')
        if self.complete and self.declared is None:
            raise ValueError('a complete region must declare its member count')
        return self


class PrunedFragment(BaseModel):
    """One addressable semantic fragment retained by a modality pruner."""

    model_config = ConfigDict(frozen=True)

    ref: RegionRef
    ordinal: int = Field(ge=0)
    label: str = Field(min_length=1)
    summary: str
    coverage: RegionCoverage | None = None

    @model_validator(mode='after')
    def _validate_region_coverage(self) -> PrunedFragment:
        from yosoi.observations.index.addressing import parse_address

        is_region = parse_address(self.ref.locator).is_region
        if is_region and self.coverage is None:
            raise ValueError('a region fragment must state how much of itself it observed')
        if not is_region and self.coverage is not None:
            raise ValueError('coverage belongs to a region fragment, not to a single element')
        return self


class PruningStats(BaseModel):
    """Loss and size accounting for a semantic pruning pass."""

    model_config = ConfigDict(frozen=True)

    source_items: int = Field(ge=0)
    retained_items: int = Field(ge=0)
    omitted_items: int = Field(ge=0)
    source_bytes: int = Field(ge=0)
    output_bytes: int = Field(ge=0)
    truncated: bool = False


class PrunedView(BaseModel):
    """Provider-independent semantic reduction recoverable through canonical evidence."""

    model_config = ConfigDict(frozen=True)

    schema_version: str = OBSERVATION_SCHEMA_VERSION
    source: ArtifactRef
    pruner_name: str = Field(min_length=1)
    pruner_version: str = Field(min_length=1)
    policy_hash: str = Field(min_length=1)
    fragments: tuple[PrunedFragment, ...] = ()
    stats: PruningStats

    @model_validator(mode='after')
    def _validate_fragment_sources(self) -> PrunedView:
        for fragment in self.fragments:
            ref = fragment.ref
            if ref.snapshot_id != self.source.snapshot_id:
                raise ValueError('pruned fragment belongs to a different snapshot')
            if ref.artifact_sha256 != self.source.sha256:
                raise ValueError('pruned fragment belongs to a different artifact')
            if ref.modality != self.source.kind:
                raise ValueError('pruned fragment modality does not match its source artifact')
        return self


class RenderedView(BaseModel):
    """One token-budgeted serialization of an existing structured view or index."""

    model_config = ConfigDict(frozen=True)

    text: str
    included_refs: tuple[RegionRef, ...] = ()
    renderer_name: str = Field(min_length=1)
    renderer_version: str = Field(min_length=1)
    tokenizer_id: str = Field(min_length=1)
    token_budget: int = Field(gt=0)
    token_count: int = Field(ge=0)
    truncated: bool = False


__all__ = [
    'PrunedFragment',
    'PrunedView',
    'PruningStats',
    'RegionCoverage',
    'RegionRef',
    'RenderedView',
]
