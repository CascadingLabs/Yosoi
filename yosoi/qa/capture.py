"""QA acquisition adapter contracts without browser-runtime wiring."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from yosoi.observations.models.snapshot import CaptureProfile, ObservationSnapshot


class QACaptureRequest(BaseModel):
    """Requested page and acquisition profile for an opt-in QA episode."""

    model_config = ConfigDict(frozen=True)

    url: str = Field(min_length=1)
    profile: CaptureProfile = CaptureProfile.BROWSER_HEADLESS


@runtime_checkable
class QACaptureSession(Protocol):
    """Retained live session capable of producing related snapshots."""

    async def capture(self, *, parent_snapshot_id: str | None = None) -> ObservationSnapshot:
        """Capture one policy-safe page state from the retained session."""
        ...

    async def close(self) -> None:
        """Release the retained browser/session resources."""
        ...


@runtime_checkable
class QACaptureAdapter(Protocol):
    """Adapter over existing Yosoi/VoidCrawl acquisition infrastructure."""

    async def open(self, request: QACaptureRequest) -> QACaptureSession:
        """Open a retained session through existing acquisition infrastructure."""
        ...


__all__ = ['QACaptureAdapter', 'QACaptureRequest', 'QACaptureSession']
