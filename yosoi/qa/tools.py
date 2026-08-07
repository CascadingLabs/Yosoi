"""Provider-visible QA tool contracts; handlers remain deliberately unwired."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from yosoi.observations.index.diff import ObservationDiff
from yosoi.observations.index.inspect import InspectionBudget, InspectionResult
from yosoi.observations.models.view import RegionRef, RenderedView


class OverviewArgs(BaseModel):
    """Request a bounded rendered overview for one exact snapshot."""

    model_config = ConfigDict(frozen=True)

    snapshot_id: str = Field(min_length=1)
    tokenizer_id: str = Field(min_length=1)
    token_budget: int = Field(gt=0)


class InspectArgs(BaseModel):
    """Request bounded canonical detail for one exact region."""

    model_config = ConfigDict(frozen=True)

    ref: RegionRef
    budget: InspectionBudget = Field(default_factory=InspectionBudget)


class DiffArgs(BaseModel):
    """Request a bounded comparison between two related snapshots."""

    model_config = ConfigDict(frozen=True)

    before_snapshot_id: str = Field(min_length=1)
    after_snapshot_id: str = Field(min_length=1)


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
    """Bounded QA tools mounted by a future provider-neutral runtime."""

    async def overview(self, args: OverviewArgs) -> RenderedView:
        """Return a token-budgeted flat overview."""
        ...

    async def inspect(self, args: InspectArgs) -> InspectionResult:
        """Return bounded canonical detail for an overview reference."""
        ...

    async def diff(self, args: DiffArgs) -> ObservationDiff:
        """Return bounded changes between related page states."""
        ...

    async def check_selector(self, args: CheckSelectorArgs) -> CheckSelectorResult:
        """Validate a selector independently from model claims."""
        ...


class UnwiredQAToolHandler:
    """Fail-closed placeholder that makes accidental production use obvious."""

    async def overview(self, args: OverviewArgs) -> RenderedView:
        """Refuse overview calls while the runtime remains unwired."""
        raise NotImplementedError('QA overview is not wired; see qa/ROADMAP.md')

    async def inspect(self, args: InspectArgs) -> InspectionResult:
        """Refuse inspection calls while the runtime remains unwired."""
        raise NotImplementedError('QA inspection is not wired; see qa/ROADMAP.md')

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
    'InspectArgs',
    'OverviewArgs',
    'QAToolHandler',
    'UnwiredQAToolHandler',
]
