"""Common contract for deterministic modality-specific semantic pruning."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from yosoi.observations.index.paging import PageRequest
from yosoi.observations.models.artifact import ArtifactRef, EvidenceKind
from yosoi.observations.models.view import PrunedView


class PruningPolicy(BaseModel):
    """Provider-independent limits applied while deriving a structured view."""

    model_config = ConfigDict(frozen=True)

    max_fragments: int = Field(default=1_000, gt=0)
    collapse_to_fit: bool = False
    """Lower resolution to cover the whole document, instead of paging it at full resolution.

    Off by default: silently serving less detail than the walk produced is the kind of quiet
    fidelity loss this package refuses elsewhere, and paging at least keeps every candidate
    reachable. Turn it on when the caller wants a MAP — complete extent, reduced detail — and
    accept that subtrees below the cut are reachable only by inspecting the entry that says so.

    Only helps when a document's candidates spread across depth. Measured: `List of Unicode
    characters` grows smoothly (3, 43, 47, 58, 72 … per depth) and collapses usefully, while the
    HTML Living Standard is WIDE — depth 0 holds 3 candidates and depth 1 holds 10,016, so no cut
    exists between them and collapse can only offer 3 entries. A wide document needs paging; the
    `Granularity` a collapse reports makes that visible rather than leaving the caller guessing.
    """
    max_fragment_chars: int = Field(default=4_000, gt=0)
    include_restricted: bool = False


class PruningInput(BaseModel):
    """Canonical artifact bytes supplied explicitly to a pure pruner."""

    model_config = ConfigDict(frozen=True)

    source: ArtifactRef
    data: bytes


@runtime_checkable
class Pruner(Protocol):
    """Pure semantic reducer for exactly one evidence modality."""

    name: str
    version: str
    evidence_kind: EvidenceKind

    def prune(self, source: PruningInput, policy: PruningPolicy, page: PageRequest | None = None) -> PrunedView:
        """Derive one page of a structured view, without mutating or persisting its source."""
        ...

    def reduce_once(self, source: PruningInput, policy: PruningPolicy) -> object:
        """Walk the artifact once, returning a candidate space reusable across pages."""
        ...


__all__ = ['Pruner', 'PruningInput', 'PruningPolicy']
