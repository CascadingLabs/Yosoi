"""Deterministic in-memory artifact store used by unit tests and early slices."""

from __future__ import annotations

import hashlib

from yosoi.observations.artifacts.protocol import ArtifactIntegrityError
from yosoi.observations.models.artifact import ArtifactRef, EvidenceKind, Sensitivity


class MemoryArtifactStore:
    """Keep immutable artifact bytes in process, keyed by exact SHA-256 digest."""

    def __init__(self) -> None:
        """Create an empty process-local immutable blob map."""
        self._blobs: dict[str, bytes] = {}

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
        """Store a defensive copy and return its exact immutable reference."""
        blob = bytes(data)
        digest = hashlib.sha256(blob).hexdigest()
        self._blobs.setdefault(digest, blob)
        return ArtifactRef(
            snapshot_id=snapshot_id,
            kind=kind,
            sha256=digest,
            media_type=media_type,
            size_bytes=len(blob),
            sensitivity=sensitivity,
            redactions=redactions,
        )

    def read(self, ref: ArtifactRef) -> bytes:
        """Return bytes only after verifying size and digest integrity."""
        try:
            blob = self._blobs[ref.sha256]
        except KeyError as exc:
            raise FileNotFoundError(f'observation artifact {ref.sha256!r} is not present') from exc
        if len(blob) != ref.size_bytes or hashlib.sha256(blob).hexdigest() != ref.sha256:
            raise ArtifactIntegrityError(f'observation artifact {ref.sha256!r} failed integrity verification')
        return blob

    def contains(self, ref: ArtifactRef) -> bool:
        """Return whether an exact, integrity-valid artifact is present."""
        try:
            self.read(ref)
        except (ArtifactIntegrityError, FileNotFoundError):
            return False
        return True


__all__ = ['MemoryArtifactStore']
