"""Accessibility-tree semantic pruning scaffold."""

from __future__ import annotations

from yosoi.observations.models.artifact import EvidenceKind
from yosoi.observations.pruning._base import Reduction, SemanticPruner
from yosoi.observations.pruning.protocol import PruningPolicy


class AxPruner(SemanticPruner):
    """Future deterministic reducer for raw accessibility-tree evidence."""

    name = 'ax'
    version = 'scaffold'
    evidence_kind = EvidenceKind.AX_TREE

    def reduce(self, data: bytes, policy: PruningPolicy) -> Reduction:
        """Refuse reduction until this modality is implemented."""
        raise NotImplementedError('AX pruning is not implemented; see observations/ROADMAP.md')


__all__ = ['AxPruner']
