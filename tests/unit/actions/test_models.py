from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

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
    FreshnessStatus,
    NetworkResponseEvidence,
    OutcomeStatus,
    PolicyEvidence,
    PolicyStatus,
    ReceiptTiming,
    ResolutionEvidence,
    ResolutionStatus,
    ResponseBodyState,
    ResponseExpectationSpec,
    ScrollDirection,
    ScrollExtent,
    ScrollSpec,
    SettlementObservation,
    SettlementSignal,
    SettlementStatus,
    TransitionReceipt,
)
from yosoi.observations.models.artifact import EvidenceKind
from yosoi.observations.models.view import RegionRef

_SHA_A = 'a' * 64
_SHA_B = 'b' * 64


def _region(snapshot_id: str = 'before') -> RegionRef:
    return RegionRef(
        snapshot_id=snapshot_id,
        artifact_sha256=_SHA_A,
        modality=EvidenceKind.RENDERED_DOM,
        locator='//*[@id="open"]',
    )


def _before() -> CaptureRef:
    return CaptureRef(snapshot_id='before', manifest_sha256=_SHA_A)


def _after() -> CaptureRef:
    return CaptureRef(snapshot_id='after', manifest_sha256=_SHA_B, parent_snapshot_id='before')


def _target() -> ElementRef:
    return ElementRef(snapshot_id='before', evidence=(_region(),), semantic_role='button')


def _timing(offset: int = 0) -> ReceiptTiming:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=offset)
    return ReceiptTiming(started_at=start, finished_at=start + timedelta(milliseconds=10))


def _allowed() -> PolicyEvidence:
    return PolicyEvidence(status=PolicyStatus.ALLOWED, policy_version='policy-v1', rule_id='reversible-click')


def _success(**updates) -> TransitionReceipt:
    values = {
        'before': _before(),
        'action': ActionSpec(kind=ActionKind.CLICK, effect=EffectClass.REVERSIBLE_UI, target=_target()),
        'freshness': FreshnessStatus.FRESH,
        'resolution': ResolutionEvidence(status=ResolutionStatus.UNIQUE, candidate_count=1),
        'policy': _allowed(),
        'dispatch': DispatchEvidence(status=DispatchStatus.DISPATCHED, adapter_code='click'),
        'settlement': SettlementStatus.SETTLED,
        'settlement_observations': (
            SettlementObservation(signal=SettlementSignal.DOM_QUIET, supported=True, satisfied=True),
        ),
        'assertions': (AssertionResult(assertion_id='coherent-after', status=AssertionStatus.PASSED),),
        'after': _after(),
        'outcome': OutcomeStatus.SUCCESS,
        'redaction_version': 'redaction-v1',
        'timing': _timing(),
    }
    values.update(updates)
    return TransitionReceipt(**values)


def test_first_slice_action_shapes_are_closed_and_explicit() -> None:
    assert ActionSpec(kind=ActionKind.NAVIGATE, effect=EffectClass.OBSERVATION, url='https://example.test/a')
    assert ActionSpec(kind=ActionKind.CLICK, effect=EffectClass.REVERSIBLE_UI, target=_target())
    assert ActionSpec(kind=ActionKind.BACK, effect=EffectClass.OBSERVATION)
    assert ActionSpec(kind=ActionKind.FORWARD, effect=EffectClass.OBSERVATION)
    assert ActionSpec(
        kind=ActionKind.SCROLL,
        effect=EffectClass.REVERSIBLE_UI,
        scroll=ScrollSpec(direction=ScrollDirection.DOWN, extent=ScrollExtent.PAGE),
    )
    assert ActionSpec(
        kind=ActionKind.SCROLL,
        effect=EffectClass.REVERSIBLE_UI,
        target=_target(),
        scroll=ScrollSpec(direction=ScrollDirection.DOWN, extent=ScrollExtent.TARGET),
    )
    with pytest.raises(ValidationError):
        ActionSpec(kind=ActionKind.CLICK, effect=EffectClass.REVERSIBLE_UI)
    with pytest.raises(ValidationError):
        ActionSpec(kind=ActionKind.BACK, effect=EffectClass.OBSERVATION, target=_target())


