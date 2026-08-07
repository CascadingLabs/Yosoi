"""Reserved filesystem-backed canonical artifact store.

The implementation is intentionally absent until atomic writes, retention, restrictive
permissions, and sensitivity handling are specified. Callers should use
:class:`MemoryArtifactStore` while the observation contract is being proven.
"""

from __future__ import annotations

from pathlib import Path

from yosoi.observations.models.artifact import ArtifactRef, EvidenceKind, Sensitivity


class FilesystemArtifactStore:
    """Fail-closed placeholder for future content-addressed local persistence."""

    def __init__(self, root: str | Path) -> None:
        """Remember the intended root without creating or writing it."""
        self.root = Path(root)

    def put(
        self,
        *,
        snapshot_id: str,
        kind: EvidenceKind,
        media_type: str,
        data: bytes,
        sensitivity: Sensitivity = Sensitivity.MODEL_SAFE,
        redactions: tuple[str, ...] = (),
    ) -> ArtifactRef:
        """Refuse writes until persistence safety requirements are implemented."""
        raise NotImplementedError('filesystem observation persistence is not wired; see observations/ROADMAP.md')

    def read(self, ref: ArtifactRef) -> bytes:
        """Refuse reads while the filesystem layout remains unspecified."""
        raise NotImplementedError('filesystem observation persistence is not wired; see observations/ROADMAP.md')

    def contains(self, ref: ArtifactRef) -> bool:
        """Refuse probes while the filesystem layout remains unspecified."""
        raise NotImplementedError('filesystem observation persistence is not wired; see observations/ROADMAP.md')


__all__ = ['FilesystemArtifactStore']
