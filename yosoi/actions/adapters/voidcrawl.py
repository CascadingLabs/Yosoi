"""Concrete retained-session adapter over the VoidCrawl browser tab Yosoi already owns.

This is the CAS-270 seam between the browser-neutral transition ledger
(:mod:`yosoi.actions.runtime`) and the retained browser machinery that already exists:
``yosoi.core.fetcher.voiddriver._VoidCrawlFetcher`` owns the single ``BrowserPool`` and lends a
live ``voidcrawl.PooledTab`` through ``browse()``. This module creates no pool, opens no tab,
and imports neither VoidCrawl nor ``yosoi.qa`` — the borrowed tab and the snapshot capture are
injected, so the one browser path that exists stays the one browser path that exists.

Capabilities are declared from what that retained tab can actually do, never from what the
action vocabulary can express:

- ``navigate`` — supported via ``goto``. ``ActionSpec`` has already refused anything that is
  not an absolute, credential-free, secret-free HTTP(S) URL.
- ``click`` — supported via ``query_ax_tree`` (resolution) and ``click_by_role`` (dispatch),
  the accessibility-role + accessible-name convention the observation kernel already mints its
  AX labels for.
- ``back`` / ``forward`` — **unsupported**. The retained tab exposes no history API at all;
  the only route would be an injected ``history.back()`` page script, which this seam forbids.
- ``scroll`` — **unsupported**. The retained tab offers no coordinate-free scroll primitive:
  only a page script, a pixel-coordinate mouse wheel, or a focus-dependent key event, and the
  resulting scroll offset is not observable without a script either.

An unsupported capability fails closed at :class:`AdapterCapabilityPolicy` — before resolution
reaches the browser and before anything is dispatched — and is refused a second time inside
:meth:`RetainedVoidCrawlSession.dispatch` so a caller who supplies a laxer policy still cannot
reach a capability the adapter does not have.

Settlement is reported from observable signals only: URL/history change is measured, and the
bounded network-idle observation window is always allowed to end before recapture. A returned
network-idle marker is recorded as observed; ``None`` is recorded as unsupported rather than
inventing global-idle evidence. Callers that truly require global idle may opt into the strict
mode, which turns that bounded non-result into a timeout. Every other signal in the vector is
declared unsupported with a reason rather than silently omitted or assumed satisfied.

The adapter is deliberately not a composition root: it holds no pool, opens and closes nothing,
and performs no acquisition. Its caller borrows the tab, produces the captures, and owns the
lifetime.
"""

from __future__ import annotations

import contextlib
import hashlib
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

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
    NetworkResponseEvidence,
    PolicyEvidence,
    PolicyStatus,
    ResolutionEvidence,
    ResolutionStatus,
    ResponseBodyState,
    ResponseExpectationSpec,
    SettlementObservation,
    SettlementSignal,
    SettlementStatus,
)
from yosoi.actions.protocols import ResolvedTarget, RetainedActionSession, SettlementResult
from yosoi.observations.models.artifact import EvidenceKind
from yosoi.observations.models.snapshot import ObservationSnapshot

ADAPTER_POLICY_VERSION = 'voidcrawl-retained-tab-v1'
"""Version stamped onto every policy decision this adapter's capability gate makes."""

SUPPORTED_ACTION_KINDS = frozenset({ActionKind.NAVIGATE, ActionKind.CLICK})
"""The action kinds the retained tab can actually perform. Everything else fails closed."""

ALLOWED_EFFECTS = frozenset({EffectClass.OBSERVATION, EffectClass.REVERSIBLE_UI})
"""Effect classes this unauthenticated slice authorizes; a wider effect is blocked, not run."""

UNSUPPORTED_CAPABILITY_REASONS = {
    ActionKind.BACK: 'no_history_navigation',
    ActionKind.FORWARD: 'no_history_navigation',
    ActionKind.SCROLL: 'no_coordinate_free_scroll',
}
"""Why each expressible-but-absent capability is refused, in model-safe code form."""

