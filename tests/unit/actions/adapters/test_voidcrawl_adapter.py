import subprocess
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from yosoi.actions.adapters.voidcrawl import (
    SUPPORTED_ACTION_KINDS,
    AdapterCapabilityPolicy,
    AxClickTarget,
    AxEvidenceResolver,
    RetainedBrowserTab,
    RetainedVoidCrawlSession,
    UnsupportedPostconditionVerifier,
    accessible_name_digest,
    capture_ref_for,
    default_adapter_errors,
)
from yosoi.actions.errors import ActionBoundaryError
from yosoi.actions.models import (
    ActionErrorCode,
    ActionKind,
    ActionSpec,
    AssertionResult,
    AssertionStatus,
    CaptureRef,
    EffectClass,
    ElementRef,
    OutcomeStatus,
    ResolutionStatus,
    ScrollDirection,
    ScrollExtent,
    ScrollSpec,
    SettlementSignal,
    SettlementStatus,
)
from yosoi.actions.protocols import SettlementResult, TransitionVerifier
from yosoi.actions.runtime import ActionRuntime
from yosoi.observations.models.artifact import EvidenceKind
from yosoi.observations.models.snapshot import CaptureProfile, ObservationSnapshot
from yosoi.observations.models.view import RegionRef

_SHA = 'a' * 64
_START_URL = 'https://example.test/list'


class FakeTabError(RuntimeError):
    """Stands in for a VoidCrawl adapter failure without importing the native extension."""


def _snapshot(snapshot_id: str, parent: str | None = None) -> ObservationSnapshot:
    return ObservationSnapshot(
        run_id='run',
        episode_id='episode',
        snapshot_id=snapshot_id,
        parent_snapshot_id=parent,
        captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        requested_profile=CaptureProfile.BROWSER_HEADLESS,
    )


def _ax_node(role: str, name: str) -> dict[str, Any]:
    return {'role': {'type': 'role', 'value': role}, 'name': {'type': 'computedString', 'value': name}}


class FakeTab:
    """Deterministic stand-in for the borrowed VoidCrawl tab. No network, no browser."""

    def __init__(self, *, nodes: list[dict[str, Any]] | None = None) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.nodes = nodes if nodes is not None else [_ax_node('button', 'Next page')]
        self.current_url = _START_URL
        self.idle: str | None = 'networkIdle'
        self.error: Exception | None = None

    async def goto(self, url: str, timeout: float = 30.0) -> object:
        self.calls.append(('goto', url))
        if self.error is not None:
            raise self.error
        self.current_url = url
        return None

    async def url(self) -> str | None:
        return self.current_url

    async def query_ax_tree(self, role: str | None = None, name: str | None = None) -> list[dict[str, Any]]:
        self.calls.append(('query_ax_tree', role or ''))
        if self.error is not None:
            raise self.error
        return [node for node in self.nodes if role is None or node['role']['value'] == role]

    async def click_by_role(self, role: str, name: str, nth: int = 0) -> None:
        self.calls.append(('click_by_role', role, name, str(nth)))
        if self.error is not None:
            raise self.error
        self.current_url = f'{_START_URL}#page-2'

    async def wait_for_network_idle(self, timeout: float = 30.0) -> str | None:
        self.calls.append(('wait_for_network_idle',))
        return self.idle

    def expect_response(
        self,
        pattern: str,
        timeout: float = 30.0,
        max_response_bytes: int = 2_097_152,
        max_total_bytes: int = 8_388_608,
    ) -> Any:
        raise AssertionError('response capture was not configured for this fake')


class PassingVerifier:
    """Application-specific verifier used only by success-path adapter tests."""

    async def verify(
        self,
        before: CaptureRef,
        action: ActionSpec,
        after: CaptureRef,
        settlement: SettlementResult,
    ) -> tuple[AssertionResult, ...]:
        return (AssertionResult(assertion_id='expected_change', status=AssertionStatus.PASSED),)


class FakeCapture:
    """Mints lineage-correct snapshots; `parent_override` forces a broken-lineage capture."""

    def __init__(self) -> None:
        self.count = 0
        self.error: Exception | None = None
        self.parent_override: str | None = None

    async def capture(self, *, parent_snapshot_id: str | None = None) -> ObservationSnapshot:
        if self.error is not None:
            raise self.error
        self.count += 1
        parent = self.parent_override if self.parent_override is not None else parent_snapshot_id
        return _snapshot(f'snap-{self.count}', parent)


def _clock():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    values = iter(base + timedelta(milliseconds=step) for step in range(0, 2000, 10))
    return lambda: next(values)


