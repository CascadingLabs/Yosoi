"""Provider-visible QA tool contracts; handlers remain deliberately unwired."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from yosoi.observations.index.diff import ObservationDiff
from yosoi.observations.index.inspect import InspectionBudget, InspectionResult, RegionPage
from yosoi.observations.models.view import RegionRef, RenderedView
from yosoi.qa.index import QA_INDEX_LIMITS, ExpandArgs, IndexCapabilities, IndexSession, IndexStatus, _validate_budget


class OverviewArgs(BaseModel):
    """Request a bounded rendered overview for one exact snapshot."""

    model_config = ConfigDict(frozen=True)

    snapshot_id: str = Field(min_length=1)
    tokenizer_id: str = Field(min_length=1)
    token_budget: int = Field(gt=0, le=QA_INDEX_LIMITS.overview_tokens)


class InspectArgs(BaseModel):
    """Request detail by an exact ref or by a snapshot-local overview ordinal."""

    model_config = ConfigDict(frozen=True)

    ref: RegionRef | None = None
    snapshot_id: str | None = Field(default=None, min_length=1)
    ordinal: int | None = Field(default=None, ge=0)
    budget: InspectionBudget = Field(
        default_factory=lambda: InspectionBudget(
            max_bytes=QA_INDEX_LIMITS.inspect_bytes,
            max_items=QA_INDEX_LIMITS.inspect_items,
            max_summary_chars=QA_INDEX_LIMITS.inspect_summary_chars,
        )
    )

    @model_validator(mode='after')
    def _one_address(self) -> InspectArgs:
        _validate_budget(self.budget, QA_INDEX_LIMITS, expand=False)
        if self.ref is not None and (self.snapshot_id is not None or self.ordinal is not None):
            raise ValueError('provide ref or snapshot_id plus ordinal, not both')
        if self.ref is None and (self.snapshot_id is None or self.ordinal is None):
            raise ValueError('provide ref or both snapshot_id and ordinal')
        return self


class DiffArgs(BaseModel):
    """Request a bounded comparison between two related snapshots."""

    model_config = ConfigDict(frozen=True)

    before_snapshot_id: str = Field(min_length=1)
    after_snapshot_id: str = Field(min_length=1)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=QA_INDEX_LIMITS.diff_page_items, gt=0, le=QA_INDEX_LIMITS.diff_page_items)


class CheckSelectorArgs(BaseModel):
    """Request independent selector validation against an exact snapshot."""

    model_config = ConfigDict(frozen=True)

    snapshot_id: str = Field(min_length=1)
    selector: str = Field(min_length=1)


class CheckSelectorResult(BaseModel):
    """Deterministic selector-validation result with optional evidence links."""

    model_config = ConfigDict(frozen=True)

    selector: str
    valid: bool
    match_count: int = Field(ge=0)
    evidence: tuple[RegionRef, ...] = ()


@runtime_checkable
class QAToolHandler(Protocol):
    """Bounded QA tools mounted by transports."""

    async def capabilities(self) -> IndexCapabilities:
        """Report actual modality and wiring capabilities."""
        ...

    async def status(self) -> IndexStatus:
        """Report readiness without attempting acquisition or provider calls."""
        ...

    async def overview(self, args: OverviewArgs) -> RenderedView:
        """Return a token-budgeted flat overview."""
        ...

    async def inspect(self, args: InspectArgs) -> InspectionResult:
        """Return bounded canonical detail for an exact reference."""
        ...

    async def expand(self, args: ExpandArgs) -> RegionPage:
        """Return one bounded page of members for an exact region."""
        ...

    async def diff(self, args: DiffArgs) -> ObservationDiff:
        """Return bounded changes between related page states."""
        ...

    async def check_selector(self, args: CheckSelectorArgs) -> CheckSelectorResult:
        """Validate a selector independently from model claims."""
        ...


class IndexQAToolHandler:
    """Thin transport adapter over the shared typed index session."""

    def __init__(self, session: IndexSession) -> None:
        """Bind this transport adapter to one typed index session."""
        self._session = session

    async def capabilities(self) -> IndexCapabilities:
        """Delegate capability reporting."""
        return await self._session.capabilities()

    async def status(self) -> IndexStatus:
        """Delegate status reporting."""
        return await self._session.status()

    async def overview(self, args: OverviewArgs) -> RenderedView:
        """Delegate bounded overview rendering."""
        return await self._session.overview(args)

    async def inspect(self, args: InspectArgs) -> InspectionResult:
        """Delegate exact inspection."""
        return await self._session.inspect(args)

    async def expand(self, args: ExpandArgs) -> RegionPage:
        """Delegate bounded region expansion."""
        return await self._session.expand(args)

    async def diff(self, args: DiffArgs) -> ObservationDiff:
        """Delegate identity-based diffing."""
        return await self._session.diff(args)

    async def check_selector(self, args: CheckSelectorArgs) -> CheckSelectorResult:
        """Refuse selector validation; it is outside the read-only index surface."""
        raise NotImplementedError('selector checking is not part of the QA index surface')


class UnwiredQAToolHandler:
    """Fail-closed placeholder that makes accidental production use obvious."""

    async def capabilities(self) -> IndexCapabilities:
        """Truthfully report that no evidence modalities or operations are wired."""
        return IndexCapabilities(operations=('capabilities', 'status'))

    async def status(self) -> IndexStatus:
        """Report not-ready without starting capture or provider work."""
        return IndexStatus(
            ready=False,
            snapshot_ids=(),
            message='no observation index is wired',
            capabilities=await self.capabilities(),
        )

    async def overview(self, args: OverviewArgs) -> RenderedView:
        """Refuse overview calls while the runtime remains unwired."""
        raise NotImplementedError('QA overview is not wired; see qa/ROADMAP.md')

    async def inspect(self, args: InspectArgs) -> InspectionResult:
        """Refuse inspection calls while the runtime remains unwired."""
        raise NotImplementedError('QA inspection is not wired; see qa/ROADMAP.md')

    async def expand(self, args: ExpandArgs) -> RegionPage:
        """Refuse expansion while the runtime remains unwired."""
        raise NotImplementedError('QA expansion is not wired; see qa/ROADMAP.md')

    async def diff(self, args: DiffArgs) -> ObservationDiff:
        """Refuse diff calls while the runtime remains unwired."""
        raise NotImplementedError('QA diffing is not wired; see qa/ROADMAP.md')

    async def check_selector(self, args: CheckSelectorArgs) -> CheckSelectorResult:
        """Refuse selector checks while the runtime remains unwired."""
        raise NotImplementedError('QA selector checking is not wired; see qa/ROADMAP.md')


__all__ = [
    'CheckSelectorArgs',
    'CheckSelectorResult',
    'DiffArgs',
    'ExpandArgs',
    'IndexQAToolHandler',
    'InspectArgs',
    'OverviewArgs',
    'QAToolHandler',
    'UnwiredQAToolHandler',
]