DEFAULT_NAVIGATE_TIMEOUT_SECONDS = 30.0
DEFAULT_SETTLE_TIMEOUT_SECONDS = 10.0
DEFAULT_REQUIRE_NETWORK_IDLE = False
"""Whether settlement requires the weak global network-idle signal by default."""

DEFAULT_RESPONSE_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_RESPONSE_BYTES = 2_097_152
DEFAULT_MAX_TOTAL_RESPONSE_BYTES = 8_388_608

AX_TARGET_ORDINAL = 0
"""Resolution only ever hands back a target that is unique in the live AX tree, so the click
ordinal is always the first (and only) match. Anything less than unique never reaches dispatch."""

_UNSUPPORTED_SETTLEMENT_SIGNALS = (
    (SettlementSignal.DOCUMENT_EPOCH_CHANGED, 'requires_page_script'),
    (SettlementSignal.DOM_QUIET, 'requires_page_script'),
    (SettlementSignal.APPLICATION_SIGNAL, 'requires_page_script'),
    (SettlementSignal.POSTCONDITION_SATISFIED, 'no_declared_postcondition'),
    (SettlementSignal.VISUAL_STABLE, 'not_captured'),
    (SettlementSignal.CONSOLE_QUIET, 'not_captured'),
)
"""Signals this adapter cannot observe, stated as unsupported instead of quietly dropped."""


def response_timeout_errors() -> tuple[type[BaseException], ...]:
    """Return the native bounded-response timeout without importing VoidCrawl eagerly."""
    try:
        from voidcrawl import ResponseTimeoutError
    except ImportError:
        return (TimeoutError,)
    return (ResponseTimeoutError, TimeoutError)


def default_adapter_errors() -> tuple[type[BaseException], ...]:
    """Return the exception types treated as expected browser failures, not programming defects.

    Resolved on call rather than at import so this module never drags in the VoidCrawl native
    extension, and so a build without VoidCrawl still imports and degrades to the stdlib I/O
    failures instead of failing closed at import time.
    """
    try:
        from voidcrawl import VoidCrawlError
    except ImportError:
        return (TimeoutError, OSError)
    return (VoidCrawlError, TimeoutError, OSError)


class RetainedBrowserTab(Protocol):
    """The exact slice of the retained VoidCrawl tab this adapter is permitted to use.

    Narrow on purpose. The real ``PooledTab`` also exposes ``eval_js``, ``type_into``,
    ``click_xy``, ``dispatch_key_event``, cookie and profile controls, and downloads. None of
    them appear here, so an arbitrary script, a coordinate click, an input or submission, or a
    credential cannot be reached through this seam even by mistake.
    """

    async def goto(self, url: str, timeout: float = ...) -> object:
        """Navigate to an absolute URL and wait for the load to settle."""
        ...

    async def url(self) -> str | None:
        """Return the tab's current URL."""
        ...

    async def query_ax_tree(self, role: str | None = ..., name: str | None = ...) -> list[dict[str, Any]]:
        """Return the live accessibility nodes matching a computed role and/or name."""
        ...

    async def click_by_role(self, role: str, name: str, nth: int = ...) -> None:
        """Click the nth element matching an accessibility role and accessible name."""
        ...

    async def wait_for_network_idle(self, timeout: float = ...) -> str | None:
        """Wait for network activity to settle; ``None`` means the wait timed out."""
        ...

    def expect_response(
        self,
        pattern: str,
        timeout: float = ...,
        max_response_bytes: int = ...,
        max_total_bytes: int = ...,
    ) -> ResponseExpectation:
        """Arm one bounded passive response expectation on this exact borrowed tab."""
        ...


class CapturedResponse(Protocol):
    """Safe metadata slice read from VoidCrawl's bounded captured response."""

    url: str
    status: int
    mime_type: str
    resource_type: str
    from_cache: bool
    from_service_worker: bool
    body_state: str
    truncated: bool


class ResponseExpectation(Protocol):
    """Async expectation context returned by the retained tab."""

    async def __aenter__(self) -> ResponseExpectation: ...

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> bool: ...

    @property
    def value(self) -> Awaitable[CapturedResponse]: ...


