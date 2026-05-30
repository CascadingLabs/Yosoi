"""Durable replay contracts for MCP-discovered browser lessons."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from yosoi.models.selectors import SelectorEntry
from yosoi.models.snapshot import SelectorSnapshot


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class ReplayStatus(str, Enum):
    """Operational state for a persisted discovery lesson."""

    ACTIVE = 'active'
    STALE = 'stale'
    DISABLED = 'disabled'


class ActKind(str, Enum):
    """Browser action kinds that can be replayed deterministically."""

    NAVIGATE = 'navigate'
    CLICK = 'click'
    TYPE = 'type'
    SCROLL = 'scroll'
    WAIT = 'wait'
    EVAL = 'eval'
    TELEPORT = 'teleport'


class AssertKind(str, Enum):
    """Observable condition kinds used by replay-node assess/expect steps."""

    URL = 'url'
    SELECTOR = 'selector'
    TEXT = 'text'
    COUNT = 'count'
    DOM_STABLE = 'dom_stable'
    AX_TARGET = 'ax_target'
    NONE = 'none'


class ReplayCondition(BaseModel):
    """An observable page condition for assess/assert phases."""

    kind: AssertKind = AssertKind.NONE
    selector: SelectorEntry | None = None
    value: str | int | float | bool | None = None
    timeout_ms: int = Field(default=5000, ge=0)
    quiet_ms: int | None = Field(default=None, ge=0)


class ReplayAct(BaseModel):
    """A deterministic browser action with an ordered target cascade."""

    kind: ActKind
    url: str | None = None
    text: str | None = None
    script: str | None = None
    targets: list[SelectorEntry] = Field(default_factory=list)
    repeat: bool = False
    max_repeats: int = Field(default=1, ge=1)
    dwell_ms: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    output_field: str | None = None

    @model_validator(mode='after')
    def validate_action_payload(self) -> ReplayAct:
        """Require the payload shape needed by action kinds that cannot infer it."""
        if self.kind == ActKind.NAVIGATE and not self.url:
            raise ValueError('navigate acts require url')
        if self.kind == ActKind.CLICK and not self.targets:
            raise ValueError('click acts require at least one target')
        if self.kind == ActKind.TYPE and (not self.targets or self.text is None):
            raise ValueError('type acts require targets and text')
        if self.kind == ActKind.EVAL and not self.script:
            raise ValueError('eval acts require script')
        return self


class ReplayNode(BaseModel):
    """Assess / Act / Assert replay primitive."""

    id: str
    intent: str
    assess: ReplayCondition = Field(default_factory=ReplayCondition)
    act: ReplayAct
    expect: ReplayCondition = Field(default_factory=ReplayCondition)


class ReplayPlan(BaseModel):
    """Flat sequence of replay nodes for one learned browser state."""

    nodes: list[ReplayNode] = Field(default_factory=list)
    version: int = 1

    @property
    def is_empty(self) -> bool:
        """Return whether the plan has no browser actions."""
        return len(self.nodes) == 0


class VerifyReport(BaseModel):
    """Replay verification result used as a lesson staleness oracle."""

    passed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    failures: list[str] = Field(default_factory=list)

    @property
    def total(self) -> int:
        """Total number of assertions considered."""
        return self.passed + self.failed

    @property
    def score(self) -> float:
        """Pass ratio, with an empty report considered fully passing."""
        if self.total == 0:
            return 1.0
        return self.passed / self.total


class LessonKey(BaseModel):
    """Stable identity for a discovery lesson."""

    domain: str
    contract_signature: str
    page_profile: str = 'default'
    mode: Literal['mcp'] = 'mcp'

    @property
    def storage_key(self) -> str:
        """Filesystem-safe key for lesson persistence."""
        raw = f'{self.domain}__{self.contract_signature}__{self.page_profile}__{self.mode}'
        return ''.join(ch if ch.isalnum() or ch in ('-', '_') else '_' for ch in raw)


class LessonTrace(BaseModel):
    """Trace references for auditing how a lesson was learned."""

    langfuse_trace_id: str | None = None
    opencode_session_id: str | None = None
    transcript_digest: str | None = None


class LessonProvenance(BaseModel):
    """Version and model metadata for a learned lesson."""

    discovered_at: AwareDatetime = Field(default_factory=utc_now)
    model_name: str | None = None
    provider: str | None = None
    yosoi_version: str | None = None
    voidcrawl_version: str | None = None


class LessonStats(BaseModel):
    """Replay counters and failure audit state."""

    replay_count: int = Field(default=0, ge=0)
    failure_count: int = Field(default=0, ge=0)
    last_replayed_at: AwareDatetime | None = None
    last_verified_at: AwareDatetime | None = None
    last_failed_at: AwareDatetime | None = None


class LessonValidation(BaseModel):
    """Validation evidence captured before a lesson becomes active."""

    report: VerifyReport = Field(default_factory=VerifyReport)
    threshold: float = Field(default=1.0, ge=0.0, le=1.0)
    sample_values: dict[str, Any] = Field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """Return whether the report meets the configured threshold."""
        return self.report.score >= self.threshold


class DiscoveryLesson(BaseModel):
    """Persisted MCP discovery artifact for replay-first scraping."""

    key: LessonKey
    replay_plan: ReplayPlan
    selectors: dict[str, SelectorSnapshot]
    validation: LessonValidation = Field(default_factory=LessonValidation)
    trace: LessonTrace = Field(default_factory=LessonTrace)
    provenance: LessonProvenance = Field(default_factory=LessonProvenance)
    stats: LessonStats = Field(default_factory=LessonStats)
    status: ReplayStatus = ReplayStatus.ACTIVE
    status_reason: str | None = None

    @property
    def is_active(self) -> bool:
        """Return whether the lesson is eligible for replay."""
        return self.status == ReplayStatus.ACTIVE and self.validation.passed
