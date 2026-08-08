"""Policy-safe network-evidence semantic pruning scaffold."""

from __future__ import annotations

from yosoi.observations.models.artifact import EvidenceKind
from yosoi.observations.pruning._base import Reduction, SemanticPruner
from yosoi.observations.pruning.protocol import PruningPolicy


class NetworkPruner(SemanticPruner):
    """Future reducer for already-redacted and normalized network evidence."""

    name = 'network'
    version = 'scaffold'
    evidence_kind = EvidenceKind.NETWORK

    def reduce(self, data: bytes, policy: PruningPolicy) -> Reduction:
        """Refuse reduction until this modality is implemented."""
        raise NotImplementedError('network pruning awaits the safe evidence contract; see observations/ROADMAP.md')


__all__ = ['NetworkPruner']
