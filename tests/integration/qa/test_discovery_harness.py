"""Deterministic indexed discovery loop with no model, browser, or network."""

from __future__ import annotations

import json
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from yosoi.actions.adapters.voidcrawl import ADAPTER_POLICY_VERSION, accessible_name_digest, capture_ref_for
from yosoi.actions.models import (
    ActionSpec,
    AssertionResult,
    AssertionStatus,
    DispatchEvidence,
    DispatchStatus,
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
from yosoi.observations.artifacts import MemoryArtifactStore
from yosoi.observations.index.compiler import ObservationIndexCompiler
from yosoi.observations.models import AxNode, AxSnapshot, CaptureProfile, EvidenceKind, ObservationSnapshot
from yosoi.observations.models.ax import serialize_ax_snapshot
from yosoi.observations.pruning import AxPruner, PruningInput, PruningPolicy
from yosoi.qa.actions import QAActionCapabilities
from yosoi.qa.discovery import (
    AxPostconditionIntent,
    ClickDecision,
    CompleteDecision,
    DiscoveryLimits,
    DiscoveryRunStatus,
    DiscoveryState,
    DiscoveryTransition,
    IndexedDiscoveryHarness,
    NavigateDecision,
)
from yosoi.qa.index import index

_FILM = 'Once Upon a Time in... Hollywood'
_PERSON = 'Brad Pitt'
_SEARCH = 'https://www.imdb.com/find/?q=Once%20Upon%20a%20Time%20in%20Hollywood&s=tt'
_CAPTURED_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)
_FIXTURE = Path(__file__).parents[2] / 'fixtures/qa_discovery/imdb_like/session.json'
_LUNA_AUDIT = Path(__file__).parents[2] / '../data/evals/cas273-luna-discovery.json'


class ScriptedAgent:
    def __init__(self, decisions: list[Any]) -> None:
        self.decisions = deque(decisions)
        self.turns = []

    async def decide(self, turn):
        self.turns.append(turn)
        decision = self.decisions.popleft()
        if isinstance(decision, BaseException):
            raise decision
        return decision


class FixtureEnvironment:
    def __init__(self, states: list[DiscoveryState], targets: dict[object, tuple[str, str]]) -> None:
        self.states = states
        self.targets = targets
        self.position = 0
        self.executed: list[ActionSpec] = []

    async def capabilities(self) -> QAActionCapabilities:
        return QAActionCapabilities(
            index=True,
            capture=True,
            actions=True,
            deterministic_assertions=True,
            a3_recording=True,
            operations=('capabilities', 'status', 'overview', 'inspect', 'execute'),
        )

    async def initial_state(self) -> DiscoveryState:
        return self.states[0]

    async def bind_target(self, state, inspection) -> ElementRef:
        role, name = self.targets[inspection.ref]
        return ElementRef(
            snapshot_id=state.snapshot.snapshot_id,
            evidence=(inspection.ref,),
            semantic_role=role,
            accessible_name_hash=accessible_name_digest(name),
        )

    async def execute(self, state, action, expect) -> DiscoveryTransition:
        self.executed.append(action)
        following = self.states[self.position + 1]
        self.position += 1
        assertion_id = expect.assertion_id if expect is not None else 'navigation-complete'
        role = expect.semantic_role if expect is not None else 'link'
        name = expect.accessible_name if expect is not None else _FILM
        evidence = _find_ref(following, self.targets, role, name)
        targeted = action.target is not None
        receipt = TransitionReceipt(
            before=state.capture,
            action=action,
            freshness=FreshnessStatus.FRESH,
            resolution=ResolutionEvidence(
                status=ResolutionStatus.UNIQUE if targeted else ResolutionStatus.NOT_REQUIRED,
                candidate_count=1 if targeted else 0,
            ),
            policy=PolicyEvidence(
                status=PolicyStatus.ALLOWED,
                policy_version=ADAPTER_POLICY_VERSION,
                rule_id='fixture-safe-action',
            ),
            dispatch=DispatchEvidence(status=DispatchStatus.DISPATCHED, adapter_code='fixture'),
            settlement=SettlementStatus.SETTLED,
            settlement_observations=(
                SettlementObservation(signal=SettlementSignal.DOM_QUIET, supported=True, satisfied=True),
            ),
            assertions=(
                AssertionResult(
                    assertion_id=assertion_id,
                    status=AssertionStatus.PASSED,
                    evidence=(evidence,),
                ),
            ),
            after=following.capture,
            outcome=OutcomeStatus.SUCCESS,
            redaction_version='fixture-v1',
            timing=ReceiptTiming(started_at=_CAPTURED_AT, finished_at=_CAPTURED_AT),
        )
        return DiscoveryTransition(receipt=receipt, after=following.snapshot, next_index=following.index)