class SnapshotCapture(Protocol):
    """Produces one policy-safe observation snapshot from the retained session.

    Structurally satisfied by ``yosoi.qa.capture.QACaptureSession``. It is declared here rather
    than imported because QA is a consumer of the action ledger, not its dependency — importing
    it would invert the layering the QA package explicitly forbids.
    """

    async def capture(self, *, parent_snapshot_id: str | None = ...) -> ObservationSnapshot:
        """Capture one page state, linked to the snapshot it descends from."""
        ...


def accessible_name_digest(name: str) -> str:
    """Return the canonical digest of an accessible name, for target identity without the name.

    Whitespace is collapsed exactly as ``yosoi.observations.ax_tree.ax_attributes`` collapses it,
    so a name that the observation kernel considers one fact hashes to one value. The digest, not
    the name, is what an :class:`~yosoi.actions.models.ElementRef` carries: a target survives
    serialization into a receipt without the page's own text riding along with it.
    """
    return hashlib.sha256(' '.join(name.split()).encode('utf-8')).hexdigest()


def snapshot_manifest_digest(snapshot: ObservationSnapshot) -> str:
    """Return the exact identity of one capture manifest.

    Digests the whole manifest — artifact digests, declared capabilities, lineage — so a
    :class:`~yosoi.actions.models.CaptureRef` in a receipt names one exact set of bytes. Any
    change to what was captured changes the reference.
    """
    return hashlib.sha256(snapshot.model_dump_json().encode('utf-8')).hexdigest()


def capture_ref_for(snapshot: ObservationSnapshot) -> CaptureRef:
    """Mint the ledger reference for one captured snapshot, preserving its declared lineage."""
    return CaptureRef(
        snapshot_id=snapshot.snapshot_id,
        manifest_sha256=snapshot_manifest_digest(snapshot),
        parent_snapshot_id=snapshot.parent_snapshot_id,
    )


def response_evidence_for(response: CapturedResponse, *, pattern_id: str) -> NetworkResponseEvidence:
    """Reduce a captured response to immutable metadata without headers, query, or body bytes."""
    parts = urlsplit(response.url)
    if parts.scheme not in {'http', 'https'} or not parts.hostname or parts.username or parts.password:
        raise ValueError('captured response URL is not policy-safe')
    port = f':{parts.port}' if parts.port is not None else ''
    origin = f'{parts.scheme}://{parts.hostname}{port}'
    path = parts.path or '/'
    sanitized_url = f'{origin}{path}'
    return NetworkResponseEvidence(
        pattern_id=pattern_id,
        request_url_sha256=hashlib.sha256(sanitized_url.encode()).hexdigest(),
        origin_sha256=hashlib.sha256(origin.encode()).hexdigest(),
        path=path,
        status=response.status,
        resource_type=response.resource_type.casefold(),
        mime_type=response.mime_type.casefold(),
        body_state=ResponseBodyState(response.body_state),
        from_cache=response.from_cache,
        from_service_worker=response.from_service_worker,
        truncated=response.truncated,
    )


@dataclass(frozen=True)
class AxClickTarget:
    """A live accessibility target proven unique at resolution time.

    Runtime-only: it never enters a receipt, which is why it may hold the accessible name that
    :class:`~yosoi.actions.models.ElementRef` deliberately reduces to a digest.
    """

    role: str
    name: str


def _ax_text(node: Mapping[str, Any], key: str) -> str:
    """Read a CDP accessibility field, which arrives either wrapped in a value object or bare."""
    value = node.get(key)
    if isinstance(value, dict):
        inner = value.get('value')
        return inner if isinstance(inner, str) else ''
    return value if isinstance(value, str) else ''


