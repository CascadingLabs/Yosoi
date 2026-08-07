"""Common contract for deterministic modality-specific semantic pruning."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from yosoi.observations.models.artifact import ArtifactRef, EvidenceKind
from yosoi.observations.models.view import PrunedView


class PruningPolicy(BaseModel):
    """Provider-independent limits applied while deriving a structured view."""

    model_config = ConfigDict(frozen=True)

    max_fragments: int = Field(default=1_000, gt=0)
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

    def prune(self, source: PruningInput, policy: PruningPolicy) -> PrunedView:
        """Derive a structured view without mutating or persisting its source."""
        ...


__all__ = ['Pruner', 'PruningInput', 'PruningPolicy']
