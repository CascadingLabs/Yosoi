"""Run, episode, snapshot, and capability contracts for multimodal evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from yosoi.observations.models.artifact import OBSERVATION_SCHEMA_VERSION, ArtifactRef, EvidenceKind


class CaptureProfile(str, Enum):
    """Requested acquisition behavior; independent from captured modalities."""

    HTTP_STATIC = 'http_static'
    BROWSER_HEADLESS = 'browser_headless'
    BROWSER_HEADFUL = 'browser_headful'
    BROWSER_MINIMAL_CDP = 'browser_minimal_cdp'


class CaptureCapability(BaseModel):
    """Whether one evidence modality was actually available for a snapshot."""

    model_config = ConfigDict(frozen=True)

    kind: EvidenceKind
    available: bool
    reason: str | None = None


class ObservationSnapshot(BaseModel):
    """Manifest for one exact page state in a potentially multi-shot episode."""

    model_config = ConfigDict(frozen=True)

    schema_version: str = OBSERVATION_SCHEMA_VERSION
    run_id: str = Field(min_length=1)
    episode_id: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    parent_snapshot_id: str | None = None
    captured_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    requested_profile: CaptureProfile
    artifacts: tuple[ArtifactRef, ...] = ()
    capabilities: tuple[CaptureCapability, ...] = ()
    page_fingerprint_id: str | None = None

    @model_validator(mode='after')
    def _validate_identity_graph(self) -> ObservationSnapshot:
        if self.parent_snapshot_id == self.snapshot_id:
            raise ValueError('a snapshot cannot be its own parent')
        if any(artifact.snapshot_id != self.snapshot_id for artifact in self.artifacts):
            raise ValueError('every artifact must belong to the containing snapshot')
        capability_kinds = [capability.kind for capability in self.capabilities]
        if len(capability_kinds) != len(set(capability_kinds)):
            raise ValueError('snapshot capabilities must contain at most one entry per evidence kind')
        return self


__all__ = ['CaptureCapability', 'CaptureProfile', 'ObservationSnapshot']