@pytest.mark.parametrize(
    'url',
    [
        'javascript:alert(1)',
        'data:text/html,hello',
        'file:///etc/passwd',
        'https://user:password@example.test/',
        'https://example.test/?access_token=visible',
        'https://example.test/?session_id=visible',
        'https://example.test/#access_token=visible',
        'https://example.test\\\\@evil.test/',
    ],
)
def test_navigation_rejects_non_http_and_secret_bearing_urls(url: str) -> None:
    with pytest.raises(ValidationError):
        ActionSpec(kind=ActionKind.NAVIGATE, effect=EffectClass.OBSERVATION, url=url)


def test_target_is_bound_to_exact_observation_evidence() -> None:
    with pytest.raises(ValidationError, match='target evidence'):
        ElementRef(snapshot_id='before', evidence=(_region('foreign'),))
    with pytest.raises(ValidationError, match='foreign capture'):
        _success(
            action=ActionSpec(
                kind=ActionKind.CLICK,
                effect=EffectClass.REVERSIBLE_UI,
                target=ElementRef(snapshot_id='foreign', evidence=(_region('foreign'),)),
            )
        )


def test_success_requires_dispatch_settlement_and_distinct_child_capture() -> None:
    receipt = _success()
    assert receipt.fingerprint == _success(timing=_timing(60)).fingerprint
    assert TransitionReceipt.model_validate_json(receipt.model_dump_json()) == receipt
    with pytest.raises(ValidationError, match='settlement'):
        _success(settlement_observations=())
    with pytest.raises(ValidationError, match='distinct child'):
        _success(after=CaptureRef(snapshot_id='before', manifest_sha256=_SHA_B))
    with pytest.raises(ValidationError, match='policy approval'):
        _success(policy=PolicyEvidence(status=PolicyStatus.BLOCKED, policy_version='v1', rule_id='deny'))
    with pytest.raises(ValidationError, match='at least one passing assertion'):
        _success(assertions=())


@pytest.mark.parametrize(
    ('outcome', 'error', 'freshness', 'resolution', 'policy', 'settlement'),
    [
        (
            OutcomeStatus.STALE,
            ActionErrorCode.STALE_BEFORE_CAPTURE,
            FreshnessStatus.STALE,
            ResolutionStatus.NOT_EVALUATED,
            PolicyStatus.NOT_EVALUATED,
            SettlementStatus.NOT_OBSERVED,
        ),
        (
            OutcomeStatus.AMBIGUOUS,
            ActionErrorCode.TARGET_AMBIGUOUS,
            FreshnessStatus.FRESH,
            ResolutionStatus.AMBIGUOUS,
            PolicyStatus.NOT_EVALUATED,
            SettlementStatus.NOT_OBSERVED,
        ),
        (
            OutcomeStatus.BLOCKED,
            ActionErrorCode.POLICY_BLOCKED,
            FreshnessStatus.FRESH,
            ResolutionStatus.UNIQUE,
            PolicyStatus.BLOCKED,
            SettlementStatus.NOT_OBSERVED,
        ),
    ],
)
def test_pre_dispatch_terminal_receipts_cannot_claim_dispatch(
    outcome,
    error,
    freshness,
    resolution,
    policy,
    settlement,
) -> None:
    candidate_count = (
        2 if resolution is ResolutionStatus.AMBIGUOUS else 1 if resolution is ResolutionStatus.UNIQUE else 0
    )
    receipt = TransitionReceipt(
        before=_before(),
        action=ActionSpec(kind=ActionKind.CLICK, effect=EffectClass.REVERSIBLE_UI, target=_target()),
        freshness=freshness,
        resolution=ResolutionEvidence(status=resolution, candidate_count=candidate_count),
        policy=PolicyEvidence(status=policy, policy_version='v1', rule_id='gate'),
        dispatch=DispatchEvidence(status=DispatchStatus.NOT_ATTEMPTED),
        settlement=settlement,
        outcome=outcome,
        error_code=error,
        redaction_version='v1',
        timing=_timing(),
    )
    assert receipt.after is None
    with pytest.raises(ValidationError, match='cannot contain dispatch'):
        TransitionReceipt.model_validate(
            {**receipt.model_dump(), 'dispatch': DispatchEvidence(status=DispatchStatus.DISPATCHED)}
        )


def test_policy_unsupported_error_is_explicit_and_status_bound() -> None:
    policy = PolicyEvidence(
        status=PolicyStatus.UNSUPPORTED,
        policy_version='v1',
        rule_id='capability',
        unsupported_error=ActionErrorCode.UNSUPPORTED_ACTION,
    )
    assert policy.unsupported_error is ActionErrorCode.UNSUPPORTED_ACTION

    with pytest.raises(ValidationError, match='matching unsupported status'):
        PolicyEvidence(
            status=PolicyStatus.ALLOWED,
            policy_version='v1',
            rule_id='allow',
            unsupported_error=ActionErrorCode.UNSUPPORTED_ACTION,
        )