def _target(snapshot_id: str, *, role: str | None = 'button', name: str | None = 'Next page') -> ElementRef:
    return ElementRef(
        snapshot_id=snapshot_id,
        evidence=(
            RegionRef(
                snapshot_id=snapshot_id,
                artifact_sha256=_SHA,
                modality=EvidenceKind.AX_TREE,
                locator='/ax/node/17',
            ),
        ),
        semantic_role=role,
        accessible_name_hash=accessible_name_digest(name) if name is not None else None,
    )


def _click(snapshot_id: str, **kwargs: Any) -> ActionSpec:
    return ActionSpec(
        kind=ActionKind.CLICK,
        effect=EffectClass.REVERSIBLE_UI,
        target=_target(snapshot_id, **kwargs),
    )


async def _wire(
    *, verifier: TransitionVerifier | None = None, require_network_idle: bool = False
) -> tuple[ActionRuntime, FakeTab, FakeCapture, RetainedVoidCrawlSession, CaptureRef]:
    tab = FakeTab()
    capture = FakeCapture()
    before = capture_ref_for(await capture.capture())
    session = RetainedVoidCrawlSession(
        tab=tab,
        capture=capture,
        active=before,
        require_network_idle=require_network_idle,
        adapter_errors=(FakeTabError,),
    )
    runtime = ActionRuntime(
        session=session,
        resolver=AxEvidenceResolver(tab=tab, adapter_errors=(FakeTabError,)),
        policy=AdapterCapabilityPolicy(),
        verifier=verifier or PassingVerifier(),
        redaction_version='redaction-v1',
        clock=_clock(),
    )
    return runtime, tab, capture, session, before


async def test_missing_postcondition_evidence_is_inconclusive_not_vacuously_successful() -> None:
    runtime, _, _, _, before = await _wire(verifier=UnsupportedPostconditionVerifier())

    receipt = await runtime.perform(before=before, action=_click(before.snapshot_id))

    assert receipt.outcome is OutcomeStatus.INCONCLUSIVE
    assert receipt.error_code is ActionErrorCode.ASSERTION_INCONCLUSIVE
    assert receipt.assertions[0].status is AssertionStatus.UNSUPPORTED


async def test_click_produces_a_success_receipt_with_exact_before_after_lineage() -> None:
    runtime, tab, _, _, before = await _wire()

    receipt = await runtime.perform(before=before, action=_click(before.snapshot_id))

    assert receipt.outcome is OutcomeStatus.SUCCESS
    assert receipt.resolution.status is ResolutionStatus.UNIQUE
    assert receipt.dispatch.adapter_code == 'click_by_role'
    assert receipt.after is not None
    assert receipt.after.parent_snapshot_id == before.snapshot_id
    assert receipt.after.snapshot_id != before.snapshot_id
    assert tab.calls == [
        ('query_ax_tree', 'button'),
        ('click_by_role', 'button', 'Next page', '0'),
        ('wait_for_network_idle',),
    ]


async def test_navigate_dispatches_goto_and_records_the_url_change() -> None:
    runtime, tab, _, _, before = await _wire()
    action = ActionSpec(kind=ActionKind.NAVIGATE, effect=EffectClass.OBSERVATION, url='https://example.test/next')

    receipt = await runtime.perform(before=before, action=action)

    assert receipt.outcome is OutcomeStatus.SUCCESS
    assert receipt.dispatch.adapter_code == 'goto'
    assert tab.calls == [('goto', 'https://example.test/next'), ('wait_for_network_idle',)]
    changed = next(
        observation
        for observation in receipt.settlement_observations
        if observation.signal is SettlementSignal.URL_OR_HISTORY_CHANGED
    )
    assert changed.supported
    assert changed.satisfied


async def test_settlement_declares_every_signal_it_cannot_observe() -> None:
    runtime, _, _, _, before = await _wire()

    receipt = await runtime.perform(before=before, action=_click(before.snapshot_id))

    by_signal = {observation.signal: observation for observation in receipt.settlement_observations}
    assert set(by_signal) == set(SettlementSignal)
    assert by_signal[SettlementSignal.RELEVANT_NETWORK_IDLE].supported
    for signal in (
        SettlementSignal.DOM_QUIET,
        SettlementSignal.DOCUMENT_EPOCH_CHANGED,
        SettlementSignal.VISUAL_STABLE,
        SettlementSignal.CONSOLE_QUIET,
        SettlementSignal.APPLICATION_SIGNAL,
        SettlementSignal.POSTCONDITION_SATISFIED,
    ):
        assert not by_signal[signal].supported
        assert not by_signal[signal].satisfied
        assert by_signal[signal].reason_code is not None


async def test_no_network_idle_still_ends_observation_and_allows_recapture() -> None:
    runtime, tab, _, _, before = await _wire()
    tab.idle = None

    receipt = await runtime.perform(before=before, action=_click(before.snapshot_id))

    assert receipt.outcome is OutcomeStatus.SUCCESS
    assert receipt.settlement is SettlementStatus.SETTLED
    assert receipt.after is not None
    idle = next(
        observation
        for observation in receipt.settlement_observations
        if observation.signal is SettlementSignal.RELEVANT_NETWORK_IDLE
    )
    assert not idle.supported
    assert not idle.satisfied
    assert idle.reason_code == 'network_idle_not_observed'