class AxEvidenceResolver:
    """Bind capture-bound accessibility evidence to at most one live target.

    Uniqueness is measured against the live tree at the moment of the action rather than assumed
    from the capture: a target that was unique when the page was indexed and is duplicated now is
    ambiguous now, and ambiguity never dispatches.
    """

    def __init__(
        self,
        *,
        tab: RetainedBrowserTab,
        adapter_errors: tuple[type[BaseException], ...] | None = None,
    ) -> None:
        """Bind the borrowed tab and the exceptions to treat as expected browser failures."""
        self._tab = tab
        self._adapter_errors = default_adapter_errors() if adapter_errors is None else adapter_errors

    async def resolve(
        self,
        session: RetainedActionSession,  # noqa: ARG002 — the boundary protocol supplies it; this resolver reads the tab it was given
        before: CaptureRef,
        target: ElementRef,
    ) -> ResolvedTarget:
        """Resolve one capture-bound target against the live accessibility tree."""
        unsupported = self._unsupported_reason(before, target)
        if unsupported is not None:
            return ResolvedTarget(
                evidence=ResolutionEvidence(
                    status=ResolutionStatus.UNSUPPORTED, candidate_count=0, reason_code=unsupported
                )
            )
        role = target.semantic_role or ''
        digest = target.accessible_name_hash
        try:
            nodes = await self._tab.query_ax_tree(role=role)
        except self._adapter_errors as exc:
            raise ActionBoundaryError(ActionErrorCode.ADAPTER_ERROR) from exc
        names = [name for node in nodes if (name := _ax_text(node, 'name')) and accessible_name_digest(name) == digest]
        if len(names) == 1:
            return ResolvedTarget(
                evidence=ResolutionEvidence(status=ResolutionStatus.UNIQUE, candidate_count=1),
                handle=AxClickTarget(role=role, name=names[0]),
            )
        if not names:
            return ResolvedTarget(evidence=ResolutionEvidence(status=ResolutionStatus.NOT_FOUND, candidate_count=0))
        return ResolvedTarget(
            evidence=ResolutionEvidence(status=ResolutionStatus.AMBIGUOUS, candidate_count=len(names))
        )

    def _unsupported_reason(self, before: CaptureRef, target: ElementRef) -> str | None:
        """State why a target cannot be resolved by this adapter, rather than guessing at it."""
        if target.snapshot_id != before.snapshot_id:
            return 'foreign_capture'
        if target.semantic_role is None or target.accessible_name_hash is None:
            return 'requires_role_and_name'
        if not any(ref.modality is EvidenceKind.AX_TREE for ref in target.evidence):
            return 'requires_ax_tree_evidence'
        return None


class AdapterCapabilityPolicy:
    """Authorize an action only if the retained tab really has the capability it needs.

    The gate sits before dispatch, so an absent capability produces an ``unsupported`` receipt
    without the browser ever being touched.
    """

    def __init__(
        self,
        *,
        tab: RetainedBrowserTab | None = None,
        supported_kinds: frozenset[ActionKind] = SUPPORTED_ACTION_KINDS,
        policy_version: str = ADAPTER_POLICY_VERSION,
    ) -> None:
        """Bind the retained tab capabilities and version stamped onto decisions."""
        self._tab = tab
        self._supported_kinds = supported_kinds
        self._policy_version = policy_version

    async def decide(
        self,
        before: CaptureRef,  # noqa: ARG002 — the boundary protocol supplies it; capability is not capture-dependent
        action: ActionSpec,
        resolution: ResolutionEvidence,  # noqa: ARG002 — the runtime has already refused any non-unique resolution
    ) -> PolicyEvidence:
        """Decide one action against the declared capability and effect bounds."""
        if action.effect not in ALLOWED_EFFECTS:
            return PolicyEvidence(
                status=PolicyStatus.BLOCKED,
                policy_version=self._policy_version,
                rule_id='effect-out-of-slice',
                reason_code='effect_not_authorized',
            )
        if action.kind not in self._supported_kinds:
            return PolicyEvidence(
                status=PolicyStatus.UNSUPPORTED,
                policy_version=self._policy_version,
                rule_id='unsupported-capability',
                reason_code=UNSUPPORTED_CAPABILITY_REASONS.get(action.kind, 'unsupported_action'),
                unsupported_error=ActionErrorCode.UNSUPPORTED_ACTION,
            )
        if action.response_expectation is not None and not callable(getattr(self._tab, 'expect_response', None)):
            return PolicyEvidence(
                status=PolicyStatus.UNSUPPORTED,
                policy_version=self._policy_version,
                rule_id='unsupported-response-observer',
                reason_code='no_response_expectation',
                unsupported_error=ActionErrorCode.UNSUPPORTED_ACTION,
            )
        return PolicyEvidence(
            status=PolicyStatus.ALLOWED,
            policy_version=self._policy_version,
            rule_id='supported-capability',
        )