class DisabledEnvironment(FixtureEnvironment):
    async def capabilities(self) -> QAActionCapabilities:
        return QAActionCapabilities(index=True, capture=True)


async def _fixture() -> tuple[list[DiscoveryState], dict[object, tuple[str, str]]]:
    store = MemoryArtifactStore()
    fixture = json.loads(_FIXTURE.read_text())
    states = []
    targets = {}
    for definition in fixture['states']:
        snapshot_id = definition['snapshot_id']
        parent = definition['parent_snapshot_id']
        facts = tuple((node['role'], node['name']) for node in definition['nodes'])
        child_ids = tuple(f'n{position}' for position in range(1, len(facts)))
        nodes = [AxNode(node_id='root', role='document', name=facts[0][1], child_ids=child_ids)]
        nodes.extend(
            AxNode(node_id=f'n{position}', parent_id='root', role=role, name=name)
            for position, (role, name) in enumerate(facts[1:], 1)
        )
        data = serialize_ax_snapshot(AxSnapshot(snapshot_id=snapshot_id, root_id='root', nodes=tuple(nodes)))
        artifact = store.put(
            snapshot_id=snapshot_id,
            kind=EvidenceKind.AX_TREE,
            media_type='application/json',
            data=data,
        )
        snapshot = ObservationSnapshot(
            run_id='fixture-run',
            episode_id='fixture-episode',
            snapshot_id=snapshot_id,
            parent_snapshot_id=parent,
            captured_at=_CAPTURED_AT,
            requested_profile=CaptureProfile.BROWSER_HEADLESS,
            artifacts=(artifact,),
        )
        view = AxPruner().prune(PruningInput(source=artifact, data=data), PruningPolicy())
        observation_index = ObservationIndexCompiler().compile(snapshot, (view,))
        session = await index(store=store, snapshot=snapshot, observation_index=observation_index)
        state = DiscoveryState(
            capture=capture_ref_for(snapshot),
            snapshot=snapshot,
            index=session,
            allowed_navigation_urls=(fixture['safe_navigation_url'],) if snapshot_id == 's0' else (),
        )
        states.append(state)
        for entry in observation_index.entries:
            detail = await session.inspect(_inspect_ref(entry.ref))
            content = detail.content.decode('utf-8')
            for role, name in facts:
                if role in content and name in content:
                    targets[entry.ref] = (role, name)
                    break
    return states, targets


def _inspect_ref(ref):
    from yosoi.qa.tools import InspectArgs

    return InspectArgs(ref=ref)


def _find_ref(state: DiscoveryState, targets, role: str, name: str):
    matches = [
        ref
        for ref, identity in targets.items()
        if ref.snapshot_id == state.snapshot.snapshot_id and identity == (role, name)
    ]
    assert len(matches) == 1
    return matches[0]


async def _ordinal_for(state: DiscoveryState, ref) -> int:
    from yosoi.qa.tools import InspectArgs

    for ordinal in range(32):
        try:
            inspected = await state.index.inspect(InspectArgs(snapshot_id=state.snapshot.snapshot_id, ordinal=ordinal))
        except LookupError:
            continue
        if inspected.ref == ref:
            return ordinal
    raise AssertionError(f'fixture ref {ref!r} has no ordinal')


@pytest.mark.asyncio
async def test_agent_discovers_frozen_journey_using_only_indexed_evidence() -> None:
    states, targets = await _fixture()
    film_ref = _find_ref(states[1], targets, 'link', _FILM)
    person_ref = _find_ref(states[2], targets, 'link', _PERSON)
    agent = ScriptedAgent(
        [
            NavigateDecision(url=_SEARCH),
            ClickDecision(
                snapshot_id='s1',
                ordinal=await _ordinal_for(states[1], film_ref),
                expect=AxPostconditionIntent(
                    assertion_id='film-heading', semantic_role='heading', accessible_name=_FILM
                ),
            ),
            ClickDecision(
                snapshot_id='s2',
                ordinal=await _ordinal_for(states[2], person_ref),
                expect=AxPostconditionIntent(
                    assertion_id='person-heading', semantic_role='heading', accessible_name=_PERSON
                ),
            ),
            CompleteDecision(),
        ]
    )
    environment = FixtureEnvironment(states, targets)

    run = await IndexedDiscoveryHarness(agent=agent, environment=environment).run('Open the film and Brad Pitt')

    assert run.status is DiscoveryRunStatus.COMPLETED
    assert run.episode is not None
    assert len(run.episode.steps) == 2
    assert run.receipts[1:] == tuple(step.receipt for step in run.episode.steps)
    assert run.turns == 4
    assert run.tool_calls == 10
    assert [action.kind.value for action in environment.executed] == ['navigate', 'click', 'click']
    assert all(
        'selector' not in turn.model_dump_json() and 'javascript' not in turn.model_dump_json() for turn in agent.turns
    )


