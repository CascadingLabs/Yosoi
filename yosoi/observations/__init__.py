"""Task-agnostic indexed observation contracts and deterministic evidence mechanics.

This package is intentionally not re-exported from :mod:`yosoi` while the static
vertical slice is being proven. See ``ROADMAP.md`` for implementation order.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from yosoi._lazy import lazy_exports

if TYPE_CHECKING:
    from yosoi.observations.artifacts.protocol import ArtifactStore as ArtifactStore
    from yosoi.observations.models.artifact import ArtifactRef as ArtifactRef
    from yosoi.observations.models.artifact import EvidenceKind as EvidenceKind
    from yosoi.observations.models.artifact import Sensitivity as Sensitivity
    from yosoi.observations.models.index import ObservationIndex as ObservationIndex
    from yosoi.observations.models.snapshot import CaptureProfile as CaptureProfile
    from yosoi.observations.models.snapshot import ObservationSnapshot as ObservationSnapshot
    from yosoi.observations.models.view import PrunedView as PrunedView
    from yosoi.observations.models.view import RegionRef as RegionRef
    from yosoi.observations.models.view import RenderedView as RenderedView
    from yosoi.observations.pruning.protocol import Pruner as Pruner

_LAZY = {
    'ArtifactRef': 'yosoi.observations.models.artifact',
    'ArtifactStore': 'yosoi.observations.artifacts.protocol',
    'CaptureProfile': 'yosoi.observations.models.snapshot',
    'EvidenceKind': 'yosoi.observations.models.artifact',
    'ObservationIndex': 'yosoi.observations.models.index',
    'ObservationSnapshot': 'yosoi.observations.models.snapshot',
    'PrunedView': 'yosoi.observations.models.view',
    'Pruner': 'yosoi.observations.pruning.protocol',
    'RegionRef': 'yosoi.observations.models.view',
    'RenderedView': 'yosoi.observations.models.view',
    'Sensitivity': 'yosoi.observations.models.artifact',
}

__all__ = sorted(_LAZY)
__getattr__, __dir__ = lazy_exports(__name__, globals(), _LAZY)