class UnsupportedPostconditionVerifier:
    """Fail closed when no application-level postcondition verifier was injected.

    Dispatch, network idle, and a lineage-correct recapture prove that an action was attempted;
    they do not prove that the requested UI change happened. Missing postcondition evidence is
    therefore explicit and inconclusive rather than an empty assertion vector that could pass
    vacuously.
    """

    async def verify(
        self,
        before: CaptureRef,  # noqa: ARG002 — the boundary protocol supplies the full transition
        action: ActionSpec,  # noqa: ARG002 — no postcondition is configured in this verifier
        after: CaptureRef,  # noqa: ARG002 — lineage is enforced by capture_after and the receipt model
        settlement: SettlementResult,  # noqa: ARG002 — settlement evidence is recorded separately
    ) -> tuple[AssertionResult, ...]:
        """Return one model-safe unsupported assertion so the receipt cannot pass vacuously."""
        return (
            AssertionResult(
                assertion_id='postcondition',
                status=AssertionStatus.UNSUPPORTED,
                reason_code='not_configured',
            ),
        )


class RetainedVoidCrawlSession:
    """A borrowed VoidCrawl tab presented as one evidence-producing action session.

    The session owns neither the tab nor the pool: it is handed a live tab and a capture
    boundary, and tracks only which capture epoch is currently active so a stale source capture
    is refused instead of acted upon.
    """

    def __init__(
        self,
        *,
        tab: RetainedBrowserTab,
        capture: SnapshotCapture,
        active: CaptureRef,
        navigate_timeout: float = DEFAULT_NAVIGATE_TIMEOUT_SECONDS,
        settle_timeout: float = DEFAULT_SETTLE_TIMEOUT_SECONDS,
        require_network_idle: bool = DEFAULT_REQUIRE_NETWORK_IDLE,
        adapter_errors: tuple[type[BaseException], ...] | None = None,
        response_timeout_error_types: tuple[type[BaseException], ...] | None = None,
    ) -> None:
        """Bind a borrowed tab, its capture boundary, and the capture epoch already in effect."""
        self._tab = tab
        self._capture = capture
        self._active = active
        self._navigate_timeout = navigate_timeout
        self._settle_timeout = settle_timeout
        self._require_network_idle = require_network_idle
        self._adapter_errors = default_adapter_errors() if adapter_errors is None else adapter_errors
        self._response_timeout_errors = (
            response_timeout_errors() if response_timeout_error_types is None else response_timeout_error_types
        )
        self._response_spec: ResponseExpectationSpec | None = None
        self._response_expectation: ResponseExpectation | None = None
        self._url_before_dispatch: str | None = None

    async def active_capture(self) -> CaptureRef:
        """Return the capture epoch this session is currently standing on."""
        return self._active

    async def arm_observers(self, action: ActionSpec, target: object | None) -> None:  # noqa: ARG002
        """Arm configured passive response capture before dispatch."""
        self._response_spec = action.response_expectation
        await self._arm_relevant_response()

    async def dispatch(self, action: ActionSpec, target: object | None) -> DispatchEvidence:
        """Dispatch exactly one action, refusing any capability the retained tab lacks."""
        if action.kind not in SUPPORTED_ACTION_KINDS:
            raise ActionBoundaryError(ActionErrorCode.UNSUPPORTED_ACTION)
        self._url_before_dispatch = await self._read_url()
        if action.kind is ActionKind.NAVIGATE:
            return await self._dispatch_navigate(action)
        return await self._dispatch_click(target)

    async def settle(
        self,
        action: ActionSpec,  # noqa: ARG002 — settlement is observed from the tab, not inferred from intent
        dispatch: DispatchEvidence,  # noqa: ARG002 — the runtime only calls settle after a dispatch succeeded
    ) -> SettlementResult:
        """Observe bounded relevant-response evidence or optional coarse global idle."""
        response_observation = await self._finish_relevant_response()
        if self._response_spec is None:
            try:
                idle = await self._tab.wait_for_network_idle(self._settle_timeout)
            except self._adapter_errors as exc:
                raise ActionBoundaryError(ActionErrorCode.ADAPTER_ERROR) from exc
            idle_observation = SettlementObservation(
                signal=SettlementSignal.RELEVANT_NETWORK_IDLE,
                supported=idle is not None or self._require_network_idle,
                satisfied=idle is not None,
                reason_code=(
                    None
                    if idle is not None
                    else 'network_idle_timeout'
                    if self._require_network_idle
                    else 'network_idle_not_observed'
                ),
            )
            status = (
                SettlementStatus.SETTLED
                if idle is not None or not self._require_network_idle
                else SettlementStatus.TIMED_OUT
            )
        else:
            idle_observation = SettlementObservation(
                signal=SettlementSignal.RELEVANT_NETWORK_IDLE,
                supported=False,
                satisfied=False,
                reason_code='superseded_by_relevant_response',
            )
            status = SettlementStatus.SETTLED if response_observation.satisfied else SettlementStatus.INCONCLUSIVE
        url_after = await self._read_url()
        observations = (
            response_observation,
            idle_observation,
            SettlementObservation(
                signal=SettlementSignal.URL_OR_HISTORY_CHANGED,
                supported=True,
                satisfied=url_after != self._url_before_dispatch,
            ),
            *(
                SettlementObservation(signal=signal, supported=False, satisfied=False, reason_code=reason)
                for signal, reason in _UNSUPPORTED_SETTLEMENT_SIGNALS
            ),
        )
        return SettlementResult(status, observations)

    async def _arm_relevant_response(self) -> None:
        """Arm configured passive capture before dispatch touches the page."""
        spec = self._response_spec
        if spec is None:
            return
        if self._response_expectation is not None:
            raise ActionBoundaryError(ActionErrorCode.ADAPTER_ERROR)
        if not callable(getattr(self._tab, 'expect_response', None)):
            raise ActionBoundaryError(ActionErrorCode.ADAPTER_ERROR)
        try:
            pending = self._tab.expect_response(
                spec.pattern,
                timeout=spec.timeout,
                max_response_bytes=spec.max_response_bytes,
                max_total_bytes=spec.max_total_bytes,
            )
            await pending.__aenter__()
        except self._adapter_errors as exc:
            raise ActionBoundaryError(ActionErrorCode.ADAPTER_ERROR) from exc
        self._response_expectation = pending

    async def cleanup_observers(self) -> None:
        """Disarm response capture after failed dispatch or cancelled settlement."""
        pending, self._response_expectation = self._response_expectation, None
        self._response_spec = None
        if pending is None:
            return
        with contextlib.suppress(*self._adapter_errors, *self._response_timeout_errors):
            await pending.__aexit__(RuntimeError, None, None)

    async def _finish_relevant_response(self) -> SettlementObservation:
        """Finish the pre-armed expectation and reduce it to receipt-safe metadata."""
        spec = self._response_spec
        if spec is None:
            return SettlementObservation(
                signal=SettlementSignal.RELEVANT_RESPONSE_OBSERVED,
                supported=False,
                satisfied=False,
                reason_code='not_configured',
            )
        pending, self._response_expectation = self._response_expectation, None
        if pending is None:
            raise ActionBoundaryError(ActionErrorCode.ADAPTER_ERROR)
        try:
            await pending.__aexit__(None, None, None)
            response = await pending.value
            evidence = response_evidence_for(response, pattern_id=spec.pattern_id)
        except self._response_timeout_errors:
            return SettlementObservation(
                signal=SettlementSignal.RELEVANT_RESPONSE_OBSERVED,
                supported=True,
                satisfied=False,
                reason_code='response_timeout',
            )
        except (ValueError, *self._adapter_errors) as exc:
            raise ActionBoundaryError(ActionErrorCode.ADAPTER_ERROR) from exc
        return SettlementObservation(
            signal=SettlementSignal.RELEVANT_RESPONSE_OBSERVED,
            supported=True,
            satisfied=True,
            responses=(evidence,),
        )

    async def capture_after(self, *, parent_snapshot_id: str) -> CaptureRef:
        """Capture the post-action state and advance the epoch, or fail closed on broken lineage."""
        try:
            snapshot = await self._capture.capture(parent_snapshot_id=parent_snapshot_id)
        except self._adapter_errors as exc:
            raise ActionBoundaryError(ActionErrorCode.AFTER_CAPTURE_FAILED) from exc
        if snapshot.parent_snapshot_id != parent_snapshot_id or snapshot.snapshot_id == parent_snapshot_id:
            raise ActionBoundaryError(ActionErrorCode.AFTER_CAPTURE_FAILED)
        self._active = capture_ref_for(snapshot)
        return self._active

    async def _read_url(self) -> str:
        """Read the tab's current URL; a tab that cannot report it cannot be reasoned about."""
        try:
            url = await self._tab.url()
        except self._adapter_errors as exc:
            raise ActionBoundaryError(ActionErrorCode.ADAPTER_ERROR) from exc
        if url is None:
            raise ActionBoundaryError(ActionErrorCode.ADAPTER_ERROR)
        return url

    async def _dispatch_navigate(self, action: ActionSpec) -> DispatchEvidence:
        """Navigate to the already-validated absolute HTTP(S) URL carried by the action."""
        if action.url is None:
            raise ActionBoundaryError(ActionErrorCode.ADAPTER_ERROR)
        try:
            await self._tab.goto(action.url, timeout=self._navigate_timeout)
        except self._adapter_errors as exc:
            raise ActionBoundaryError(ActionErrorCode.DISPATCH_FAILED) from exc
        return DispatchEvidence(status=DispatchStatus.DISPATCHED, adapter_code='goto')

    async def _dispatch_click(self, target: object | None) -> DispatchEvidence:
        """Click the accessibility target this adapter's own resolver proved unique."""
        if not isinstance(target, AxClickTarget):
            raise ActionBoundaryError(ActionErrorCode.ADAPTER_ERROR)
        try:
            await self._tab.click_by_role(target.role, target.name, AX_TARGET_ORDINAL)
        except self._adapter_errors as exc:
            raise ActionBoundaryError(ActionErrorCode.DISPATCH_FAILED) from exc
        return DispatchEvidence(status=DispatchStatus.DISPATCHED, adapter_code='click_by_role')


__all__ = [
    'ADAPTER_POLICY_VERSION',
    'ALLOWED_EFFECTS',
    'AX_TARGET_ORDINAL',
    'DEFAULT_MAX_RESPONSE_BYTES',
    'DEFAULT_MAX_TOTAL_RESPONSE_BYTES',
    'DEFAULT_NAVIGATE_TIMEOUT_SECONDS',
    'DEFAULT_REQUIRE_NETWORK_IDLE',
    'DEFAULT_RESPONSE_TIMEOUT_SECONDS',
    'DEFAULT_SETTLE_TIMEOUT_SECONDS',
    'SUPPORTED_ACTION_KINDS',
    'UNSUPPORTED_CAPABILITY_REASONS',
    'AdapterCapabilityPolicy',
    'AxClickTarget',
    'AxEvidenceResolver',
    'RetainedBrowserTab',
    'RetainedVoidCrawlSession',
    'SnapshotCapture',
    'UnsupportedPostconditionVerifier',
    'accessible_name_digest',
    'capture_ref_for',
    'default_adapter_errors',
    'response_evidence_for',
    'response_timeout_errors',
    'snapshot_manifest_digest',
]
