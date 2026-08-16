"""Canonical observation artifact storage boundaries."""

from __future__ import annotations

from typing import TYPE_CHECKING

from yosoi._lazy import lazy_exports

if TYPE_CHECKING:
    from yosoi.observations.artifacts.filesystem import FilesystemArtifactStore as FilesystemArtifactStore
    from yosoi.observations.artifacts.manifest import manifest_bytes as manifest_bytes
    from yosoi.observations.artifacts.memory import MemoryArtifactStore as MemoryArtifactStore
    from yosoi.observations.artifacts.protocol import ArtifactIntegrityError as ArtifactIntegrityError
    from yosoi.observations.artifacts.protocol import ArtifactStore as ArtifactStore

_LAZY = {
    'ArtifactIntegrityError': 'yosoi.observations.artifacts.protocol',
    'ArtifactStore': 'yosoi.observations.artifacts.protocol',
    'FilesystemArtifactStore': 'yosoi.observations.artifacts.filesystem',
    'MemoryArtifactStore': 'yosoi.observations.artifacts.memory',
    'manifest_bytes': 'yosoi.observations.artifacts.manifest',
}

__all__ = sorted(_LAZY)
__getattr__, __dir__ = lazy_exports(__name__, globals(), _LAZY)
