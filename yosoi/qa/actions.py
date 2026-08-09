"""Transport-neutral, fail-closed QA action contracts.

This module describes the boundary only. It does not acquire a browser, dispatch an
action, or persist a transition ledger.
"""

from __future__ import annotations

from enum import Enum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from yosoi.actions.models import ActionSpec, CaptureRef, TransitionReceipt

_SHA256 = r'^[0-9a-f]{64}$'
_SAFE_HANDLE = r'^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,255}$'


class QAActionOutcome(str, Enum):
    """Result envelope state, independent of any transport."""

    COMPLETED = 'completed'
    REFUSED = 'refused'


class QAActionCapabilities(BaseModel):
    """Explicit readiness flags for the complete QA action boundary."""

    model_config = ConfigDict(frozen=True, extra='forbid', strict=True)

    index: bool = False
    capture: bool = False
    actions: bool = False
    deterministic_assertions: bool = False
    a3_recording: bool = False
    live_readiness: bool = False
    operations: tuple[str, ...] = ('capabilities', 'status')


class QAActionStatus(BaseModel):
    """Truthful readiness report without attempting any operation."""

    model_config = ConfigDict(frozen=True, extra='forbid', strict=True)

    ready: bool = False
    message: str = Field(min_length=1)
    capabilities: QAActionCapabilities


class QAActionRequest(BaseModel):
    """One evidence-backed action request; there is no selector or payload channel."""

    model_config = ConfigDict(frozen=True, extra='forbid', strict=True)

    before: CaptureRef
    action: ActionSpec

    @model_validator(mode='after')
    def _target_belongs_to_before_capture(self) -> QAActionRequest:
        if self.action.target is not None and self.action.target.snapshot_id != self.before.snapshot_id:
            raise ValueError('action target must belong to the before capture')
        return self


class QAActionResult(BaseModel):
    """A complete receipt or a bounded handle retaining its exact receipt identity."""

    model_config = ConfigDict(frozen=True, extra='forbid', strict=True)

    status: QAActionOutcome
    receipt: TransitionReceipt | None = None
    receipt_handle: str | None = Field(default=None, pattern=_SAFE_HANDLE)
    receipt_fingerprint: str | None = Field(default=None, pattern=_SHA256)
    before_snapshot_id: str | None = Field(default=None, min_length=1, max_length=256)
    after_snapshot_id: str | None = Field(default=None, min_length=1, max_length=256)

    @model_validator(mode='after')
    def _preserve_receipt_identity(self) -> QAActionResult:
        if self.receipt is None and self.receipt_handle is None:
            if self.status is QAActionOutcome.COMPLETED:
                raise ValueError('completed action results require a receipt or receipt handle')
            if any((self.receipt_fingerprint, self.before_snapshot_id, self.after_snapshot_id)):
                raise ValueError('receipt identity requires a receipt or receipt handle')
            return self
        if self.receipt is not None and self.receipt_handle is not None:
            raise ValueError('provide a full receipt or a receipt handle, not both')
        if self.receipt is not None:
            if self.status is not QAActionOutcome.COMPLETED:
                raise ValueError('a receipt is only valid for a completed action')
            if self.receipt_fingerprint not in (None, self.receipt.fingerprint):
                raise ValueError('receipt fingerprint does not match the receipt')
            if self.before_snapshot_id not in (None, self.receipt.before.snapshot_id):
                raise ValueError('before snapshot id does not match the receipt')
            after_id = self.receipt.after.snapshot_id if self.receipt.after is not None else None
            if self.after_snapshot_id not in (None, after_id):
                raise ValueError('after snapshot id does not match the receipt')
            return self
        if self.status is not QAActionOutcome.COMPLETED:
            raise ValueError('a receipt handle is only valid for a completed action')
        if self.receipt_fingerprint is None or self.before_snapshot_id is None:
            raise ValueError('receipt handles require fingerprint and before snapshot id')
        return self


@runtime_checkable
class QAActionHandler(Protocol):
    """Handler boundary suitable for a future MCP, CLI, or other transport."""

    async def capabilities(self) -> QAActionCapabilities:
        """Report action-surface capabilities without side effects."""
        ...

    async def status(self) -> QAActionStatus:
        """Report action-surface readiness without side effects."""
        ...

    async def execute(self, request: QAActionRequest) -> QAActionResult:
        """Execute one typed action and preserve its transition evidence."""
        ...


class UnwiredQAActionHandler:
    """Fail-closed action handler until live action wiring is deliberately added."""

    async def capabilities(self) -> QAActionCapabilities:
        """Return explicit false flags; no action operation is advertised."""
        return QAActionCapabilities()

    async def status(self) -> QAActionStatus:
        """Report that this additive boundary is not ready for live use."""
        return QAActionStatus(
            message='QA actions are not wired; see qa/ROADMAP.md',
            capabilities=await self.capabilities(),
        )

    async def execute(self, request: QAActionRequest) -> QAActionResult:
        """Refuse execution without touching the supplied evidence or action."""
        raise NotImplementedError('QA action execution is not wired; see qa/ROADMAP.md')


__all__ = [
    'QAActionCapabilities',
    'QAActionHandler',
    'QAActionOutcome',
    'QAActionRequest',
    'QAActionResult',
    'QAActionStatus',
    'UnwiredQAActionHandler',
]
