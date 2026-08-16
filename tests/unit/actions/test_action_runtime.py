import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from yosoi.actions.errors import ActionBoundaryError
from yosoi.actions.models import (
    ActionErrorCode,
    ActionKind,
    ActionSpec,
    AssertionResult,
    AssertionStatus,
    CaptureRef,
    DispatchEvidence,
    DispatchStatus,
    EffectClass,
    ElementRef,
    OutcomeStatus,
    PolicyEvidence,
    PolicyStatus,
    ResolutionEvidence,
    ResolutionStatus,
    SettlementObservation,
    SettlementSignal,
    SettlementStatus,
)
from yosoi.actions.protocols import ResolvedTarget, SettlementResult
from yosoi.actions.runtime import ActionRuntime
from yosoi.observations.models.artifact import EvidenceKind
from yosoi.observations.models.view import RegionRef

_SHA_A = 'a' * 64
_SHA_B = 'b' * 64


def _before() -> CaptureRef:
    return CaptureRef(snapshot_id='before', manifest_sha256=_SHA_A)


def _after() -> CaptureRef:
    return CaptureRef(snapshot_id='after', manifest_sha256=_SHA_B, parent_snapshot_id='before')


def _action() -> ActionSpec:
    ref = RegionRef(
        snapshot_id='before',
        artifact_sha256=_SHA_A,
        modality=EvidenceKind.AX_TREE,
        locator='ax:button/open',
    )
    return ActionSpec(
        kind=ActionKind.CLICK,
        effect=EffectClass.REVERSIBLE_UI,
        target=ElementRef(snapshot_id='before', evidence=(ref,), semantic_role='button'),
    )


class FakeSession:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.active = _before()
        self.dispatch_result = DispatchEvidence(status=DispatchStatus.DISPATCHED, adapter_code='click')
        self.settlement = SettlementResult(
            SettlementStatus.SETTLED,
            (SettlementObservation(signal=SettlementSignal.DOM_QUIET, supported=True, satisfied=True),),
        )
        self.after = _after()
        self.dispatch_error: Exception | None = None
        self.settle_error: BaseException | None = None
        self.capture_error: Exception | None = None
        self.observer_active = False
        self.observer_cleanup_count = 0

    async def active_capture(self) -> CaptureRef:
        self.calls.append('active')
        return self.active

    async def arm_observers(self, action: ActionSpec, target: object | None) -> None:
        self.observer_active = True

    async def dispatch(self, action: ActionSpec, target: object | None) -> DispatchEvidence:
        self.calls.append('dispatch')
        assert action == _action()
        assert target == 'button-handle'
        if self.dispatch_error:
            raise self.dispatch_error
        return self.dispatch_result

    async def settle(self, action: ActionSpec, dispatch: DispatchEvidence) -> SettlementResult:
        self.calls.append('settle')
        if self.settle_error is not None:
            raise self.settle_error
        return self.settlement

    async def cleanup_observers(self) -> None:
        self.observer_active = False
        self.observer_cleanup_count += 1

    async def capture_after(self, *, parent_snapshot_id: str) -> CaptureRef:
        self.calls.append('capture')
        assert parent_snapshot_id == 'before'
        if self.capture_error:
            raise self.capture_error
        return self.after


class FakeResolver:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.result = ResolvedTarget(
            evidence=ResolutionEvidence(status=ResolutionStatus.UNIQUE, candidate_count=1),
            handle='button-handle',
        )

    async def resolve(self, session, before, target) -> ResolvedTarget:
        self.calls.append('resolve')
        return self.result


class FakePolicy:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.result = PolicyEvidence(
            status=PolicyStatus.ALLOWED,
            policy_version='policy-v1',
            rule_id='reversible-click',
        )

    async def decide(self, before, action, resolution) -> PolicyEvidence:
        self.calls.append('policy')
        return self.result


class FakeVerifier:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.results = (AssertionResult(assertion_id='coherent-after', status=AssertionStatus.PASSED),)

    async def verify(self, before, action, after, settlement):
        self.calls.append('verify')
        return self.results


def _clock():
    values = iter(
        (
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=10),
        )
    )
    return lambda: next(values)


def _runtime(calls: list[str]):
    session = FakeSession(calls)
    resolver = FakeResolver(calls)
    policy = FakePolicy(calls)
    verifier = FakeVerifier(calls)
    runtime = ActionRuntime(
        session=session,
        resolver=resolver,
        policy=policy,
        verifier=verifier,
        redaction_version='redaction-v1',
        clock=_clock(),
    )
    return runtime, session, resolver, policy, verifier


