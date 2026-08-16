"""QA findings and run-level audit report contracts."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from yosoi.observations.models.view import RegionRef


class FindingSeverity(str, Enum):
    """User-facing severity assigned to a QA finding."""

    INFO = 'info'
    WARNING = 'warning'
    ERROR = 'error'
    CRITICAL = 'critical'


class ClaimKind(str, Enum):
    """Whether report text is directly observed or inferred by a model."""

    OBSERVED = 'observed'
    INFERRED = 'inferred'


class QAFinding(BaseModel):
    """One QA claim linked to exact observation evidence where available."""

    model_config = ConfigDict(frozen=True)

    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    severity: FindingSeverity
    claim_kind: ClaimKind
    evidence: tuple[RegionRef, ...] = ()


class QAReport(BaseModel):
    """Provider-neutral output and audit counters for one QA run."""

    model_config = ConfigDict(frozen=True)

    run_id: str = Field(min_length=1)
    findings: tuple[QAFinding, ...] = ()
    snapshot_ids: tuple[str, ...] = ()
    model_name: str | None = None
    tool_calls: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


__all__ = ['ClaimKind', 'FindingSeverity', 'QAFinding', 'QAReport']
