"""Immutable contracts for one policy-gated browser transition."""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from yosoi.observations.models.view import RegionRef

ACTION_SCHEMA_VERSION = 'action1'
_SAFE_CODE = r'^[a-z][a-z0-9_.-]{0,127}$'
_SHA256 = r'^[0-9a-f]{64}$'
_SENSITIVE_QUERY_KEYS = frozenset(
    {
        'access_token',
        'api_key',
        'apikey',
        'authorization',
        'auth',
        'code',
        'cookie',
        'credential',
        'key',
        'password',
        'secret',
        'session',
        'session_id',
        'token',
    }
)


class _ValueObject(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid', strict=True)


class ActionKind(str, Enum):
    """Closed first-slice action vocabulary."""

    NAVIGATE = 'navigate'
    CLICK = 'click'
    BACK = 'back'
    FORWARD = 'forward'
    SCROLL = 'scroll'


class EffectClass(str, Enum):
    """Effects permitted by the unauthenticated CAS-270 slice."""

    OBSERVATION = 'observation'
    REVERSIBLE_UI = 'reversible_ui'


class ScrollDirection(str, Enum):
    """Semantic scroll direction without pointer coordinates."""

    UP = 'up'
    DOWN = 'down'
    LEFT = 'left'
    RIGHT = 'right'


class ScrollExtent(str, Enum):
    """Bounded destination for a scroll action."""

    VIEWPORT = 'viewport'
    PAGE = 'page'
    END = 'end'
    TARGET = 'target'


class FreshnessStatus(str, Enum):
    """Relationship between requested and active browser epochs."""

    FRESH = 'fresh'
    STALE = 'stale'
    UNKNOWN = 'unknown'


class ResolutionStatus(str, Enum):
    """Outcome of resolving an evidence-backed target."""

    NOT_EVALUATED = 'not_evaluated'
    NOT_REQUIRED = 'not_required'
    UNIQUE = 'unique'
    NOT_FOUND = 'not_found'
    AMBIGUOUS = 'ambiguous'
    UNSUPPORTED = 'unsupported'


class PolicyStatus(str, Enum):
    """Action policy gate outcome."""

    NOT_EVALUATED = 'not_evaluated'
    ALLOWED = 'allowed'
    BLOCKED = 'blocked'
    UNSUPPORTED = 'unsupported'


class DispatchStatus(str, Enum):
    """Whether exactly one action reached the browser adapter."""

    NOT_ATTEMPTED = 'not_attempted'
    DISPATCHED = 'dispatched'
    FAILED = 'failed'


class SettlementStatus(str, Enum):
    """Evidence-based post-dispatch settlement verdict."""

    NOT_OBSERVED = 'not_observed'
    SETTLED = 'settled'
    INCONCLUSIVE = 'inconclusive'
    TIMED_OUT = 'timed_out'


class OutcomeStatus(str, Enum):
    """Normalized terminal outcome for one attempted transition."""

    SUCCESS = 'success'
    BLOCKED = 'blocked'
    STALE = 'stale'
    AMBIGUOUS = 'ambiguous'
    UNSUPPORTED = 'unsupported'
    NOT_FOUND = 'not_found'
    TIMED_OUT = 'timed_out'
    INCONCLUSIVE = 'inconclusive'
    FAILED = 'failed'


class AssertionStatus(str, Enum):
    """Four-state deterministic assertion result."""

    PASSED = 'passed'
    FAILED = 'failed'
    UNSUPPORTED = 'unsupported'
    INCONCLUSIVE = 'inconclusive'


class SettlementSignal(str, Enum):
    """Independent signals composing a settlement vector."""

    URL_OR_HISTORY_CHANGED = 'url_or_history_changed'
    DOCUMENT_EPOCH_CHANGED = 'document_epoch_changed'
    POSTCONDITION_SATISFIED = 'postcondition_satisfied'
    DOM_QUIET = 'dom_quiet'
    RELEVANT_NETWORK_IDLE = 'relevant_network_idle'
    RELEVANT_RESPONSE_OBSERVED = 'relevant_response_observed'
    VISUAL_STABLE = 'visual_stable'
    CONSOLE_QUIET = 'console_quiet'
    APPLICATION_SIGNAL = 'application_signal'


class ResponseBodyState(str, Enum):
    """Bounded response-body availability without retaining body bytes."""

    AVAILABLE = 'available'
    TRUNCATED = 'truncated'
    UNAVAILABLE = 'unavailable'


class ActionErrorCode(str, Enum):
    """Secret-safe error taxonomy stored instead of raw exceptions."""

    STALE_BEFORE_CAPTURE = 'stale_before_capture'
    UNSUPPORTED_ACTION = 'unsupported_action'
    UNSUPPORTED_EFFECT = 'unsupported_effect'
    TARGET_NOT_FOUND = 'target_not_found'
    TARGET_AMBIGUOUS = 'target_ambiguous'
    POLICY_BLOCKED = 'policy_blocked'
    DISPATCH_FAILED = 'dispatch_failed'
    SETTLEMENT_TIMEOUT = 'settlement_timeout'
    SETTLEMENT_INCONCLUSIVE = 'settlement_inconclusive'
    AFTER_CAPTURE_FAILED = 'after_capture_failed'
    INTEGRITY_FAILED = 'integrity_failed'
    ASSERTION_FAILED = 'assertion_failed'
    ASSERTION_INCONCLUSIVE = 'assertion_inconclusive'
    ADAPTER_ERROR = 'adapter_error'


class CaptureRef(_ValueObject):
    """Content-addressed reference to one exact observation manifest."""

    snapshot_id: str = Field(min_length=1, max_length=256)
    manifest_sha256: str = Field(pattern=_SHA256)
    parent_snapshot_id: str | None = Field(default=None, min_length=1, max_length=256)

    @model_validator(mode='after')
    def _not_own_parent(self) -> CaptureRef:
        if self.parent_snapshot_id == self.snapshot_id:
            raise ValueError('a capture cannot be its own parent')
        return self


class ElementRef(_ValueObject):
    """Action target derived from exact evidence exposed in one capture."""

    snapshot_id: str = Field(min_length=1, max_length=256)
    evidence: tuple[RegionRef, ...] = Field(min_length=1, max_length=8)
    semantic_role: str | None = Field(default=None, pattern=r'^[a-z][a-z0-9_-]{0,63}$')
    accessible_name_hash: str | None = Field(default=None, pattern=_SHA256)
    selector_hints: tuple[str, ...] = Field(default=(), max_length=8)

    @model_validator(mode='after')
    def _bind_evidence(self) -> ElementRef:
        if any(ref.snapshot_id != self.snapshot_id for ref in self.evidence):
            raise ValueError('target evidence must belong to the target snapshot')
        if any(not hint.strip() or len(hint) > 512 for hint in self.selector_hints):
            raise ValueError('selector hints must be non-empty and at most 512 characters')
        forbidden = ('authorization', 'cookie', 'password', 'secret', 'token', 'value=')
        if any(any(term in hint.casefold() for term in forbidden) for hint in self.selector_hints):
            raise ValueError('selector hints cannot carry secret-bearing values or auth targets')
        return self


class ScrollSpec(_ValueObject):
    """Coordinate-free scroll request."""

    direction: ScrollDirection
    extent: ScrollExtent


class ResponseExpectationSpec(_ValueObject):
    """Bounded passive response expected as evidence of this action."""

    pattern_id: str = Field(pattern=_SAFE_CODE)
    pattern: str = Field(min_length=1, max_length=2048)
    timeout: float = Field(default=30.0, gt=0, le=120)
    max_response_bytes: int = Field(default=2_097_152, gt=0, le=8_388_608)
    max_total_bytes: int = Field(default=8_388_608, gt=0, le=33_554_432)

    @model_validator(mode='after')
    def _safe_pattern(self) -> ResponseExpectationSpec:
        if any(char.isspace() or ord(char) < 0x20 for char in self.pattern):
            raise ValueError('response pattern cannot contain whitespace or control characters')
        if any(char in self.pattern for char in ('?', '#', '@', '\\')):
            raise ValueError('response pattern cannot contain query, fragment, credentials, or backslashes')
        if self.max_response_bytes > self.max_total_bytes:
            raise ValueError('per-response byte limit cannot exceed total byte limit')
        forbidden = ('authorization', 'cookie', 'password', 'secret', 'token')
        if any(term in self.pattern.casefold() for term in forbidden):
            raise ValueError('response pattern cannot carry secret-bearing targets')
        return self


class ActionSpec(_ValueObject):
    """Serializable action intent with no arbitrary payload channel."""

    kind: ActionKind
    effect: EffectClass
    target: ElementRef | None = None
    url: str | None = Field(default=None, max_length=4096)
    scroll: ScrollSpec | None = None
    response_expectation: ResponseExpectationSpec | None = None

    @model_validator(mode='after')
    def _validate_shape(self) -> ActionSpec:
        if self.kind is ActionKind.NAVIGATE:
            self._validate_url()
            if self.target is not None or self.scroll is not None:
                raise ValueError('navigate accepts only a policy-safe URL and passive response expectation')
        elif self.kind is ActionKind.CLICK:
            if self.target is None:
                raise ValueError('click requires an evidence-backed target')
            if self.url is not None or self.scroll is not None:
                raise ValueError('click accepts only an evidence-backed target and passive response expectation')
        elif self.kind is ActionKind.SCROLL:
            if self.response_expectation is not None:
                raise ValueError('scroll cannot arm a response expectation')
            if self.scroll is None or self.url is not None:
                raise ValueError('scroll requires a semantic scroll specification')
            if (self.scroll.extent is ScrollExtent.TARGET) != (self.target is not None):
                raise ValueError('target scrolls require a target and viewport scrolls forbid one')
        elif (
            self.target is not None
            or self.url is not None
            or self.scroll is not None
            or self.response_expectation is not None
        ):
            raise ValueError('back and forward accept no payload')
        return self

    def _validate_url(self) -> None:
        if self.url is None:
            raise ValueError('navigate requires a URL')
        if any(char.isspace() or ord(char) < 0x20 or ord(char) == 0x7F for char in self.url):
            raise ValueError('navigate URLs cannot contain whitespace or control characters')
        parts = urlsplit(self.url)
        if parts.scheme not in {'http', 'https'} or not parts.netloc:
            raise ValueError('navigate supports only absolute HTTP(S) URLs')
        if parts.username or parts.password or '\\\\' in parts.netloc:
            raise ValueError('navigate URLs cannot contain credentials or backslashes')
        query_pairs = parse_qsl(parts.query, keep_blank_values=True)
        fragment_pairs = parse_qsl(parts.fragment, keep_blank_values=True)
        if any(key.casefold() in _SENSITIVE_QUERY_KEYS for key, _ in (*query_pairs, *fragment_pairs)):
            raise ValueError('navigate URLs cannot contain secret-bearing query or fragment keys')


class ResolutionEvidence(_ValueObject):
    """Serializable target-resolution evidence without an opaque handle."""

    status: ResolutionStatus
    candidate_count: int = Field(ge=0)
    reason_code: str | None = Field(default=None, pattern=_SAFE_CODE)

    @model_validator(mode='after')
    def _coherent_count(self) -> ResolutionEvidence:
        expected = {
            ResolutionStatus.NOT_EVALUATED: 0,
            ResolutionStatus.NOT_REQUIRED: 0,
            ResolutionStatus.UNIQUE: 1,
            ResolutionStatus.NOT_FOUND: 0,
        }
        if self.status in expected and self.candidate_count != expected[self.status]:
            raise ValueError(f'{self.status.value} resolution requires {expected[self.status]} candidates')
        if self.status is ResolutionStatus.AMBIGUOUS and self.candidate_count < 2:
            raise ValueError('ambiguous resolution requires at least two candidates')
        return self


class PolicyEvidence(_ValueObject):
    """Versioned, normalized action-policy decision."""

    status: PolicyStatus
    policy_version: str = Field(pattern=_SAFE_CODE)
    rule_id: str = Field(pattern=_SAFE_CODE)
    reason_code: str | None = Field(default=None, pattern=_SAFE_CODE)
    unsupported_error: ActionErrorCode | None = None

    @model_validator(mode='after')
    def _unsupported_error_matches_status(self) -> PolicyEvidence:
        allowed = {ActionErrorCode.UNSUPPORTED_ACTION, ActionErrorCode.UNSUPPORTED_EFFECT}
        if self.unsupported_error is not None and (
            self.status is not PolicyStatus.UNSUPPORTED or self.unsupported_error not in allowed
        ):
            raise ValueError('policy unsupported_error requires a matching unsupported status')
        return self


class DispatchEvidence(_ValueObject):
    """Model-safe evidence that the adapter accepted or refused dispatch."""

    status: DispatchStatus
    adapter_code: str | None = Field(default=None, pattern=_SAFE_CODE)


class AssertionResult(_ValueObject):
    """Deterministic assertion outcome linked to optional exact evidence."""

    assertion_id: str = Field(pattern=_SAFE_CODE)
    status: AssertionStatus
    evidence: tuple[RegionRef, ...] = Field(default=(), max_length=16)
    reason_code: str | None = Field(default=None, pattern=_SAFE_CODE)


class NetworkResponseEvidence(_ValueObject):
    """Sanitized metadata proving one bounded response completed on the retained tab.

    URLs are represented by origin/full-URL digests plus a query-free path. Headers and body
    bytes are intentionally absent, so receipts cannot retain cookies, tokens, or response data.
    """

    pattern_id: str = Field(pattern=_SAFE_CODE)
    request_url_sha256: str = Field(pattern=_SHA256)
    origin_sha256: str = Field(pattern=_SHA256)
    path: str = Field(min_length=1, max_length=2048, pattern=r'^/[^?#\x00-\x20]*$')
    status: int = Field(ge=100, le=599)
    resource_type: str = Field(pattern=_SAFE_CODE)
    mime_type: str = Field(min_length=1, max_length=255, pattern=r'^[^\x00-\x20;]+/[^\x00-\x20;]+(?:;[^\x00-\x1f]*)?$')
    body_state: ResponseBodyState
    from_cache: bool
    from_service_worker: bool
    truncated: bool

    @model_validator(mode='after')
    def _coherent_body_state(self) -> NetworkResponseEvidence:
        if self.truncated is not (self.body_state is ResponseBodyState.TRUNCATED):
            raise ValueError('truncated must agree with response body state')
        return self


class SettlementObservation(_ValueObject):
    """One supported or unavailable dimension of settlement."""

    signal: SettlementSignal
    supported: bool
    satisfied: bool
    reason_code: str | None = Field(default=None, pattern=_SAFE_CODE)
    responses: tuple[NetworkResponseEvidence, ...] = Field(default=(), max_length=8)

    @model_validator(mode='after')
    def _coherent_evidence(self) -> SettlementObservation:
        if not self.supported and self.satisfied:
            raise ValueError('an unsupported settlement signal cannot be satisfied')
        if self.responses and self.signal is not SettlementSignal.RELEVANT_RESPONSE_OBSERVED:
            raise ValueError('response evidence belongs only to relevant-response observations')
        if self.responses and (not self.supported or not self.satisfied):
            raise ValueError('response evidence requires a supported, satisfied observation')
        if self.signal is SettlementSignal.RELEVANT_RESPONSE_OBSERVED and self.satisfied != bool(self.responses):
            raise ValueError('relevant-response satisfaction must agree with response evidence')
        return self


class ReceiptTiming(_ValueObject):
    """Volatile audit timing excluded from receipt identity."""

    started_at: AwareDatetime
    finished_at: AwareDatetime

    @model_validator(mode='after')
    def _ordered(self) -> ReceiptTiming:
        if self.finished_at < self.started_at:
            raise ValueError('receipt timing must be ordered')
        return self


class TransitionReceipt(_ValueObject):
    """Immutable source-of-truth record for one attempted transition."""

    schema_version: str = ACTION_SCHEMA_VERSION
    before: CaptureRef
    action: ActionSpec
    freshness: FreshnessStatus
    resolution: ResolutionEvidence
    policy: PolicyEvidence
    dispatch: DispatchEvidence
    settlement: SettlementStatus
    settlement_observations: tuple[SettlementObservation, ...] = ()
    assertions: tuple[AssertionResult, ...] = ()
    after: CaptureRef | None = None
    outcome: OutcomeStatus
    error_code: ActionErrorCode | None = None
    redaction_version: str = Field(pattern=_SAFE_CODE)
    timing: ReceiptTiming

    @model_validator(mode='after')
    def _coherent(self) -> TransitionReceipt:
        self._validate_target()
        self._validate_after()
        if self.outcome is OutcomeStatus.SUCCESS:
            self._validate_success()
        else:
            self._validate_non_success()
        self._validate_lineage()
        return self

    def _validate_lineage(self) -> None:
        signals = [observation.signal for observation in self.settlement_observations]
        if len(signals) != len(set(signals)):
            raise ValueError('settlement observations cannot repeat a signal')
        if self.dispatch.status is not DispatchStatus.DISPATCHED:
            if self.settlement is not SettlementStatus.NOT_OBSERVED:
                raise ValueError('undispatched transitions cannot contain settlement evidence')
            if self.after is not None or self.assertions:
                raise ValueError('undispatched transitions cannot contain post-dispatch evidence')
        elif self.freshness is not FreshnessStatus.FRESH or self.policy.status is not PolicyStatus.ALLOWED:
            raise ValueError('dispatched transitions require fresh policy-approved evidence')
        if self.settlement is SettlementStatus.NOT_OBSERVED and self.settlement_observations:
            raise ValueError('unobserved settlement cannot contain observations')
        response_observations = [
            observation
            for observation in self.settlement_observations
            if observation.signal is SettlementSignal.RELEVANT_RESPONSE_OBSERVED
        ]
        response_evidence = [response for observation in response_observations for response in observation.responses]
        if self.action.response_expectation is None:
            if response_evidence or any(observation.supported for observation in response_observations):
                raise ValueError('response evidence requires a declared action expectation')
        elif any(response.pattern_id != self.action.response_expectation.pattern_id for response in response_evidence):
            raise ValueError('response evidence must match the declared expectation')
        if self.after is not None and self.settlement is SettlementStatus.NOT_OBSERVED:
            raise ValueError('after capture requires an observed settlement state')

    def _validate_target(self) -> None:
        if self.action.target is not None and self.action.target.snapshot_id != self.before.snapshot_id:
            raise ValueError('action target belongs to a foreign capture')

    def _validate_after(self) -> None:
        if self.after is None:
            if any(result.evidence for result in self.assertions):
                raise ValueError('assertion evidence requires an after capture')
            return
        if (
            self.after.snapshot_id == self.before.snapshot_id
            or self.after.parent_snapshot_id != self.before.snapshot_id
        ):
            raise ValueError('after capture must be a distinct child of the source capture')
        if any(ref.snapshot_id != self.after.snapshot_id for result in self.assertions for ref in result.evidence):
            raise ValueError('assertion evidence must belong to the after capture')

    def _validate_success(self) -> None:
        if self.error_code is not None:
            raise ValueError('successful transitions cannot carry an error code')
        if self.freshness is not FreshnessStatus.FRESH:
            raise ValueError('successful transitions require a fresh source capture')
        if self.policy.status is not PolicyStatus.ALLOWED:
            raise ValueError('successful transitions require policy approval')
        if self.dispatch.status is not DispatchStatus.DISPATCHED:
            raise ValueError('successful transitions require dispatch evidence')
        if self.settlement is not SettlementStatus.SETTLED or not self.settlement_observations:
            raise ValueError('successful transitions require observed settlement evidence')
        if self.action.target is not None and self.resolution.status is not ResolutionStatus.UNIQUE:
            raise ValueError('targeted transitions require unique target resolution')
        if self.action.target is None and self.resolution.status is not ResolutionStatus.NOT_REQUIRED:
            raise ValueError('untargeted transitions must not claim target resolution')
        if self.after is None:
            raise ValueError('successful transitions require a coherent after capture')
        if not self.assertions:
            raise ValueError('successful transitions require at least one passing assertion')
        if any(result.status is not AssertionStatus.PASSED for result in self.assertions):
            raise ValueError('successful transitions cannot contain a non-passing assertion')
        if self.action.response_expectation is not None and not any(
            observation.signal is SettlementSignal.RELEVANT_RESPONSE_OBSERVED and observation.satisfied
            for observation in self.settlement_observations
        ):
            raise ValueError('successful transitions require their declared response evidence')

    def _validate_non_success(self) -> None:
        if self.error_code is None:
            raise ValueError('non-success transitions require a normalized error code')
        pre_dispatch = {
            OutcomeStatus.BLOCKED: (ActionErrorCode.POLICY_BLOCKED, self.policy.status is PolicyStatus.BLOCKED),
            OutcomeStatus.STALE: (ActionErrorCode.STALE_BEFORE_CAPTURE, self.freshness is FreshnessStatus.STALE),
            OutcomeStatus.AMBIGUOUS: (
                ActionErrorCode.TARGET_AMBIGUOUS,
                self.resolution.status is ResolutionStatus.AMBIGUOUS,
            ),
            OutcomeStatus.NOT_FOUND: (
                ActionErrorCode.TARGET_NOT_FOUND,
                self.resolution.status is ResolutionStatus.NOT_FOUND,
            ),
            OutcomeStatus.UNSUPPORTED: (
                self.error_code,
                self.error_code in {ActionErrorCode.UNSUPPORTED_ACTION, ActionErrorCode.UNSUPPORTED_EFFECT}
                and (
                    self.policy.status is PolicyStatus.UNSUPPORTED
                    or self.resolution.status is ResolutionStatus.UNSUPPORTED
                ),
            ),
        }
        if self.outcome in pre_dispatch:
            expected_error, evidence_ok = pre_dispatch[self.outcome]
            if self.error_code is not expected_error or not evidence_ok:
                raise ValueError(f'{self.outcome.value} outcome disagrees with its evidence')
            if self.dispatch.status is not DispatchStatus.NOT_ATTEMPTED or self.after is not None:
                raise ValueError(f'{self.outcome.value} outcome cannot contain dispatch or after-capture evidence')
        elif self.outcome is OutcomeStatus.TIMED_OUT:
            if (
                self.error_code is not ActionErrorCode.SETTLEMENT_TIMEOUT
                or self.settlement is not SettlementStatus.TIMED_OUT
            ):
                raise ValueError('timed-out outcome requires timed-out settlement evidence')
        elif self.outcome is OutcomeStatus.INCONCLUSIVE:
            settlement_inconclusive = (
                self.error_code is ActionErrorCode.SETTLEMENT_INCONCLUSIVE
                and self.settlement is SettlementStatus.INCONCLUSIVE
            )
            assertion_inconclusive = self.error_code is ActionErrorCode.ASSERTION_INCONCLUSIVE and any(
                result.status in {AssertionStatus.UNSUPPORTED, AssertionStatus.INCONCLUSIVE}
                for result in self.assertions
            )
            if not (settlement_inconclusive or assertion_inconclusive):
                raise ValueError('inconclusive outcome requires settlement or assertion evidence')
        elif self.outcome is OutcomeStatus.FAILED and self.error_code in {
            ActionErrorCode.POLICY_BLOCKED,
            ActionErrorCode.STALE_BEFORE_CAPTURE,
            ActionErrorCode.TARGET_AMBIGUOUS,
            ActionErrorCode.TARGET_NOT_FOUND,
            ActionErrorCode.SETTLEMENT_TIMEOUT,
            ActionErrorCode.SETTLEMENT_INCONCLUSIVE,
        }:
            raise ValueError('failed outcome cannot hide a more specific terminal outcome')

    def canonical_dict(self) -> dict[str, Any]:
        """Return stable evidence identity without volatile timing."""
        return self.model_dump(mode='json', exclude={'timing'})

    def canonical_json(self) -> str:
        """Serialize canonical evidence deterministically."""
        return json.dumps(self.canonical_dict(), sort_keys=True, separators=(',', ':'), ensure_ascii=True)

    @property
    def fingerprint(self) -> str:
        """Return a stable digest of non-volatile receipt evidence."""
        return hashlib.sha256(self.canonical_json().encode()).hexdigest()


__all__ = [
    'ACTION_SCHEMA_VERSION',
    'ActionErrorCode',
    'ActionKind',
    'ActionSpec',
    'AssertionResult',
    'AssertionStatus',
    'CaptureRef',
    'DispatchEvidence',
    'DispatchStatus',
    'EffectClass',
    'ElementRef',
    'FreshnessStatus',
    'NetworkResponseEvidence',
    'OutcomeStatus',
    'PolicyEvidence',
    'PolicyStatus',
    'ReceiptTiming',
    'ResolutionEvidence',
    'ResolutionStatus',
    'ResponseBodyState',
    'ResponseExpectationSpec',
    'ScrollDirection',
    'ScrollExtent',
    'ScrollSpec',
    'SettlementObservation',
    'SettlementSignal',
    'SettlementStatus',
    'TransitionReceipt',
]