@pytest.mark.asyncio
async def test_foreign_target_is_rejected_before_any_runtime_boundary() -> None:
    calls: list[str] = []
    runtime, *_ = _runtime(calls)
    ref = RegionRef(
        snapshot_id='foreign',
        artifact_sha256=_SHA_A,
        modality=EvidenceKind.AX_TREE,
        locator='ax:button/open',
    )
    action = ActionSpec(
        kind=ActionKind.CLICK,
        effect=EffectClass.REVERSIBLE_UI,
        target=ElementRef(snapshot_id='foreign', evidence=(ref,), semantic_role='button'),
    )

    with pytest.raises(ValueError, match='before capture'):
        await runtime.perform(before=_before(), action=action)

    assert calls == []


@pytest.mark.asyncio
async def test_success_calls_each_boundary_once_in_order() -> None:
    calls: list[str] = []
    runtime, *_ = _runtime(calls)
    receipt = await runtime.perform(before=_before(), action=_action())
    assert receipt.outcome is OutcomeStatus.SUCCESS
    assert receipt.after == _after()
    assert calls == ['active', 'resolve', 'policy', 'dispatch', 'settle', 'capture', 'verify']


@pytest.mark.asyncio
async def test_stale_capture_never_resolves_or_dispatches() -> None:
    calls: list[str] = []
    runtime, session, *_ = _runtime(calls)
    session.active = CaptureRef(snapshot_id='other', manifest_sha256=_SHA_B)
    receipt = await runtime.perform(before=_before(), action=_action())
    assert receipt.outcome is OutcomeStatus.STALE
    assert receipt.error_code is ActionErrorCode.STALE_BEFORE_CAPTURE
    assert calls == ['active']


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('resolution', 'outcome'),
    [
        (ResolutionEvidence(status=ResolutionStatus.NOT_FOUND, candidate_count=0), OutcomeStatus.NOT_FOUND),
        (ResolutionEvidence(status=ResolutionStatus.AMBIGUOUS, candidate_count=2), OutcomeStatus.AMBIGUOUS),
        (ResolutionEvidence(status=ResolutionStatus.UNSUPPORTED, candidate_count=0), OutcomeStatus.UNSUPPORTED),
    ],
)
async def test_non_unique_resolution_never_reaches_policy_or_dispatch(resolution, outcome) -> None:
    calls: list[str] = []
    runtime, _, resolver, *_ = _runtime(calls)
    resolver.result = ResolvedTarget(evidence=resolution)
    receipt = await runtime.perform(before=_before(), action=_action())
    assert receipt.outcome is outcome
    assert calls == ['active', 'resolve']


@pytest.mark.asyncio
async def test_policy_block_never_dispatches() -> None:
    calls: list[str] = []
    runtime, _, _, policy, _ = _runtime(calls)
    policy.result = PolicyEvidence(
        status=PolicyStatus.BLOCKED,
        policy_version='policy-v1',
        rule_id='deny-unknown-click',
        reason_code='unknown-effect',
    )
    receipt = await runtime.perform(before=_before(), action=_action())
    assert receipt.outcome is OutcomeStatus.BLOCKED
    assert calls == ['active', 'resolve', 'policy']


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('settlement_status', 'expected_outcome', 'expected_error'),
    [
        (SettlementStatus.TIMED_OUT, OutcomeStatus.TIMED_OUT, ActionErrorCode.SETTLEMENT_TIMEOUT),
        (SettlementStatus.INCONCLUSIVE, OutcomeStatus.INCONCLUSIVE, ActionErrorCode.SETTLEMENT_INCONCLUSIVE),
    ],
)
@pytest.mark.parametrize('assertion_status', list(AssertionStatus))
async def test_unsettled_capture_runs_verifier_and_preserves_assertions(
    settlement_status, expected_outcome, expected_error, assertion_status
) -> None:
    calls: list[str] = []
    runtime, session, _, _, verifier = _runtime(calls)
    session.settlement = SettlementResult(
        settlement_status,
        (SettlementObservation(signal=SettlementSignal.DOM_QUIET, supported=True, satisfied=False),),
    )
    verifier.results = (AssertionResult(assertion_id='postcondition', status=assertion_status),)

    receipt = await runtime.perform(before=_before(), action=_action())

    assert receipt.outcome is expected_outcome
    assert receipt.error_code is expected_error
    assert receipt.assertions == verifier.results
    assert receipt.after == _after()
    assert calls == ['active', 'resolve', 'policy', 'dispatch', 'settle', 'capture', 'verify']


