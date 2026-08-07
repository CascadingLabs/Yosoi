"""Fail-closed validation for snapshot-local observation references."""

from __future__ import annotations

from yosoi.observations.models.index import IndexEntry, ObservationIndex
from yosoi.observations.models.view import RegionRef


class ObservationAddressError(LookupError):
    """Raised when an observation reference is stale, foreign, or absent."""


def resolve_index_entry(index: ObservationIndex, ref: RegionRef) -> IndexEntry:
    """Resolve an exact reference from a flat index without fuzzy fallback."""
    if ref.snapshot_id != index.snapshot_id:
        raise ObservationAddressError('observation reference belongs to a different snapshot')
    matches = [entry for entry in index.entries if entry.ref == ref]
    if len(matches) != 1:
        raise ObservationAddressError(f'observation reference resolved to {len(matches)} index entries')
    return matches[0]


__all__ = ['ObservationAddressError', 'resolve_index_entry']
