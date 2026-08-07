"""Accessibility-tree semantic pruning scaffold."""

from __future__ import annotations

from yosoi.observations.models.artifact import EvidenceKind
from yosoi.observations.models.view import PrunedView
from yosoi.observations.pruning._shared import require_prunable
from yosoi.observations.pruning.protocol import PruningInput, PruningPolicy


class AxPruner:
    """Future deterministic reducer for raw accessibility-tree evidence."""

    name = 'ax'
    version = 'scaffold'
    evidence_kind = EvidenceKind.AX_TREE

    def prune(self, source: PruningInput, policy: PruningPolicy) -> PrunedView:
        """Validate input identity, then refuse until AX reduction is ported."""
        require_prunable(source, self.evidence_kind, policy)
        raise NotImplementedError('AX pruning is not implemented; see observations/ROADMAP.md')


__all__ = ['AxPruner']