async def test_strict_network_idle_opt_in_preserves_timeout_gate() -> None:
    runtime, tab, _, _, before = await _wire(require_network_idle=True)
    tab.idle = None

    receipt = await runtime.perform(before=before, action=_click(before.snapshot_id))

    assert receipt.outcome is OutcomeStatus.TIMED_OUT
    assert receipt.settlement is SettlementStatus.TIMED_OUT
    assert receipt.error_code is ActionErrorCode.SETTLEMENT_TIMEOUT
    idle = next(
        observation
        for observation in receipt.settlement_observations
        if observation.signal is SettlementSignal.RELEVANT_NETWORK_IDLE
    )
    assert idle.supported
    assert not idle.satisfied
    assert idle.reason_code == 'network_idle_timeout'


@pytest.mark.parametrize(
    ('kind', 'scroll'),
    [
        (ActionKind.BACK, None),
        (ActionKind.FORWARD, None),
        (ActionKind.SCROLL, ScrollSpec(direction=ScrollDirection.DOWN, extent=ScrollExtent.PAGE)),
    ],
)
async def test_absent_capabilities_fail_closed_before_the_browser_is_touched(kind, scroll) -> None:
    runtime, tab, capture, _, before = await _wire()
    action = ActionSpec(kind=kind, effect=EffectClass.REVERSIBLE_UI, scroll=scroll)

    receipt = await runtime.perform(before=before, action=action)

    assert receipt.outcome is OutcomeStatus.UNSUPPORTED
    assert receipt.error_code is ActionErrorCode.UNSUPPORTED_ACTION
    assert receipt.policy.reason_code in {'no_history_navigation', 'no_coordinate_free_scroll'}
    assert receipt.after is None
    assert tab.calls == []
    assert capture.count == 1


@pytest.mark.parametrize('kind', [ActionKind.BACK, ActionKind.FORWARD, ActionKind.SCROLL])
async def test_dispatch_refuses_an_absent_capability_even_without_the_policy_gate(kind) -> None:
    _, tab, _capture, session, _ = await _wire()
    scroll = ScrollSpec(direction=ScrollDirection.DOWN, extent=ScrollExtent.PAGE) if kind is ActionKind.SCROLL else None
    action = ActionSpec(kind=kind, effect=EffectClass.REVERSIBLE_UI, scroll=scroll)

    with pytest.raises(ActionBoundaryError) as caught:
        await session.dispatch(action, None)

    assert caught.value.code is ActionErrorCode.UNSUPPORTED_ACTION
    assert tab.calls == []


@pytest.mark.parametrize(
    ('nodes', 'outcome'),
    [
        ([], OutcomeStatus.NOT_FOUND),
        ([_ax_node('button', 'Next page'), _ax_node('button', 'Next  page')], OutcomeStatus.AMBIGUOUS),
    ],
)
async def test_non_unique_live_targets_never_dispatch(nodes, outcome) -> None:
    runtime, tab, _, _, before = await _wire()
    tab.nodes = nodes

    receipt = await runtime.perform(before=before, action=_click(before.snapshot_id))

    assert receipt.outcome is outcome
    assert tab.calls == [('query_ax_tree', 'button')]


@pytest.mark.parametrize(
    ('kwargs', 'reason'),
    [
        ({'role': None}, 'requires_role_and_name'),
        ({'name': None}, 'requires_role_and_name'),
    ],
)
async def test_targets_without_role_and_name_are_unsupported_not_guessed(kwargs, reason) -> None:
    runtime, tab, _, _, before = await _wire()

    receipt = await runtime.perform(before=before, action=_click(before.snapshot_id, **kwargs))

    assert receipt.outcome is OutcomeStatus.UNSUPPORTED
    assert receipt.resolution.status is ResolutionStatus.UNSUPPORTED
    assert receipt.resolution.reason_code == reason
    assert tab.calls == []


async def test_non_ax_evidence_is_unsupported_rather_than_resolved_by_another_route() -> None:
    runtime, tab, _, _, before = await _wire()
    target = ElementRef(
        snapshot_id=before.snapshot_id,
        evidence=(
            RegionRef(
                snapshot_id=before.snapshot_id,
                artifact_sha256=_SHA,
                modality=EvidenceKind.RENDERED_DOM,
                locator='//*[@id="next"]',
            ),
        ),
        semantic_role='button',
        accessible_name_hash=accessible_name_digest('Next page'),
    )
    action = ActionSpec(kind=ActionKind.CLICK, effect=EffectClass.REVERSIBLE_UI, target=target)

    receipt = await runtime.perform(before=before, action=action)

    assert receipt.resolution.reason_code == 'requires_ax_tree_evidence'
    assert tab.calls == []


