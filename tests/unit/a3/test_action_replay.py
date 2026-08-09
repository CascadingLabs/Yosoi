"""Deterministic tests for receipt-backed exact action replay."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from yosoi.a3 import (
    ActionEpisode,
    ActionEpisodeBuilder,
    ActionEpisodeStep,
    ActionEpisodeStore,
    ActionReplayCompileError,
    ActionReplayExecutor,
    ReplayExpectation,
    ReplayRunStatus,
    ReplayTargetSignature,
    compile_action_episode,
)
from yosoi.actions.adapters.voidcrawl import ADAPTER_POLICY_VERSION, accessible_name_digest, capture_ref_for
from yosoi.actions.models import (
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
    OutcomeStatus,
    PolicyEvidence,
    PolicyStatus,
    ReceiptTiming,
    ResolutionEvidence,
    ResolutionStatus,
    SettlementObservation,
    SettlementSignal,
    SettlementStatus,
    TransitionReceipt,
)
from yosoi.observations.models.artifact import ArtifactRef, EvidenceKind, Sensitivity
from yosoi.observations.models.snapshot import CaptureCapability, CaptureProfile, ObservationSnapshot
from yosoi.observations.models.view import RegionRef

_FILM = 'Once Upon a Time... in Hollywood'
_PERSON = 'Brad Pitt'
_SHA_A = 'a' * 64
_SHA_B = 'b' * 64


def _source_snapshot(snapshot_id: str, digest: str, parent: str | None = None) -> ObservationSnapshot:
    return ObservationSnapshot(
        run_id='discovery-run',
        episode_id='imdb-discovery',
        snapshot_id=snapshot_id,
        parent_snapshot_id=parent,
        captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        requested_profile=CaptureProfile.BROWSER_HEADLESS,
        artifacts=(
            ArtifactRef(
                snapshot_id=snapshot_id,
                kind=EvidenceKind.AX_TREE,
                sha256=digest,
                media_type='application/json',
                size_bytes=1,
                sensitivity=Sensitivity.MODEL_SAFE,
            ),
        ),
        capabilities=(CaptureCapability(kind=EvidenceKind.AX_TREE, available=True),),
    )


def _region(snapshot_id: str, digest: str, locator: str) -> RegionRef:
    return RegionRef(
        snapshot_id=snapshot_id,
        artifact_sha256=digest,
        modality=EvidenceKind.AX_TREE,
        locator=locator,
    )


def _target(snapshot_id: str, digest: str, role: str, name: str) -> ElementRef:
    return ElementRef(
        snapshot_id=snapshot_id,
        evidence=(_region(snapshot_id, digest, f'ax:{role}/{name}'),),
        semantic_role=role,
        accessible_name_hash=accessible_name_digest(name),
    )


def _receipt(
    *,
    before: CaptureRef,
    after: CaptureRef,
    action: ActionSpec,
    assertion_id: str,
    assertion_evidence: RegionRef,
) -> TransitionReceipt:
    targeted = action.target is not None
    return TransitionReceipt(
        before=before,
        action=action,
        freshness=FreshnessStatus.FRESH,
        resolution=ResolutionEvidence(
            status=ResolutionStatus.UNIQUE if targeted else ResolutionStatus.NOT_REQUIRED,
            candidate_count=1 if targeted else 0,
        ),
        policy=PolicyEvidence(
            status=PolicyStatus.ALLOWED,
            policy_version=ADAPTER_POLICY_VERSION,
            rule_id='safe-action',
        ),
        dispatch=DispatchEvidence(status=DispatchStatus.DISPATCHED, adapter_code='test'),
        settlement=SettlementStatus.SETTLED,
        settlement_observations=(
            SettlementObservation(signal=SettlementSignal.DOM_QUIET, supported=True, satisfied=True),
        ),
        assertions=(
            AssertionResult(
                assertion_id=assertion_id,
                status=AssertionStatus.PASSED,
                evidence=(assertion_evidence,),
            ),
        ),
        after=after,
        outcome=OutcomeStatus.SUCCESS,
        redaction_version='test-v1',
        timing=ReceiptTiming(
            started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            finished_at=datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
        ),
    )


def _episode() -> ActionEpisode:
    s0_snapshot = _source_snapshot('s0', _SHA_A)
    s1_snapshot = _source_snapshot('s1', _SHA_B, 's0')
    s2_snapshot = _source_snapshot('s2', _SHA_A, 's1')
    s0 = capture_ref_for(s0_snapshot)
    s1 = capture_ref_for(s1_snapshot)
    s2 = capture_ref_for(s2_snapshot)
    film_after = _region('s1', _SHA_B, 'ax:link/film')
    person_after = _region('s2', _SHA_A, 'ax:link/person')
    navigate = _receipt(
        before=s0,
        after=s1,
        action=ActionSpec(
            kind=ActionKind.NAVIGATE,
            effect=EffectClass.OBSERVATION,
            url='https://www.imdb.com/find/?q=once+upon+a+time+in+hollywood',
        ),
        assertion_id='film-result-visible',
        assertion_evidence=film_after,
    )
    click = _receipt(
        before=s1,
        after=s2,
        action=ActionSpec(
            kind=ActionKind.CLICK,
            effect=EffectClass.OBSERVATION,
            target=_target('s1', _SHA_B, 'link', _FILM),
        ),
        assertion_id='person-link-visible',
        assertion_evidence=person_after,
    )
    return ActionEpisode(
        episode_id='imdb-discovery',
        snapshots=(s0_snapshot, s1_snapshot, s2_snapshot),
        steps=(
            ActionEpisodeStep(
                receipt=navigate,
                expect=ReplayExpectation(
                    assertion_id='film-result-visible',
                    target=ReplayTargetSignature(
                        semantic_role='link',
                        accessible_name_hash=accessible_name_digest(_FILM),
                        source_evidence=film_after,
                    ),
                ),
            ),
            ActionEpisodeStep(
                receipt=click,
                expect=ReplayExpectation(
                    assertion_id='person-link-visible',
                    target=ReplayTargetSignature(
                        semantic_role='link',
                        accessible_name_hash=accessible_name_digest(_PERSON),
                        source_evidence=person_after,
                    ),
                ),
            ),
        ),
    )


class FakeTab:
    def __init__(self, *, drift: bool = False, ambiguous_film: bool = False) -> None:
        self.stage = 'home'
        self.drift = drift
        self.ambiguous_film = ambiguous_film
        self.calls: list[tuple[str, ...]] = []

    def stage_nodes(self) -> list[dict[str, Any]]:
        names = {'home': [], 'results': [_FILM], 'film': [] if self.drift else [_PERSON]}[self.stage]
        return [{'role': {'value': 'link'}, 'name': {'value': item}} for item in names]

    async def goto(self, url: str, timeout: float = 30.0) -> object:
        self.calls.append(('goto', url))
        self.stage = 'results'
        return object()

    async def url(self) -> str | None:
        return f'https://www.imdb.com/{self.stage}'

    async def query_ax_tree(self, role: str | None = None, name: str | None = None) -> list[dict[str, Any]]:
        self.calls.append(('query_ax_tree', role or ''))
        names = [str(item['name']['value']) for item in self.stage_nodes()]
        if self.stage == 'results' and self.ambiguous_film:
            names = [_FILM, _FILM]
        return [
            {'role': {'value': 'link'}, 'name': {'value': item}} for item in names if role is None or role == 'link'
        ]

    async def click_by_role(self, role: str, name: str, nth: int = 0) -> None:
        self.calls.append(('click_by_role', role, name, str(nth)))
        self.stage = 'film'

    async def wait_for_network_idle(self, timeout: float = 30.0) -> str | None:
        self.calls.append(('wait_for_network_idle',))
        return 'networkIdle'

    def expect_response(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError('this replay does not declare response capture')


class FakeReplayCapture:
    def __init__(self, tab: FakeTab, *, duplicate_name_other_role: bool = False) -> None:
        self.tab = tab
        self.duplicate_name_other_role = duplicate_name_other_role
        self.count = 0
        self.snapshots: dict[str, ObservationSnapshot] = {}
        self.nodes: dict[str, list[dict[str, Any]]] = {}

    async def capture(self, *, parent_snapshot_id: str | None = None) -> ObservationSnapshot:
        self.count += 1
        snapshot_id = f'r{self.count}'
        digest = hashlib.sha256(f'{snapshot_id}:{self.tab.stage}'.encode()).hexdigest()
        snapshot = ObservationSnapshot(
            run_id='replay-run',
            episode_id='replay-episode',
            snapshot_id=snapshot_id,
            parent_snapshot_id=parent_snapshot_id,
            captured_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            requested_profile=CaptureProfile.BROWSER_HEADLESS,
            artifacts=(
                ArtifactRef(
                    snapshot_id=snapshot_id,
                    kind=EvidenceKind.AX_TREE,
                    sha256=digest,
                    media_type='application/json',
                    size_bytes=1,
                    sensitivity=Sensitivity.MODEL_SAFE,
                ),
            ),
            capabilities=(CaptureCapability(kind=EvidenceKind.AX_TREE, available=True),),
        )
        self.snapshots[snapshot_id] = snapshot
        self.nodes[snapshot_id] = self.tab.stage_nodes()
        if self.duplicate_name_other_role and self.tab.stage == 'results':
            self.nodes[snapshot_id].append({'role': {'value': 'StaticText'}, 'name': {'value': _FILM}})
        return snapshot

    def snapshot_for(self, snapshot_id: str) -> ObservationSnapshot:
        return self.snapshots[snapshot_id]

    def ax_nodes_for(self, snapshot_id: str) -> list[dict[str, Any]]:
        return self.nodes[snapshot_id]


def test_episode_is_deterministic_and_requires_contiguous_success() -> None:
    episode = _episode()
    assert episode.canonical_json() == episode.canonical_json()
    assert len(episode.fingerprint) == 64

    first, second = episode.steps
    broken_before = second.receipt.before.model_copy(update={'snapshot_id': 'foreign'})
    broken_receipt = second.receipt.model_copy(update={'before': broken_before})
    with pytest.raises(ValidationError, match='contiguous'):
        ActionEpisode(
            episode_id='imdb-discovery',
            snapshots=episode.snapshots,
            steps=(first, second.model_copy(update={'receipt': broken_receipt})),
        )


def test_episode_and_plan_reject_unknown_schema_versions() -> None:
    episode = _episode()
    episode_payload = episode.model_dump(mode='json')
    episode_payload['schema_version'] = 'future-version'
    with pytest.raises(ValidationError):
        ActionEpisode.model_validate(episode_payload)

    plan = compile_action_episode(episode)
    plan_payload = plan.model_dump(mode='json')
    plan_payload['schema_version'] = 'future-version'
    with pytest.raises(ValidationError):
        type(plan).model_validate(plan_payload)


def test_builder_records_discovery_edges_as_they_complete() -> None:
    source = _episode()
    builder = ActionEpisodeBuilder(episode_id=source.episode_id, initial=source.snapshots[0])
    for step, after in zip(source.steps, source.snapshots[1:], strict=True):
        builder.append(receipt=step.receipt, after=after, expect=step.expect)

    assert builder.build() == source


def test_compiler_preserves_provenance_without_raw_selector_identity() -> None:
    episode = _episode()
    plan = compile_action_episode(episode)

    assert plan.source_episode_fingerprint == episode.fingerprint
    assert [step.kind for step in plan.steps] == [ActionKind.NAVIGATE, ActionKind.CLICK]
    assert plan.steps[1].target is not None
    assert plan.steps[1].target.accessible_name_hash == accessible_name_digest(_FILM)
    assert 'selector' not in plan.model_dump_json()
    assert [step.source_receipt_fingerprint for step in plan.steps] == [
        source.receipt.fingerprint for source in episode.steps
    ]


def test_compiler_rejects_click_without_rebindable_ax_signature() -> None:
    episode = _episode()
    click = episode.steps[1]
    assert click.receipt.action.target is not None
    unsafe_target = click.receipt.action.target.model_copy(update={'accessible_name_hash': None})
    unsafe_action = click.receipt.action.model_copy(update={'target': unsafe_target})
    unsafe_receipt = click.receipt.model_copy(update={'action': unsafe_action})
    unsafe_episode = episode.model_copy(
        update={'steps': (episode.steps[0], click.model_copy(update={'receipt': unsafe_receipt}))}
    )

    with pytest.raises(ActionReplayCompileError, match='rebindable'):
        compile_action_episode(unsafe_episode)


@pytest.mark.asyncio
async def test_episode_and_plan_round_trip_through_shared_sqlite(tmp_path) -> None:
    episode = _episode()
    plan = compile_action_episode(episode)
    async with ActionEpisodeStore(database_url=tmp_path / 'yosoi.sqlite3') as store:
        await store.save_episode(episode)
        await store.save_plan(plan)
        restored_episode = await store.load_episode(episode.fingerprint)
        restored_plan = await store.load_plan(plan.plan_id)

    assert restored_episode == episode
    assert restored_plan == plan


@pytest.mark.asyncio
async def test_fresh_session_replay_is_llm_free_and_emits_new_receipts() -> None:
    episode = _episode()
    plan = compile_action_episode(episode)
    tab = FakeTab()
    capture = FakeReplayCapture(tab)
    initial = await capture.capture()
    executor = ActionReplayExecutor(
        tab=tab,
        capture=capture,
        redaction_version='test-v1',
        adapter_errors=(RuntimeError, OSError, TimeoutError),
    )

    replay = await executor.replay(plan, initial=initial)

    assert replay.status is ReplayRunStatus.COMPLETED
    assert len(replay.receipts) == 2
    assert replay.final_capture == replay.receipts[-1].after
    assert all(receipt.outcome is OutcomeStatus.SUCCESS for receipt in replay.receipts)
    assert {receipt.fingerprint for receipt in replay.receipts}.isdisjoint(
        {step.receipt.fingerprint for step in episode.steps}
    )
    assert ('click_by_role', 'link', _FILM, '0') in tab.calls


@pytest.mark.asyncio
async def test_postcondition_identity_includes_ax_role() -> None:
    plan = compile_action_episode(_episode())
    tab = FakeTab()
    capture = FakeReplayCapture(tab, duplicate_name_other_role=True)
    initial = await capture.capture()
    executor = ActionReplayExecutor(
        tab=tab,
        capture=capture,
        redaction_version='test-v1',
        adapter_errors=(RuntimeError, OSError, TimeoutError),
    )

    replay = await executor.replay(plan, initial=initial)

    assert replay.status is ReplayRunStatus.COMPLETED


@pytest.mark.asyncio
async def test_policy_version_drift_stops_before_browser_calls() -> None:
    plan = compile_action_episode(_episode()).model_copy(update={'policy_version': 'old-policy'})
    tab = FakeTab()
    capture = FakeReplayCapture(tab)
    initial = await capture.capture()
    executor = ActionReplayExecutor(
        tab=tab,
        capture=capture,
        redaction_version='test-v1',
        adapter_errors=(RuntimeError, OSError, TimeoutError),
    )

    replay = await executor.replay(plan, initial=initial)

    assert replay.status is ReplayRunStatus.DRIFTED
    assert replay.receipts == ()
    assert tab.calls == []


@pytest.mark.asyncio
async def test_missing_fresh_ax_artifact_reports_drift_before_dispatch() -> None:
    compiled = compile_action_episode(_episode())
    plan = compiled.model_copy(update={'steps': (compiled.steps[1],)})
    tab = FakeTab()
    capture = FakeReplayCapture(tab)
    initial = (await capture.capture()).model_copy(update={'artifacts': ()})
    executor = ActionReplayExecutor(
        tab=tab,
        capture=capture,
        redaction_version='test-v1',
        adapter_errors=(RuntimeError, OSError, TimeoutError),
    )

    replay = await executor.replay(plan, initial=initial)

    assert replay.status is ReplayRunStatus.DRIFTED
    assert replay.receipts == ()
    assert replay.failed_step_id == plan.steps[0].step_id
    assert tab.calls == []


@pytest.mark.asyncio
async def test_replay_never_dispatches_an_ambiguous_rebound_target() -> None:
    plan = compile_action_episode(_episode())
    tab = FakeTab(ambiguous_film=True)
    capture = FakeReplayCapture(tab)
    initial = await capture.capture()
    executor = ActionReplayExecutor(
        tab=tab,
        capture=capture,
        redaction_version='test-v1',
        adapter_errors=(RuntimeError, OSError, TimeoutError),
    )

    replay = await executor.replay(plan, initial=initial)

    assert replay.status is ReplayRunStatus.DRIFTED
    assert replay.failed_step_id == 'step-2'
    assert replay.receipts[-1].outcome is OutcomeStatus.AMBIGUOUS
    assert not any(call[0] == 'click_by_role' for call in tab.calls)


@pytest.mark.asyncio
async def test_replay_stops_and_reports_drift_when_postcondition_disappears() -> None:
    plan = compile_action_episode(_episode())
    tab = FakeTab(drift=True)
    capture = FakeReplayCapture(tab)
    initial = await capture.capture()
    executor = ActionReplayExecutor(
        tab=tab,
        capture=capture,
        redaction_version='test-v1',
        adapter_errors=(RuntimeError, OSError, TimeoutError),
    )

    replay = await executor.replay(plan, initial=initial)

    assert replay.status is ReplayRunStatus.DRIFTED
    assert replay.failed_step_id == 'step-2'
    assert replay.receipts[-1].outcome is OutcomeStatus.FAILED
    assert replay.receipts[-1].error_code is not None
