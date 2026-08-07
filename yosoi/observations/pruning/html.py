"""Source-HTML semantic pruning scaffold."""

from __future__ import annotations

from yosoi.observations.models.artifact import EvidenceKind
from yosoi.observations.models.view import PrunedView
from yosoi.observations.pruning._shared import require_prunable
from yosoi.observations.pruning.protocol import PruningInput, PruningPolicy


class HtmlPruner:
    """Future deterministic reducer for server/source HTML evidence."""

    name = 'html'
    version = 'scaffold'
    evidence_kind = EvidenceKind.SOURCE_HTML

    def prune(self, source: PruningInput, policy: PruningPolicy) -> PrunedView:
        """Validate input identity, then refuse until spike logic is ported."""
        require_prunable(source, self.evidence_kind, policy)
        raise NotImplementedError('HTML pruning is the first implementation slice; see observations/ROADMAP.md')


__all__ = ['HtmlPruner']
