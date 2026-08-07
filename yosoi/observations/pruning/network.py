"""Policy-safe network-evidence semantic pruning scaffold."""

from __future__ import annotations

from yosoi.observations.models.artifact import EvidenceKind
from yosoi.observations.models.view import PrunedView
from yosoi.observations.pruning._shared import require_prunable
from yosoi.observations.pruning.protocol import PruningInput, PruningPolicy


class NetworkPruner:
    """Future reducer for already-redacted and normalized network evidence."""

    name = 'network'
    version = 'scaffold'
    evidence_kind = EvidenceKind.NETWORK

    def prune(self, source: PruningInput, policy: PruningPolicy) -> PrunedView:
        """Validate input identity, then refuse until safe network reduction exists."""
        require_prunable(source, self.evidence_kind, policy)
        raise NotImplementedError('network pruning awaits the safe evidence contract; see observations/ROADMAP.md')


__all__ = ['NetworkPruner']
