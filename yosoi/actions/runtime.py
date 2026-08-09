"""Browser-neutral orchestration for exactly one evidence-ledgered action."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from yosoi.actions.errors import ActionBoundaryError
from yosoi.actions.models import (
    ActionErrorCode,
    ActionSpec,
    AssertionResult,
    AssertionStatus,
    CaptureRef,
    DispatchEvidence,
    DispatchStatus,
    FreshnessStatus,
    OutcomeStatus,
    PolicyEvidence,
    PolicyStatus,
    ReceiptTiming,
    ResolutionEvidence,
    ResolutionStatus,
    SettlementStatus,
    TransitionReceipt,
)
from yosoi.actions.protocols import (
    ActionPolicy,
    ResolvedTarget,
    RetainedActionSession,
    SettlementResult,
    TargetResolver,
    TransitionVerifier,
)

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ActionRuntime:
    """Compose injected boundaries without owning browser/session resources."""

    def __init__(
        self,
        *,
        session: RetainedActionSession,
        resolver: TargetResolver,
        policy: ActionPolicy,
        verifier: TransitionVerifier,
        redaction_version: str,
        clock: Clock = _utc_now,
    ) -> None:
        """Bind injected boundaries and a model-safe redaction version."""
        self._session = session
        self._resolver = resolver
        self._policy = policy
        self._verifier = verifier
        self._redaction_version = redaction_version
        self._clock = clock

    async def perform(self, *, before: CaptureRef, action: ActionSpec) -> TransitionReceipt:  # noqa: C901
        """Attempt one transition and return normalized evidence for expected failures.

        Only :class:`ActionBoundaryError` is normalized. Unexpected exceptions propagate so
        programming defects are not disguised as ordinary browser outcomes.
        """
        if action.target is not None and action.target.snapshot_id != before.snapshot_id:
            raise ValueError('action target must belong to the before capture')
        started_at = self._clock()
        resolution = self._initial_resolution(action)
        policy = self._unevaluated_policy()
        dispatch = DispatchEvidence(status=DispatchStatus.NOT_ATTEMPTED)

        try:
            active = await self._session.active_capture()
        except ActionBoundaryError as exc:
            return self._receipt(
                started_at=started_at,
                before=before,
                action=action,
                freshness=FreshnessStatus.UNKNOWN,
                resolution=resolution,
                policy=policy,
                dispatch=dispatch,
                settlement=SettlementResult(SettlementStatus.NOT_OBSERVED),
                outcome=OutcomeStatus.FAILED,
                error_code=exc.code,
            )
        if active != before:
            return self._receipt(
                started_at=started_at,
                before=before,
                action=action,
                freshness=FreshnessStatus.STALE,
                resolution=resolution,
                policy=policy,
                dispatch=dispatch,
                settlement=SettlementResult(SettlementStatus.NOT_OBSERVED),
                outcome=OutcomeStatus.STALE,
                error_code=ActionErrorCode.STALE_BEFORE_CAPTURE,
            )

        resolved = ResolvedTarget(evidence=resolution)
        if action.target is not None:
            try:
                resolved = await self._resolver.resolve(self._session, before, action.target)
            except ActionBoundaryError as exc:
                return self._failed_boundary(started_at, before, action, resolution, policy, dispatch, exc.code)
            terminal = self._resolution_terminal(resolved.evidence.status)
            if terminal is not None:
                outcome, error_code = terminal
                return self._receipt(
                    started_at=started_at,
                    before=before,
                    action=action,
                    freshness=FreshnessStatus.FRESH,
                    resolution=resolved.evidence,
                    policy=policy,
                    dispatch=dispatch,
                    settlement=SettlementResult(SettlementStatus.NOT_OBSERVED),
                    outcome=outcome,
                    error_code=error_code,
                )

        try:
            policy = await self._policy.decide(before, action, resolved.evidence)
        except ActionBoundaryError as exc:
            return self._failed_boundary(started_at, before, action, resolved.evidence, policy, dispatch, exc.code)
        if policy.status is not PolicyStatus.ALLOWED:
            outcome = OutcomeStatus.BLOCKED if policy.status is PolicyStatus.BLOCKED else OutcomeStatus.UNSUPPORTED
            error = (
                ActionErrorCode.POLICY_BLOCKED
                if policy.status is PolicyStatus.BLOCKED
                else policy.unsupported_error or ActionErrorCode.UNSUPPORTED_EFFECT
            )
            return self._receipt(
                started_at=started_at,
                before=before,
                action=action,
                freshness=FreshnessStatus.FRESH,
                resolution=resolved.evidence,
                policy=policy,
                dispatch=dispatch,
                settlement=SettlementResult(SettlementStatus.NOT_OBSERVED),
                outcome=outcome,
                error_code=error,
            )

        try:
            await self._session.arm_observers(action, resolved.handle)
        except ActionBoundaryError as exc:
            return self._failed_boundary(started_at, before, action, resolved.evidence, policy, dispatch, exc.code)
        try:
            try:
                dispatch = await self._session.dispatch(action, resolved.handle)
            except ActionBoundaryError as exc:
                if exc.code is ActionErrorCode.DISPATCH_FAILED:
                    dispatch = DispatchEvidence(status=DispatchStatus.FAILED)
                return self._failed_boundary(started_at, before, action, resolved.evidence, policy, dispatch, exc.code)
            if dispatch.status is not DispatchStatus.DISPATCHED:
                return self._receipt(
                    started_at=started_at,
                    before=before,
                    action=action,
                    freshness=FreshnessStatus.FRESH,
                    resolution=resolved.evidence,
                    policy=policy,
                    dispatch=dispatch,
                    settlement=SettlementResult(SettlementStatus.NOT_OBSERVED),
                    outcome=OutcomeStatus.FAILED,
                    error_code=ActionErrorCode.DISPATCH_FAILED,
                )

            try:
                settlement = await self._session.settle(action, dispatch)
            except ActionBoundaryError as exc:
                return self._failed_boundary(started_at, before, action, resolved.evidence, policy, dispatch, exc.code)
        finally:
            await self._session.cleanup_observers()
        if settlement.status in {SettlementStatus.TIMED_OUT, SettlementStatus.INCONCLUSIVE}:
            after = await self._capture_after_if_available(before)
            outcome = (
                OutcomeStatus.TIMED_OUT
                if settlement.status is SettlementStatus.TIMED_OUT
                else OutcomeStatus.INCONCLUSIVE
            )
            error = (
                ActionErrorCode.SETTLEMENT_TIMEOUT
                if settlement.status is SettlementStatus.TIMED_OUT
                else ActionErrorCode.SETTLEMENT_INCONCLUSIVE
            )
            assertions: tuple[AssertionResult, ...] = ()
            if after is not None:
                try:
                    assertions = await self._verifier.verify(before, action, after, settlement)
                except ActionBoundaryError as exc:
                    # A verifier boundary failure has deterministic precedence over the
                    # settlement verdict, while the settlement evidence remains recorded.
                    return self._receipt(
                        started_at=started_at,
                        before=before,
                        action=action,
                        freshness=FreshnessStatus.FRESH,
                        resolution=resolved.evidence,
                        policy=policy,
                        dispatch=dispatch,
                        settlement=settlement,
                        outcome=OutcomeStatus.FAILED,
                        error_code=exc.code,
                        after=after,
                    )
                if not assertions:
                    assertions = (
                        AssertionResult(
                            assertion_id='postcondition',
                            status=AssertionStatus.UNSUPPORTED,
                            reason_code='missing_evidence',
                        ),
                    )
            return self._receipt(
                started_at=started_at,
                before=before,
                action=action,
                freshness=FreshnessStatus.FRESH,
                resolution=resolved.evidence,
                policy=policy,
                dispatch=dispatch,
                settlement=settlement,
                assertions=assertions,
                outcome=outcome,
                error_code=error,
                after=after,
            )
        if settlement.status is not SettlementStatus.SETTLED:
            return self._receipt(
                started_at=started_at,
                before=before,
                action=action,
                freshness=FreshnessStatus.FRESH,
                resolution=resolved.evidence,
                policy=policy,
                dispatch=dispatch,
                settlement=settlement,
                outcome=OutcomeStatus.FAILED,
                error_code=ActionErrorCode.INTEGRITY_FAILED,
            )

        try:
            after = await self._session.capture_after(parent_snapshot_id=before.snapshot_id)
        except ActionBoundaryError:
            return self._receipt(
                started_at=started_at,
                before=before,
                action=action,
                freshness=FreshnessStatus.FRESH,
                resolution=resolved.evidence,
                policy=policy,
                dispatch=dispatch,
                settlement=settlement,
                outcome=OutcomeStatus.FAILED,
                error_code=ActionErrorCode.AFTER_CAPTURE_FAILED,
            )
        try:
            assertions = await self._verifier.verify(before, action, after, settlement)
        except ActionBoundaryError as exc:
            return self._receipt(
                started_at=started_at,
                before=before,
                action=action,
                freshness=FreshnessStatus.FRESH,
                resolution=resolved.evidence,
                policy=policy,
                dispatch=dispatch,
                settlement=settlement,
                outcome=OutcomeStatus.FAILED,
                error_code=exc.code,
                after=after,
            )
        if not assertions:
            assertions = (
                AssertionResult(
                    assertion_id='postcondition',
                    status=AssertionStatus.UNSUPPORTED,
                    reason_code='missing_evidence',
                ),
            )
        if any(result.status is AssertionStatus.FAILED for result in assertions):
            outcome, error = OutcomeStatus.FAILED, ActionErrorCode.ASSERTION_FAILED
        elif not assertions or any(result.status is not AssertionStatus.PASSED for result in assertions):
            outcome, error = OutcomeStatus.INCONCLUSIVE, ActionErrorCode.ASSERTION_INCONCLUSIVE
        else:
            outcome, error = OutcomeStatus.SUCCESS, None
        return self._receipt(
            started_at=started_at,
            before=before,
            action=action,
            freshness=FreshnessStatus.FRESH,
            resolution=resolved.evidence,
            policy=policy,
            dispatch=dispatch,
            settlement=settlement,
            assertions=assertions,
            outcome=outcome,
            error_code=error,
            after=after,
        )

    def _initial_resolution(self, action: ActionSpec) -> ResolutionEvidence:
        status = ResolutionStatus.NOT_EVALUATED if action.target is not None else ResolutionStatus.NOT_REQUIRED
        return ResolutionEvidence(status=status, candidate_count=0)

    def _unevaluated_policy(self) -> PolicyEvidence:
        return PolicyEvidence(
            status=PolicyStatus.NOT_EVALUATED,
            policy_version='not-evaluated',
            rule_id='not-evaluated',
        )

    def _resolution_terminal(self, status: ResolutionStatus) -> tuple[OutcomeStatus, ActionErrorCode] | None:
        return {
            ResolutionStatus.NOT_FOUND: (OutcomeStatus.NOT_FOUND, ActionErrorCode.TARGET_NOT_FOUND),
            ResolutionStatus.AMBIGUOUS: (OutcomeStatus.AMBIGUOUS, ActionErrorCode.TARGET_AMBIGUOUS),
            ResolutionStatus.UNSUPPORTED: (OutcomeStatus.UNSUPPORTED, ActionErrorCode.UNSUPPORTED_ACTION),
        }.get(status)

    async def _capture_after_if_available(self, before: CaptureRef) -> CaptureRef | None:
        try:
            return await self._session.capture_after(parent_snapshot_id=before.snapshot_id)
        except ActionBoundaryError:
            return None

    def _failed_boundary(
        self,
        started_at: datetime,
        before: CaptureRef,
        action: ActionSpec,
        resolution: ResolutionEvidence,
        policy: PolicyEvidence,
        dispatch: DispatchEvidence,
        code: ActionErrorCode,
    ) -> TransitionReceipt:
        return self._receipt(
            started_at=started_at,
            before=before,
            action=action,
            freshness=FreshnessStatus.FRESH,
            resolution=resolution,
            policy=policy,
            dispatch=dispatch,
            settlement=SettlementResult(SettlementStatus.NOT_OBSERVED),
            outcome=OutcomeStatus.FAILED,
            error_code=code,
        )

    def _receipt(
        self,
        *,
        started_at: datetime,
        before: CaptureRef,
        action: ActionSpec,
        freshness: FreshnessStatus,
        resolution: ResolutionEvidence,
        policy: PolicyEvidence,
        dispatch: DispatchEvidence,
        settlement: SettlementResult,
        outcome: OutcomeStatus,
        error_code: ActionErrorCode | None,
        assertions: tuple = (),
        after: CaptureRef | None = None,
    ) -> TransitionReceipt:
        return TransitionReceipt(
            before=before,
            action=action,
            freshness=freshness,
            resolution=resolution,
            policy=policy,
            dispatch=dispatch,
            settlement=settlement.status,
            settlement_observations=settlement.observations,
            assertions=assertions,
            after=after,
            outcome=outcome,
            error_code=error_code,
            redaction_version=self._redaction_version,
            timing=ReceiptTiming(started_at=started_at, finished_at=self._clock()),
        )


__all__ = ['ActionRuntime', 'Clock']
