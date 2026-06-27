"""Snapshot-based caching models for per-field selector staleness tracking."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, Field, model_validator


class CacheVerdict(str, Enum):
    """Result of verifying a cached selector against the current page HTML.

    On each scrape Yosoi tests every cached selector against the live page
    before deciding whether to call the LLM. The verdict determines what
    happens next for that field.

    Attributes:
        FRESH: Selector still matches the page — extract directly, no LLM call needed.
        STALE: Selector no longer matches any elements — triggers re-discovery for this field.
        DEGRADED: Selector matches but quality has dropped — flagged for future re-discovery.

    """

    FRESH = 'fresh'
    STALE = 'stale'
    DEGRADED = 'degraded'  # stub: treated as STALE for now, FUTURE used for event driven pipeline healing when pipeline_mode != maintenance or offline


class SnapshotStatus(str, Enum):
    """Operational health state for a cached field snapshot."""

    ACTIVE = 'active'
    ABSENT = 'absent'
    DISCOVERY_FAILED = 'discovery_failed'
    VERIFICATION_FAILED = 'verification_failed'


class SelectorSnapshot(BaseModel):
    """Per-field selector data with audit metadata.

    Each field in a cache file is stored as a ``SelectorSnapshot``. It holds up
    to three selector candidates (primary, fallback, tertiary) plus timestamps
    that track when the selector was discovered, last verified, and last failed.
    The ``failure_count`` drives automatic staleness detection.

    Attributes:
        primary: Most specific selector value. Can be a CSS string, a dict (for XPath/regex entries), or ``None``.
        fallback: Less specific alternative selector, or ``None``.
        tertiary: Generic last-resort selector, or ``None``.
        discovered_at: UTC timestamp of when the selector was first discovered or pinned.
        last_verified_at: UTC timestamp of the most recent successful verification against live HTML.
        last_failed_at: UTC timestamp of the most recent verification failure, or ``None`` if never failed.
        failure_count: Number of consecutive verification failures. Reset to 0 on success.
        source: How the selector was obtained — ``'discovered'`` (LLM), ``'pinned'`` (contract), or ``'override'`` (manual edit).
        parent_root: Optional parent CSS selector for nested/scoped items within multi-item pages.
        root: Optional full root selector entry for field-scoped extraction.

    """

    primary: str | dict[str, Any] | None = None
    fallback: str | dict[str, Any] | None = None
    tertiary: str | dict[str, Any] | None = None
    discovered_at: AwareDatetime
    last_verified_at: AwareDatetime | None = None
    last_failed_at: AwareDatetime | None = None
    failure_count: int = 0
    source: Literal['discovered', 'pinned', 'override'] = 'discovered'
    parent_root: str | None = None
    root: str | dict[str, Any] | None = None
    status: SnapshotStatus = SnapshotStatus.ACTIVE
    status_reason: str | None = None
    discovery_record_count: int | None = None
    discovery_field_coverage: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode='before')
    @classmethod
    def _migrate_legacy_absent_sentinel(cls, data: Any) -> Any:
        """Map legacy ``primary: "NA"`` cache entries to explicit absent status."""
        if not isinstance(data, dict) or data.get('primary') != 'NA':
            return data

        migrated = dict(data)
        migrated['primary'] = None
        migrated['fallback'] = None
        migrated['tertiary'] = None
        migrated.setdefault('status', SnapshotStatus.ABSENT)
        migrated.setdefault('status_reason', 'legacy primary=NA sentinel')
        return migrated

    @property
    def is_active(self) -> bool:
        """Whether this snapshot contains selector payload that should be used."""
        return self.status == SnapshotStatus.ACTIVE


class SnapshotMap(BaseModel):
    """Serializable selector snapshot bundle.

    SQLite is the runtime source of truth; this model remains the portable
    import/export/debug shape for a domain's selector snapshots. It maps field
    names to their ``SelectorSnapshot`` entries.

    Attributes:
        url: The source URL this cache was built from.
        domain: The domain name (e.g. ``'example.com'``).
        snapshots: Mapping of contract field names to their cached ``SelectorSnapshot``.

    """

    url: str
    domain: str
    snapshots: dict[str, SelectorSnapshot] = Field(default_factory=dict)


def snapshot_to_selector_dict(snap: SelectorSnapshot) -> dict[str, Any]:
    """Extract just the primary/fallback/tertiary selector data from a snapshot."""
    if not snap.is_active:
        return {}
    result: dict[str, Any] = {}
    if snap.primary is not None:
        result['primary'] = snap.primary
    if snap.fallback is not None:
        result['fallback'] = snap.fallback
    if snap.tertiary is not None:
        result['tertiary'] = snap.tertiary
    if snap.root is not None:
        result['root'] = snap.root
    elif snap.parent_root is not None:
        result['root'] = {'type': 'css', 'value': snap.parent_root}
    return result


def snapshot_to_cache_entry(snap: SelectorSnapshot) -> dict[str, Any]:
    """Return selector payload plus snapshot health for field-task cache checks."""
    result = snapshot_to_selector_dict(snap)
    result['status'] = snap.status
    if snap.status_reason is not None:
        result['status_reason'] = snap.status_reason
    return result


def _ensure_utc(dt: datetime | None) -> datetime | None:
    """Normalize a datetime to timezone-aware UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def selector_dict_to_snapshot(
    field_data: dict[str, Any],
    discovered_at: datetime | None = None,
    source: Literal['discovered', 'pinned', 'override'] = 'discovered',
    parent_root: str | None = None,
    last_verified_at: datetime | None = None,
    discovery_record_count: int | None = None,
    discovery_field_coverage: dict[str, int] | None = None,
) -> SelectorSnapshot:
    """Wrap a raw selector dict into a SelectorSnapshot."""
    ts = _ensure_utc(discovered_at) or datetime.now(timezone.utc)
    status = SnapshotStatus.ABSENT if field_data.get('primary') == 'NA' else SnapshotStatus.ACTIVE
    return SelectorSnapshot(
        primary=None if status != SnapshotStatus.ACTIVE else field_data.get('primary'),
        fallback=None if status != SnapshotStatus.ACTIVE else field_data.get('fallback'),
        tertiary=None if status != SnapshotStatus.ACTIVE else field_data.get('tertiary'),
        discovered_at=ts,
        last_verified_at=_ensure_utc(last_verified_at),
        source=source,
        parent_root=parent_root,
        root=None if status != SnapshotStatus.ACTIVE else field_data.get('root'),
        status=status,
        status_reason='legacy primary=NA sentinel' if status == SnapshotStatus.ABSENT else None,
        discovery_record_count=discovery_record_count,
        discovery_field_coverage=discovery_field_coverage or {},
    )