def test_settlement_vectors_are_unique_and_follow_dispatch_lineage() -> None:
    duplicate = SettlementObservation(signal=SettlementSignal.DOM_QUIET, supported=True, satisfied=True)
    with pytest.raises(ValidationError, match='cannot repeat'):
        _success(settlement_observations=(duplicate, duplicate))

    with pytest.raises(ValidationError, match='undispatched'):
        _success(
            outcome=OutcomeStatus.TIMED_OUT,
            error_code=ActionErrorCode.SETTLEMENT_TIMEOUT,
            settlement=SettlementStatus.TIMED_OUT,
            settlement_observations=(duplicate,),
            dispatch=DispatchEvidence(status=DispatchStatus.NOT_ATTEMPTED),
            after=None,
            assertions=(),
        )


def test_assertion_evidence_must_belong_to_after_capture() -> None:
    foreign = _region('foreign')
    with pytest.raises(ValidationError, match='after capture'):
        _success(
            assertions=(AssertionResult(assertion_id='check', status=AssertionStatus.PASSED, evidence=(foreign,)),)
        )


def test_models_have_no_arbitrary_payload_or_unsafe_effect_channel() -> None:
    with pytest.raises(ValidationError):
        ActionSpec.model_validate(
            {
                'kind': 'click',
                'effect': 'destructive',
                'target': _target().model_dump(),
                'script': 'fetch("/delete")',
                'value': 'secret',
                'x': 10,
                'y': 20,
            }
        )


def _response_expectation() -> ResponseExpectationSpec:
    return ResponseExpectationSpec(pattern_id='ajaxdata', pattern='**/ajaxdata')


def _response_evidence(pattern_id: str = 'ajaxdata') -> NetworkResponseEvidence:
    return NetworkResponseEvidence(
        pattern_id=pattern_id,
        request_url_sha256=_SHA_A,
        origin_sha256=_SHA_B,
        path='/ajaxdata',
        status=200,
        resource_type='xhr',
        mime_type='text/html',
        body_state=ResponseBodyState.AVAILABLE,
        from_cache=False,
        from_service_worker=False,
        truncated=False,
    )


def test_response_expectation_is_bounded_and_secret_safe() -> None:
    assert _response_expectation().max_total_bytes == 8_388_608
    for pattern in ('**/ajaxdata?private=value', '**/secret/path', 'https://user@example.test/data'):
        with pytest.raises(ValidationError):
            ResponseExpectationSpec(pattern_id='ajaxdata', pattern=pattern)
    with pytest.raises(ValidationError):
        ResponseExpectationSpec(
            pattern_id='ajaxdata',
            pattern='**/ajaxdata',
            max_response_bytes=1024,
            max_total_bytes=512,
        )


def test_success_with_declared_response_requires_matching_sanitized_evidence() -> None:
    action = ActionSpec(
        kind=ActionKind.CLICK,
        effect=EffectClass.REVERSIBLE_UI,
        target=_target(),
        response_expectation=_response_expectation(),
    )
    observation = SettlementObservation(
        signal=SettlementSignal.RELEVANT_RESPONSE_OBSERVED,
        supported=True,
        satisfied=True,
        responses=(_response_evidence(),),
    )
    receipt = _success(action=action, settlement_observations=(observation,))
    assert receipt.settlement_observations[0].responses[0].path == '/ajaxdata'
    serialized = receipt.model_dump_json()
    assert 'headers' not in serialized
    assert 'body_bytes' not in serialized

    with pytest.raises(ValidationError):
        _success(action=action)
    with pytest.raises(ValidationError):
        _success(
            action=action,
            settlement_observations=(
                observation.model_copy(update={'responses': (_response_evidence('foreign-pattern'),)}),
            ),
        )


def test_response_evidence_cannot_exist_without_declared_expectation() -> None:
    observation = SettlementObservation(
        signal=SettlementSignal.RELEVANT_RESPONSE_OBSERVED,
        supported=True,
        satisfied=True,
        responses=(_response_evidence(),),
    )
    with pytest.raises(ValidationError):
        _success(settlement_observations=(observation,))
