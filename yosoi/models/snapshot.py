"""Snapshot-based caching models for per-field selector staleness tracking."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, Field


class CacheVerdict(str, Enum):
    """Result of verifying a cached selector against current HTML."""

    FRESH = 'fresh'
    STALE = 'stale'
    DEGRADED = 'degraded'  # stub: treated as STALE for now


class SelectorSnapshot(BaseModel):
    """Per-field selector data with audit metadata."""

    primary: str | dict[str, Any] | None = None
    fallback: str | dict[str, Any] | None = None
    tertiary: str | dict[str, Any] | None = None
    discovered_at: AwareDatetime
    last_verified_at: AwareDatetime | None = None
    last_failed_at: AwareDatetime | None = None
    failure_count: int = 0
    source: Literal['discovered', 'pinned', 'override'] = 'discovered'
    parent_root: str | None = None


class SnapshotMap(BaseModel):
    """Top-level cache file with per-field snapshots."""

    url: str
    domain: str
    snapshots: dict[str, SelectorSnapshot] = Field(default_factory=dict)


def snapshot_to_selector_dict(snap: SelectorSnapshot) -> dict[str, Any]:
    """Extract just the primary/fallback/tertiary selector data from a snapshot."""
    result: dict[str, Any] = {}
    if snap.primary is not None:
        result['primary'] = snap.primary
    if snap.fallback is not None:
        result['fallback'] = snap.fallback
    if snap.tertiary is not None:
        result['tertiary'] = snap.tertiary
    return result


def selector_dict_to_snapshot(
    field_data: dict[str, Any],
    discovered_at: datetime | None = None,
    source: Literal['discovered', 'pinned', 'override'] = 'discovered',
    parent_root: str | None = None,
    last_verified_at: datetime | None = None,
) -> SelectorSnapshot:
    """Wrap a raw selector dict into a SelectorSnapshot."""
    ts = discovered_at or datetime.now(timezone.utc)
    return SelectorSnapshot(
        primary=field_data.get('primary'),
        fallback=field_data.get('fallback'),
        tertiary=field_data.get('tertiary'),
        discovered_at=ts,
        last_verified_at=last_verified_at,
        source=source,
        parent_root=parent_root,
    )