@pytest.mark.asyncio
async def test_unsettled_missing_assertions_are_retained_as_unsupported() -> None:
    calls: list[str] = []
    runtime, session, _, _, verifier = _runtime(calls)
    session.settlement = SettlementResult(
        SettlementStatus.INCONCLUSIVE,
        (SettlementObservation(signal=SettlementSignal.DOM_QUIET, supported=True, satisfied=False),),
    )
    verifier.results = ()

    receipt = await runtime.perform(before=_before(), action=_action())

    assert receipt.outcome is OutcomeStatus.INCONCLUSIVE
    assert receipt.error_code is ActionErrorCode.SETTLEMENT_INCONCLUSIVE
    assert receipt.assertions == (
        AssertionResult(
            assertion_id='postcondition',
            status=AssertionStatus.UNSUPPORTED,
            reason_code='missing_evidence',
        ),
    )
    assert calls == ['active', 'resolve', 'policy', 'dispatch', 'settle', 'capture', 'verify']


@pytest.mark.asyncio
async def test_unsettled_capture_failure_has_no_assertions_or_verifier_call() -> None:
    calls: list[str] = []
    runtime, session, *_ = _runtime(calls)
    session.settlement = SettlementResult(
        SettlementStatus.TIMED_OUT,
        (SettlementObservation(signal=SettlementSignal.DOM_QUIET, supported=True, satisfied=False),),
    )
    session.capture_error = ActionBoundaryError(ActionErrorCode.AFTER_CAPTURE_FAILED)

    receipt = await runtime.perform(before=_before(), action=_action())

    assert receipt.outcome is OutcomeStatus.TIMED_OUT
    assert receipt.error_code is ActionErrorCode.SETTLEMENT_TIMEOUT
    assert receipt.after is None
    assert receipt.assertions == ()
    assert calls == ['active', 'resolve', 'policy', 'dispatch', 'settle', 'capture']


@pytest.mark.asyncio
async def test_expected_adapter_error_is_sanitized_but_programming_error_propagates() -> None:
    calls: list[str] = []
    runtime, session, *_ = _runtime(calls)
    session.dispatch_error = ActionBoundaryError(ActionErrorCode.DISPATCH_FAILED)
    receipt = await runtime.perform(before=_before(), action=_action())
    assert receipt.error_code is ActionErrorCode.DISPATCH_FAILED
    assert receipt.dispatch.status is DispatchStatus.FAILED
    assert 'secret' not in receipt.model_dump_json()

    calls.clear()
    runtime, session, *_ = _runtime(calls)
    session.dispatch_error = RuntimeError('programming defect containing secret')
    with pytest.raises(RuntimeError, match='programming defect'):
        await runtime.perform(before=_before(), action=_action())


@pytest.mark.asyncio
async def test_cancelled_settlement_still_cleans_up_armed_observers() -> None:
    calls: list[str] = []
    runtime, session, *_ = _runtime(calls)
    session.settle_error = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await runtime.perform(before=_before(), action=_action())

    assert not session.observer_active
    assert session.observer_cleanup_count == 1


@pytest.mark.asyncio
async def test_assertion_failure_and_inconclusive_are_not_success() -> None:
    calls: list[str] = []
    runtime, _, _, _, verifier = _runtime(calls)
    verifier.results = (AssertionResult(assertion_id='state-change', status=AssertionStatus.FAILED),)
    failed = await runtime.perform(before=_before(), action=_action())
    assert failed.outcome is OutcomeStatus.FAILED
    assert failed.error_code is ActionErrorCode.ASSERTION_FAILED

    calls.clear()
    runtime, _, _, _, verifier = _runtime(calls)
    verifier.results = (AssertionResult(assertion_id='network-change', status=AssertionStatus.UNSUPPORTED),)
    inconclusive = await runtime.perform(before=_before(), action=_action())
    assert inconclusive.outcome is OutcomeStatus.INCONCLUSIVE
    assert inconclusive.error_code is ActionErrorCode.ASSERTION_INCONCLUSIVE

    calls.clear()
    runtime, _, _, _, verifier = _runtime(calls)
    verifier.results = ()
    missing = await runtime.perform(before=_before(), action=_action())
    assert missing.outcome is OutcomeStatus.INCONCLUSIVE
    assert missing.error_code is ActionErrorCode.ASSERTION_INCONCLUSIVE
