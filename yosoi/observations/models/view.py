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
    bound_to_previous: bool = False
    """Whether this fragment and the one before it form one routing unit."""

    @model_validator(mode='after')
    def _validate_region_coverage(self) -> PrunedFragment:
        from yosoi.observations.index.addressing import parse_address

        is_region = parse_address(self.ref.locator).is_region
        if is_region and self.coverage is None:
            raise ValueError('a region fragment must state how much of itself it observed')
        if not is_region and self.coverage is not None:
            raise ValueError('coverage belongs to a region fragment, not to a single element')
        return self


class Pagination(BaseModel):
    """Which window of a reduction a view holds, and how large the whole space is.

    Carried on the view because `total` is the only place a downstream consumer can learn that
    the reduction proposed more than it was handed. Without it the compiler, the index, and the
    renderer each honestly report omission relative to what they received, and the reader is told
    a smaller page is a smaller page rather than the first window of an enormous one.
    """

    model_config = ConfigDict(frozen=True)

    offset: int = Field(ge=0)
    limit: int = Field(gt=0)
    returned: int = Field(ge=0)
    total: int = Field(ge=0)

    @model_validator(mode='after')
    def _validate_window(self) -> Pagination:
        if self.offset + self.returned > self.total:
            raise ValueError('a page cannot return candidates past the total it declares')
        return self

    @property
    def next_offset(self) -> int | None:
        """Offset of the next page, or None at the end. Always `offset + returned`."""
        consumed = self.offset + self.returned
        return consumed if consumed < self.total else None

    @property
    def complete(self) -> bool:
        """Whether this window holds the entire candidate space."""
        return self.offset == 0 and self.returned == self.total


class Granularity(BaseModel):
    """The resolution one reduction was served at, and what that cost.

    `reduced` is the field a consumer must branch on: at full depth the reduction is the whole
    document at the walk's own resolution, and at anything less it is the whole document with
    subtrees deliberately unexplored — complete in extent, partial in detail.
    """

    model_config = ConfigDict(frozen=True)

    depth: int = Field(ge=0)
    deepest: int = Field(ge=0)
    retained: int = Field(ge=0)
    proposed: int = Field(ge=0)
    undescended: int = Field(ge=0)
    """How many retained candidates hold content the collapse chose not to index."""

    @model_validator(mode='after')
    def _validate_choice(self) -> Granularity:
        if self.depth > self.deepest:
            raise ValueError('a granularity cannot be deeper than the walk that produced it')
        if self.retained > self.proposed:
            raise ValueError('a granularity cannot retain more candidates than were proposed')
        if self.undescended > self.retained:
            raise ValueError('only retained candidates can hold unindexed content')
        return self

    @property
    def reduced(self) -> bool:
        """Whether resolution was lowered to fit the budget."""
        return self.depth < self.deepest

    def describe(self) -> str:
        """State the resolution in one line, or say plainly that none was lost."""
        if not self.reduced:
            return f'full depth {self.depth}; whole document indexed'
        return (
            f'depth {self.depth} of {self.deepest} — the whole document at reduced resolution; '
            f'{self.undescended} entries hold content below the cut, each inspectable to descend'
        )


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
    page: Pagination
    granularity: Granularity | None = None
    """The resolution this view was served at, when resolution had to be lowered to fit.

    Distinct from `page`, and both can apply. A page omission is not addressable — those
    candidates are not in this index at all. A granularity omission IS addressable: it sits under
    a retained entry that says so and can be inspected to descend.
    """

    stats: PruningStats

    @model_validator(mode='after')
    def _validate_fragment_sources(self) -> PrunedView:
        for position, fragment in enumerate(self.fragments):
            if fragment.bound_to_previous and position == 0:
                raise ValueError('the first fragment in a view cannot be bound to a missing predecessor')
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
    'Granularity',
    'Pagination',
    'PrunedFragment',
    'PrunedView',
    'PruningStats',
    'RegionCoverage',
    'RegionRef',
    'RenderedView',
]
