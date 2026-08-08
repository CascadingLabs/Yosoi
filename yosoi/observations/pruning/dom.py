"""Rendered-DOM semantic pruning scaffold."""

from __future__ import annotations

from yosoi.observations.models.artifact import EvidenceKind
from yosoi.observations.pruning._base import Reduction, SemanticPruner
from yosoi.observations.pruning.protocol import PruningPolicy


class DomPruner(SemanticPruner):
    """Future deterministic reducer for structured rendered-DOM evidence."""

    name = 'dom'
    version = 'scaffold'
    evidence_kind = EvidenceKind.RENDERED_DOM

    def reduce(self, data: bytes, policy: PruningPolicy) -> Reduction:
        """Refuse reduction until this modality is implemented."""
        raise NotImplementedError('DOM pruning is not implemented; see observations/ROADMAP.md')


__all__ = ['DomPruner']
