"""Rendered-DOM semantic pruning scaffold."""

from __future__ import annotations

from yosoi.observations.models.artifact import EvidenceKind
from yosoi.observations.models.view import PrunedView
from yosoi.observations.pruning._shared import require_prunable
from yosoi.observations.pruning.protocol import PruningInput, PruningPolicy


class DomPruner:
    """Future deterministic reducer for structured rendered-DOM evidence."""

    name = 'dom'
    version = 'scaffold'
    evidence_kind = EvidenceKind.RENDERED_DOM

    def prune(self, source: PruningInput, policy: PruningPolicy) -> PrunedView:
        """Validate input identity, then refuse until DOM reduction is ported."""
        require_prunable(source, self.evidence_kind, policy)
        raise NotImplementedError('DOM pruning is not implemented; see observations/ROADMAP.md')


__all__ = ['DomPruner']
