"""Shared internals for sink backends: driver-import errors and time helpers."""

from __future__ import annotations

from datetime import datetime, timezone


class MissingSinkDependencyError(ImportError):
    """Raised when an optional sink driver is not installed.

    Subclasses :class:`ImportError` so existing ``except ImportError`` handlers
    keep working, while the message tells the user exactly which extra to add.
    """


def missing_dependency(driver: str, extra: str) -> MissingSinkDependencyError:
    """Build a helpful error for a missing optional driver.

    Args:
        driver: The import name that failed (e.g. ``'pymongo'``).
        extra: The Yosoi extra that provides it (e.g. ``'mongo'``).

    """
    return MissingSinkDependencyError(
        f'{driver} is required for this sink but is not installed. '
        f"Install it with: uv add 'yosoi[{extra}]'  (or: pip install 'yosoi[{extra}]')"
    )


def to_utc(dt: datetime) -> datetime:
    """Normalise a datetime to timezone-aware UTC.

    Naive datetimes are assumed to already be UTC. This keeps stored timestamps
    comparable across backends and makes ISO-string range queries correct.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
