"""Frozen contracts for canonical evidence, derived views, and flat indexes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from yosoi._lazy import lazy_exports

if TYPE_CHECKING:
    from yosoi.observations.models.artifact import ArtifactRef as ArtifactRef
    from yosoi.observations.models.artifact import EvidenceKind as EvidenceKind
    from yosoi.observations.models.artifact import Sensitivity as Sensitivity
    from yosoi.observations.models.dom import DomAttribute as DomAttribute
    from yosoi.observations.models.dom import DomCapability as DomCapability
    from yosoi.observations.models.dom import DomCapabilityKind as DomCapabilityKind
    from yosoi.observations.models.dom import DomGeometry as DomGeometry
    from yosoi.observations.models.dom import DomNode as DomNode
    from yosoi.observations.models.dom import DomRuntimeState as DomRuntimeState
    from yosoi.observations.models.dom import DomSnapshot as DomSnapshot
    from yosoi.observations.models.dom import DomVisibility as DomVisibility
    from yosoi.observations.models.index import IndexEntry as IndexEntry
    from yosoi.observations.models.index import ObservationIndex as ObservationIndex
    from yosoi.observations.models.snapshot import CaptureCapability as CaptureCapability
    from yosoi.observations.models.snapshot import CaptureProfile as CaptureProfile
    from yosoi.observations.models.snapshot import ObservationSnapshot as ObservationSnapshot
    from yosoi.observations.models.view import PrunedFragment as PrunedFragment
    from yosoi.observations.models.view import PrunedView as PrunedView
    from yosoi.observations.models.view import PruningStats as PruningStats
    from yosoi.observations.models.view import RegionRef as RegionRef
    from yosoi.observations.models.view import RenderedView as RenderedView

_LAZY = {
    'ArtifactRef': 'yosoi.observations.models.artifact',
    'CaptureCapability': 'yosoi.observations.models.snapshot',
    'CaptureProfile': 'yosoi.observations.models.snapshot',
    'DomAttribute': 'yosoi.observations.models.dom',
    'DomCapability': 'yosoi.observations.models.dom',
    'DomCapabilityKind': 'yosoi.observations.models.dom',
    'DomGeometry': 'yosoi.observations.models.dom',
    'DomNode': 'yosoi.observations.models.dom',
    'DomRuntimeState': 'yosoi.observations.models.dom',
    'DomSnapshot': 'yosoi.observations.models.dom',
    'DomVisibility': 'yosoi.observations.models.dom',
    'EvidenceKind': 'yosoi.observations.models.artifact',
    'IndexEntry': 'yosoi.observations.models.index',
    'ObservationIndex': 'yosoi.observations.models.index',
    'ObservationSnapshot': 'yosoi.observations.models.snapshot',
    'PrunedFragment': 'yosoi.observations.models.view',
    'PrunedView': 'yosoi.observations.models.view',
    'PruningStats': 'yosoi.observations.models.view',
    'RegionRef': 'yosoi.observations.models.view',
    'RenderedView': 'yosoi.observations.models.view',
    'Sensitivity': 'yosoi.observations.models.artifact',
}

__all__ = sorted(_LAZY)
__getattr__, __dir__ = lazy_exports(__name__, globals(), _LAZY)
