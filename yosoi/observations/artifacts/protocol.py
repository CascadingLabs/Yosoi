"""Immutable content-store boundary for canonical observation artifacts."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from yosoi.observations.models.artifact import ArtifactRef, EvidenceKind, Sensitivity


class ArtifactIntegrityError(RuntimeError):
    """Raised when stored bytes do not match an exact artifact reference."""


@runtime_checkable
class ArtifactStore(Protocol):
    """Store policy-safe bytes by digest without exposing mutation operations."""

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
        """Persist policy-safe canonical bytes and return their exact reference."""
        ...

    def read(self, ref: ArtifactRef) -> bytes:
        """Read bytes only when they match the supplied exact reference."""
        ...

    def contains(self, ref: ArtifactRef) -> bool:
        """Return whether an exact, integrity-valid reference is available."""
        ...


__all__ = ['ArtifactIntegrityError', 'ArtifactStore']