@pytest.mark.asyncio
async def test_navigation_must_match_controller_allowlist_before_dispatch() -> None:
    states, targets = await _fixture()
    environment = FixtureEnvironment(states, targets)

    run = await IndexedDiscoveryHarness(
        agent=ScriptedAgent([NavigateDecision(url='https://www.imdb.com/title/tt7131622/')]),
        environment=environment,
    ).run('Open the film')

    assert run.status is DiscoveryRunStatus.REFUSED
    assert run.reason_code == 'navigation_not_allowed'
    assert environment.executed == []


@pytest.mark.asyncio
async def test_unseen_or_stale_target_refuses_before_dispatch() -> None:
    states, targets = await _fixture()
    stale_ref = _find_ref(states[1], targets, 'link', _FILM)
    agent = ScriptedAgent(
        [
            NavigateDecision(url=_SEARCH),
            ClickDecision(
                snapshot_id='s0',
                ordinal=await _ordinal_for(states[1], stale_ref),
                expect=AxPostconditionIntent(
                    assertion_id='film-heading', semantic_role='heading', accessible_name=_FILM
                ),
            ),
        ]
    )
    environment = FixtureEnvironment(states, targets)

    run = await IndexedDiscoveryHarness(agent=agent, environment=environment).run('Open the film')

    assert run.status is DiscoveryRunStatus.REFUSED
    assert run.reason_code == 'unseen_target'
    assert len(environment.executed) == 1
    assert run.episode is None


@pytest.mark.asyncio
async def test_missing_capabilities_refuse_before_model_or_action() -> None:
    states, targets = await _fixture()
    agent = ScriptedAgent([CompleteDecision()])
    environment = DisabledEnvironment(states, targets)

    run = await IndexedDiscoveryHarness(agent=agent, environment=environment).run('Anything')

    assert run.status is DiscoveryRunStatus.REFUSED
    assert run.reason_code == 'capability_unavailable'
    assert agent.turns == []
    assert environment.executed == []


@pytest.mark.asyncio
async def test_invalid_model_output_refuses_before_dispatch() -> None:
    states, targets = await _fixture()
    agent = ScriptedAgent([{'decision': 'click', 'selector': '#unsafe'}])
    environment = FixtureEnvironment(states, targets)

    run = await IndexedDiscoveryHarness(agent=agent, environment=environment).run('Anything')

    assert run.status is DiscoveryRunStatus.REFUSED
    assert run.reason_code == 'invalid_decision'
    assert environment.executed == []


@pytest.mark.asyncio
async def test_captured_luna_transcript_mints_authoritative_fixture_receipts() -> None:
    states, targets = await _fixture()
    audit = json.loads(_LUNA_AUDIT.resolve().read_text())
    decisions: list[Any] = []
    for event in audit['audit']:
        if event.get('event') != 'decision':
            continue
        params = event['params']
        if event['name'] == 'qa_navigate':
            decisions.append(NavigateDecision(url=params['url']))
        else:
            assertion_id = 'film-heading' if params['snapshot_id'] == 's1' else 'person-heading'
            decisions.append(
                ClickDecision(
                    snapshot_id=params['snapshot_id'],
                    ordinal=params['ordinal'],
                    expect=AxPostconditionIntent(
                        assertion_id=assertion_id,
                        semantic_role=params['expected_role'],
                        accessible_name=params['expected_name'],
                    ),
                )
            )
    decisions.append(CompleteDecision())
    environment = FixtureEnvironment(states, targets)

    run = await IndexedDiscoveryHarness(
        agent=ScriptedAgent(decisions),
        environment=environment,
    ).run('Open the film and Brad Pitt')

    assert run.status is DiscoveryRunStatus.COMPLETED
    assert len(run.receipts) == 3
    assert all(isinstance(receipt, TransitionReceipt) for receipt in run.receipts)
    assert run.episode is not None
    assert len(run.episode.steps) == 2


@pytest.mark.asyncio
async def test_action_budget_stops_without_extra_dispatch() -> None:
    states, targets = await _fixture()
    film_ref = _find_ref(states[1], targets, 'link', _FILM)
    agent = ScriptedAgent(
        [
            NavigateDecision(url=_SEARCH),
            ClickDecision(
                snapshot_id='s1',
                ordinal=await _ordinal_for(states[1], film_ref),
                expect=AxPostconditionIntent(
                    assertion_id='film-heading', semantic_role='heading', accessible_name=_FILM
                ),
            ),
        ]
    )
    environment = FixtureEnvironment(states, targets)

    run = await IndexedDiscoveryHarness(
        agent=agent,
        environment=environment,
        limits=DiscoveryLimits(max_actions=1),
    ).run('Open the film')

    assert run.status is DiscoveryRunStatus.EXHAUSTED
    assert run.reason_code == 'action_budget'
    assert len(environment.executed) == 1
