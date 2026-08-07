"""Deterministic flat-index compiler scaffold."""

from __future__ import annotations

from collections.abc import Sequence

from yosoi.observations.models.index import ObservationIndex
from yosoi.observations.models.snapshot import ObservationSnapshot
from yosoi.observations.models.view import PrunedView


class ObservationIndexCompiler:
    """Future compiler combining explicit modality views without provider packing."""

    def compile(self, snapshot: ObservationSnapshot, views: Sequence[PrunedView]) -> ObservationIndex:
        """Refuse compilation until deterministic ordering and parity are implemented."""
        raise NotImplementedError('observation index compilation is not implemented; see observations/ROADMAP.md')


__all__ = ['ObservationIndexCompiler']
