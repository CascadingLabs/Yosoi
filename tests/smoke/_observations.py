"""Shared checks for the live observation-pruning smoke tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from yosoi.observations.index.inspect import InspectionBudget

if TYPE_CHECKING:
    from yosoi.observations.index.inspect import ObservationInspector
    from yosoi.observations.models.index import IndexEntry


def resolution_failure(inspector: ObservationInspector, entry: IndexEntry) -> str | None:
    """Return a human-readable reason this entry failed to resolve, or None if it resolved.

    Returns rather than raises so a caller can report every dead address in one assertion
    instead of stopping at the first. A raising resolver is itself a finding, so the
    exception is captured as text rather than propagated.
    """
    try:
        content = inspector.inspect(entry.ref, InspectionBudget()).content
    except Exception as exc:  # noqa: BLE001 — any resolver failure is a finding, not just the expected one
        return f'{entry.ordinal} {entry.label} ({type(exc).__name__}: {exc})'
    return None if content else f'{entry.ordinal} {entry.label} (empty)'
