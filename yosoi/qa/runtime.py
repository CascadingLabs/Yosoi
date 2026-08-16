"""Provider-neutral QA composition contracts and fail-closed runtime scaffold."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from yosoi.observations.models.snapshot import CaptureProfile
from yosoi.qa.reports import QAReport


class QAStatus(str, Enum):
    """Terminal state of an attempted QA run."""

    COMPLETED = 'completed'
    FAILED = 'failed'
    INTERRUPTED = 'interrupted'


class QARequest(BaseModel):
    """Task-level request independent from provider configuration and credentials."""

    model_config = ConfigDict(frozen=True)

    url: str = Field(min_length=1)
    objective: str = Field(default='Find user-visible defects.', min_length=1)
    capture_profile: CaptureProfile = CaptureProfile.BROWSER_HEADLESS
    max_turns: int = Field(default=8, gt=0)
    max_tool_calls: int = Field(default=24, gt=0)


class QAResult(BaseModel):
    """Envelope around a completed, failed, or interrupted QA report."""

    model_config = ConfigDict(frozen=True)

    status: QAStatus
    report: QAReport | None = None
    error: str | None = None


class QARuntime:
    """Future composition root for capture, indexing, provider tools, and reporting."""

    async def run(self, request: QARequest) -> QAResult:
        """Refuse execution until capture, tools, and provider boundaries are wired."""
        raise NotImplementedError('the QA runtime is not wired; see qa/ROADMAP.md')


__all__ = ['QARequest', 'QAResult', 'QARuntime', 'QAStatus']