async def test_adapter_failures_are_normalized_and_carry_no_raw_text() -> None:
    runtime, tab, _, _, before = await _wire()
    tab.error = FakeTabError('navigation failed for https://example.test/?token=super-secret')

    receipt = await runtime.perform(before=before, action=_click(before.snapshot_id))

    assert receipt.error_code is ActionErrorCode.ADAPTER_ERROR
    serialized = receipt.model_dump_json()
    assert 'secret' not in serialized
    assert 'navigation failed' not in serialized


def test_unclassified_runtime_errors_are_not_hidden_as_browser_outcomes() -> None:
    assert RuntimeError not in default_adapter_errors()


async def test_a_programming_defect_is_not_disguised_as_a_browser_outcome() -> None:
    runtime, tab, _, _, before = await _wire()
    tab.error = TypeError('programming defect containing secret')

    with pytest.raises(TypeError, match='programming defect'):
        await runtime.perform(before=before, action=_click(before.snapshot_id))


async def test_a_capture_with_broken_lineage_fails_closed() -> None:
    runtime, _, capture, _, before = await _wire()
    capture.parent_override = 'some-other-snapshot'

    receipt = await runtime.perform(before=before, action=_click(before.snapshot_id))

    assert receipt.outcome is OutcomeStatus.FAILED
    assert receipt.error_code is ActionErrorCode.AFTER_CAPTURE_FAILED
    assert receipt.after is None


async def test_a_stale_epoch_is_refused_after_the_session_advances() -> None:
    runtime, _, _, session, before = await _wire()
    first = await runtime.perform(before=before, action=_click(before.snapshot_id))
    assert first.outcome is OutcomeStatus.SUCCESS

    replayed = await runtime.perform(before=before, action=_click(before.snapshot_id))

    assert replayed.outcome is OutcomeStatus.STALE
    assert await session.active_capture() == first.after


async def test_capture_refs_are_manifest_exact() -> None:
    plain = capture_ref_for(_snapshot('snap-1'))
    same = capture_ref_for(_snapshot('snap-1'))
    relineaged = capture_ref_for(_snapshot('snap-1', 'snap-0'))

    assert plain == same
    assert relineaged.manifest_sha256 != plain.manifest_sha256


def test_accessible_name_digest_collapses_whitespace_like_the_observation_kernel() -> None:
    assert accessible_name_digest('Next  page') == accessible_name_digest(' Next\npage ')
    assert accessible_name_digest('Next page') != accessible_name_digest('Previous page')


def _protocol_methods() -> set[str]:
    return {name for name in dir(RetainedBrowserTab) if not name.startswith('_')}


def test_the_retained_tab_protocol_is_the_only_browser_surface_this_seam_can_reach() -> None:
    assert _protocol_methods() == {
        'goto',
        'url',
        'query_ax_tree',
        'click_by_role',
        'wait_for_network_idle',
        'expect_response',
    }


def test_the_retained_tab_surface_matches_the_installed_voidcrawl_build() -> None:
    """Prove core methods exist while optional response support remains capability-gated."""
    from voidcrawl import PooledTab

    for method in _protocol_methods() - {'expect_response'}:
        assert callable(getattr(PooledTab, method, None)), f'PooledTab lost {method}'
    for absent in ('back', 'forward', 'go_back', 'go_forward', 'history', 'scroll', 'scroll_by', 'scroll_into_view'):
        assert not hasattr(PooledTab, absent), f'PooledTab now offers {absent}; revisit the capability declaration'
    assert {kind.value for kind in SUPPORTED_ACTION_KINDS} == {'navigate', 'click'}
    assert isinstance(hasattr(PooledTab, 'expect_response'), bool)


def test_the_adapter_module_pulls_in_no_browser_provider_or_qa_runtime() -> None:
    probe = """
import sys
import yosoi.actions.adapters.voidcrawl as adapter
assert adapter.AxClickTarget is not None
assert "voidcrawl" not in sys.modules
assert not any(name.startswith("yosoi.qa") for name in sys.modules)
assert "yosoi.core.fetcher.voiddriver" not in sys.modules
assert "pydantic_ai" not in sys.modules
"""
    subprocess.run([sys.executable, '-c', probe], check=True)


async def test_the_click_handle_is_runtime_only_and_never_reaches_a_receipt() -> None:
    runtime, _, _, _, before = await _wire()

    receipt = await runtime.perform(before=before, action=_click(before.snapshot_id))

    assert 'Next page' not in receipt.model_dump_json()
    assert AxClickTarget(role='button', name='Next page').name == 'Next page'
