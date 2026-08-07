"""Deterministic serialization helpers for observation snapshot manifests."""

from __future__ import annotations

import json

from yosoi.observations.models.snapshot import ObservationSnapshot


def manifest_bytes(snapshot: ObservationSnapshot) -> bytes:
    """Serialize a snapshot manifest deterministically for hashing and golden tests."""
    payload = snapshot.model_dump(mode='json')
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


__all__ = ['manifest_bytes']
