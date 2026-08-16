"""Injected browser-neutral boundaries for executing one action."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from yosoi.actions.models import (
    ActionSpec,
    AssertionResult,
    CaptureRef,
    DispatchEvidence,
    ElementRef,
    PolicyEvidence,
    ResolutionEvidence,
    SettlementObservation,
    SettlementStatus,
)


@dataclass(frozen=True)
class ResolvedTarget:
    """Runtime-only target handle paired with serializable resolution evidence."""

    evidence: ResolutionEvidence
    handle: object | None = None


@dataclass(frozen=True)
class SettlementResult:
    """Serializable settlement verdict returned by a retained session."""

    status: SettlementStatus
    observations: tuple[SettlementObservation, ...] = ()


class RetainedActionSession(Protocol):
    """Borrowed session; implementations own acquisition, lifetime, and pooling."""

    async def active_capture(self) -> CaptureRef:
        """Return the exact capture corresponding to the session's active epoch."""
        ...

    async def arm_observers(self, action: ActionSpec, target: object | None) -> None:
        """Arm bounded passive observers before dispatch."""
        ...

    async def dispatch(self, action: ActionSpec, target: object | None) -> DispatchEvidence:
        """Dispatch exactly one typed action."""
        ...

    async def settle(self, action: ActionSpec, dispatch: DispatchEvidence) -> SettlementResult:
        """Observe settlement without issuing another action or sleeping blindly."""
        ...

    async def cleanup_observers(self) -> None:
        """Disarm any observer not consumed by settlement."""
        ...

    async def capture_after(self, *, parent_snapshot_id: str) -> CaptureRef:
        """Capture one coherent post-action state linked to its parent."""
        ...


class TargetResolver(Protocol):
    """Bind evidence provenance to at most one live browser target."""

    async def resolve(
        self,
        session: RetainedActionSession,
        before: CaptureRef,
        target: ElementRef,
    ) -> ResolvedTarget:
        """Resolve a capture-bound target uniquely against the retained session."""
        ...


class ActionPolicy(Protocol):
    """Authorize a typed action after target resolution."""

    async def decide(
        self,
        before: CaptureRef,
        action: ActionSpec,
        resolution: ResolutionEvidence,
    ) -> PolicyEvidence:
        """Authorize one resolved action without dispatching it."""
        ...


class TransitionVerifier(Protocol):
    """Evaluate deterministic postconditions over retained evidence."""

    async def verify(
        self,
        before: CaptureRef,
        action: ActionSpec,
        after: CaptureRef,
        settlement: SettlementResult,
    ) -> tuple[AssertionResult, ...]:
        """Evaluate deterministic transition-integrity postconditions."""
        ...


__all__ = [
    'ActionPolicy',
    'ResolvedTarget',
    'RetainedActionSession',
    'SettlementResult',
    'TargetResolver',
    'TransitionVerifier',
]
