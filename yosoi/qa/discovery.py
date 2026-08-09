"""Bounded, provider-neutral agent discovery over immutable QA indexes.

The model may choose only from evidence references rendered for the current snapshot. Browser
ownership, target binding, dispatch, capture, and deterministic verification remain behind an
injected environment; successful receipts are appended to the A3 episode ledger immediately.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Annotated, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from yosoi.a3.compiler import ActionEpisodeBuilder
from yosoi.a3.models import (
    ActionEpisode,
    AxPropertyExpectation,
    ReplayExpectation,
    ReplayTargetSignature,
)
from yosoi.actions.adapters.voidcrawl import accessible_name_digest, capture_ref_for
from yosoi.actions.models import (
    ActionKind,
    ActionSpec,
    AssertionStatus,
    CaptureRef,
    EffectClass,
    ElementRef,
    OutcomeStatus,
    TransitionReceipt,
)
from yosoi.observations.index.inspect import InspectionResult
from yosoi.observations.models.artifact import EvidenceKind
from yosoi.observations.models.snapshot import ObservationSnapshot
from yosoi.observations.models.view import RegionRef
from yosoi.qa.actions import QAActionCapabilities
from yosoi.qa.index import IndexSession
from yosoi.qa.tools import InspectArgs, OverviewArgs

_SAFE_CODE = r'^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$'


class DiscoveryLimits(BaseModel):
    """Hard limits applied by the controller, never delegated to the model."""

    model_config = ConfigDict(frozen=True, extra='forbid', strict=True)

    max_turns: int = Field(default=8, ge=1, le=32)
    max_tool_calls: int = Field(default=24, ge=2, le=96)
    max_actions: int = Field(default=7, ge=1, le=31)
    overview_tokens: int = Field(default=1_000, ge=1, le=3_000)


class AxPostconditionIntent(BaseModel):
    """Explicit deterministic condition predicted before an action is dispatched."""

    model_config = ConfigDict(frozen=True, extra='forbid', strict=True)

    assertion_id: str = Field(pattern=_SAFE_CODE)
    semantic_role: str = Field(min_length=1, max_length=64, pattern=r'^[a-zA-Z][a-zA-Z0-9_-]{0,63}$')
    accessible_name: str = Field(min_length=1, max_length=512)
    properties: tuple[AxPropertyExpectation, ...] = Field(default=(), max_length=8)


class NavigateDecision(BaseModel):
    """Navigate to one policy-validated HTTPS URL without guessing unseen AX labels."""

    model_config = ConfigDict(frozen=True, extra='forbid', strict=True)

    decision: Literal['navigate'] = 'navigate'
    url: str = Field(min_length=1, max_length=2_048)


class ClickDecision(BaseModel):
    """Activate one snapshot-local ordinal included in the current bounded overview."""

    model_config = ConfigDict(frozen=True, extra='forbid', strict=True)

    decision: Literal['click'] = 'click'
    snapshot_id: str = Field(min_length=1, max_length=256)
    ordinal: int = Field(ge=0)
    expect: AxPostconditionIntent


class CompleteDecision(BaseModel):
    """Stop after the goal has been satisfied by already-proven transitions."""

    model_config = ConfigDict(frozen=True, extra='forbid', strict=True)

    decision: Literal['complete'] = 'complete'


DiscoveryDecision = Annotated[NavigateDecision | ClickDecision | CompleteDecision, Field(discriminator='decision')]
_DECISION_ADAPTER = TypeAdapter(DiscoveryDecision)


class DiscoveryTurn(BaseModel):
    """Bounded model input derived from one immutable observation index."""

    model_config = ConfigDict(frozen=True, extra='forbid', strict=True)

    goal: str = Field(min_length=1, max_length=2_000)
    turn: int = Field(ge=1)
    snapshot_id: str = Field(min_length=1, max_length=256)
    overview: str
    available_refs: tuple[RegionRef, ...]
    receipt_fingerprints: tuple[str, ...] = ()
    allowed_navigation_urls: tuple[str, ...] = Field(default=(), max_length=8)


@runtime_checkable
class DiscoveryAgent(Protocol):
    """Provider adapter that returns one closed decision per bounded turn."""

    async def decide(self, turn: DiscoveryTurn) -> DiscoveryDecision:
        """Choose one action or declare the proven goal complete."""
        ...


@dataclass(frozen=True)
class DiscoveryState:
    """Controller state for one exact capture and its matching index session."""

    capture: CaptureRef
    snapshot: ObservationSnapshot
    index: IndexSession
    allowed_navigation_urls: tuple[str, ...] = ()


@dataclass(frozen=True)
class DiscoveryTransition:
    """Authoritative environment result after deterministic action verification."""

    receipt: TransitionReceipt
    after: ObservationSnapshot
    next_index: IndexSession


@runtime_checkable
class DiscoveryEnvironment(Protocol):
    """Injected retained-session boundary; it never belongs to the model."""

    async def capabilities(self) -> QAActionCapabilities:
        """Declare complete action/index/assertion readiness before the model runs."""
        ...

    async def initial_state(self) -> DiscoveryState:
        """Return the already-captured initial state and index."""
        ...

    async def bind_target(self, state: DiscoveryState, inspection: InspectionResult) -> ElementRef:
        """Bind inspected current evidence into one capture-bound safe target."""
        ...

    async def execute(
        self, state: DiscoveryState, action: ActionSpec, expect: AxPostconditionIntent | None
    ) -> DiscoveryTransition:
        """Execute through the action runtime and return its receipt plus indexed after-state."""
        ...


class DiscoveryRunStatus(str, Enum):
    """Normalized terminal state for one bounded discovery attempt."""

    COMPLETED = 'completed'
    REFUSED = 'refused'
    DRIFTED = 'drifted'
    EXHAUSTED = 'exhausted'


class DiscoveryRun(BaseModel):
    """Audit envelope retaining receipts even when no episode is promoted."""

    model_config = ConfigDict(frozen=True, extra='forbid', strict=True)

    status: DiscoveryRunStatus
    turns: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    receipts: tuple[TransitionReceipt, ...] = ()
    episode: ActionEpisode | None = None
    reason_code: str | None = Field(default=None, pattern=_SAFE_CODE)

    @model_validator(mode='after')
    def _coherent(self) -> DiscoveryRun:
        if self.status is DiscoveryRunStatus.COMPLETED:
            if self.episode is None or not self.receipts or self.reason_code is not None:
                raise ValueError('completed discovery requires a promoted episode and receipts')
        elif self.episode is not None or self.reason_code is None:
            raise ValueError('non-completed discovery requires a reason and cannot promote an episode')
        return self


class IndexedDiscoveryHarness:
    """Run a model under index, action, evidence, and turn boundaries."""

    def __init__(
        self, *, agent: DiscoveryAgent, environment: DiscoveryEnvironment, limits: DiscoveryLimits | None = None
    ) -> None:
        """Bind one provider adapter and one retained-session environment."""
        self._agent = agent
        self._environment = environment
        self._limits = limits or DiscoveryLimits()

    async def run(self, goal: str) -> DiscoveryRun:  # noqa: C901 — linear safety gate audit
        """Explore until complete, drift, refusal, or a hard budget is reached."""
        capabilities = await self._environment.capabilities()
        if not all(
            (
                capabilities.index,
                capabilities.capture,
                capabilities.actions,
                capabilities.deterministic_assertions,
                capabilities.a3_recording,
            )
        ):
            return self._terminal(DiscoveryRunStatus.REFUSED, 0, 0, (), 'capability_unavailable')
        state = await self._environment.initial_state()
        if capture_ref_for(state.snapshot) != state.capture:
            return self._terminal(DiscoveryRunStatus.REFUSED, 0, 0, (), 'initial_capture_mismatch')
        builder = ActionEpisodeBuilder(episode_id=state.snapshot.episode_id, initial=state.snapshot)
        recorded_steps = 0
        receipts: list[TransitionReceipt] = []
        tool_calls = 0
        for turn_number in range(1, self._limits.max_turns + 1):
            if tool_calls + 2 > self._limits.max_tool_calls:
                return self._terminal(
                    DiscoveryRunStatus.EXHAUSTED, turn_number - 1, tool_calls, receipts, 'tool_budget'
                )
            try:
                overview = await state.index.overview(
                    OverviewArgs(snapshot_id=state.snapshot.snapshot_id, token_budget=self._limits.overview_tokens)
                )
            except (KeyError, ValueError, RuntimeError, PermissionError, NotImplementedError):
                return self._terminal(
                    DiscoveryRunStatus.REFUSED, turn_number, tool_calls + 1, receipts, 'index_unavailable'
                )
            tool_calls += 1
            try:
                decision = _DECISION_ADAPTER.validate_python(
                    await self._agent.decide(
                        DiscoveryTurn(
                            goal=goal,
                            turn=turn_number,
                            snapshot_id=state.snapshot.snapshot_id,
                            overview=overview.text,
                            available_refs=overview.included_refs,
                            receipt_fingerprints=tuple(item.fingerprint for item in receipts),
                            allowed_navigation_urls=state.allowed_navigation_urls,
                        )
                    )
                )
            except (ValidationError, TypeError, ValueError):
                return self._terminal(
                    DiscoveryRunStatus.REFUSED, turn_number, tool_calls + 1, receipts, 'invalid_decision'
                )
            tool_calls += 1
            if isinstance(decision, CompleteDecision):
                if not receipts:
                    return self._terminal(
                        DiscoveryRunStatus.REFUSED, turn_number, tool_calls, receipts, 'empty_completion'
                    )
                if not recorded_steps:
                    return self._terminal(
                        DiscoveryRunStatus.REFUSED, turn_number, tool_calls, receipts, 'no_recordable_steps'
                    )
                return DiscoveryRun(
                    status=DiscoveryRunStatus.COMPLETED,
                    turns=turn_number,
                    tool_calls=tool_calls,
                    receipts=tuple(receipts),
                    episode=builder.build(),
                )
            if isinstance(decision, NavigateDecision):
                if decision.url not in state.allowed_navigation_urls:
                    return self._terminal(
                        DiscoveryRunStatus.REFUSED, turn_number, tool_calls, receipts, 'navigation_not_allowed'
                    )
                try:
                    action = ActionSpec(kind=ActionKind.NAVIGATE, effect=EffectClass.OBSERVATION, url=decision.url)
                except ValueError:
                    return self._terminal(
                        DiscoveryRunStatus.REFUSED, turn_number, tool_calls, receipts, 'invalid_action'
                    )
                expect = None
            else:
                if decision.snapshot_id != state.snapshot.snapshot_id:
                    return self._terminal(
                        DiscoveryRunStatus.REFUSED, turn_number, tool_calls, receipts, 'unseen_target'
                    )
                if tool_calls + 1 > self._limits.max_tool_calls:
                    return self._terminal(
                        DiscoveryRunStatus.EXHAUSTED, turn_number, tool_calls, receipts, 'tool_budget'
                    )
                try:
                    inspected = await state.index.inspect(
                        InspectArgs(snapshot_id=decision.snapshot_id, ordinal=decision.ordinal)
                    )
                    if inspected.ref not in overview.included_refs:
                        return self._terminal(
                            DiscoveryRunStatus.REFUSED, turn_number, tool_calls + 1, receipts, 'unseen_target'
                        )
                    target = await self._environment.bind_target(state, inspected)
                    action = ActionSpec(kind=ActionKind.CLICK, effect=EffectClass.REVERSIBLE_UI, target=target)
                except (KeyError, LookupError, ValueError, PermissionError, NotImplementedError):
                    return self._terminal(
                        DiscoveryRunStatus.REFUSED, turn_number, tool_calls + 1, receipts, 'target_unbindable'
                    )
                tool_calls += 1
                if target.snapshot_id != state.capture.snapshot_id or inspected.ref not in target.evidence:
                    return self._terminal(
                        DiscoveryRunStatus.REFUSED, turn_number, tool_calls, receipts, 'foreign_target'
                    )
                expect = decision.expect
            if len(receipts) >= self._limits.max_actions:
                return self._terminal(DiscoveryRunStatus.EXHAUSTED, turn_number, tool_calls, receipts, 'action_budget')
            transition = await self._environment.execute(state, action, expect)
            receipt = transition.receipt
            if receipt.before != state.capture or receipt.action != action:
                return self._terminal(DiscoveryRunStatus.REFUSED, turn_number, tool_calls, receipts, 'receipt_mismatch')
            receipts.append(receipt)
            if receipt.outcome is not OutcomeStatus.SUCCESS or receipt.after is None:
                return self._terminal(
                    DiscoveryRunStatus.DRIFTED, turn_number, tool_calls, receipts, 'transition_unproven'
                )
            if capture_ref_for(transition.after) != receipt.after:
                return self._terminal(
                    DiscoveryRunStatus.REFUSED, turn_number, tool_calls, receipts, 'after_capture_mismatch'
                )
            if expect is not None:
                assertions = [item for item in receipt.assertions if item.assertion_id == expect.assertion_id]
                if len(assertions) != 1 or assertions[0].status is not AssertionStatus.PASSED:
                    return self._terminal(
                        DiscoveryRunStatus.DRIFTED, turn_number, tool_calls, receipts, 'postcondition_unproven'
                    )
                evidence = [ref for ref in assertions[0].evidence if ref.modality is EvidenceKind.AX_TREE]
                if len(evidence) != 1 or evidence[0].snapshot_id != transition.after.snapshot_id:
                    return self._terminal(
                        DiscoveryRunStatus.REFUSED, turn_number, tool_calls, receipts, 'postcondition_evidence'
                    )
            next_status = await transition.next_index.status()
            if next_status.snapshot_ids != (transition.after.snapshot_id,):
                return self._terminal(
                    DiscoveryRunStatus.REFUSED, turn_number, tool_calls, receipts, 'next_index_mismatch'
                )
            if expect is None:
                if recorded_steps:
                    return self._terminal(
                        DiscoveryRunStatus.REFUSED, turn_number, tool_calls, receipts, 'unrecorded_mid_episode'
                    )
                builder = ActionEpisodeBuilder(
                    episode_id=transition.after.episode_id,
                    initial=transition.after,
                )
            else:
                replay_expectation = ReplayExpectation(
                    assertion_id=expect.assertion_id,
                    target=ReplayTargetSignature(
                        semantic_role=expect.semantic_role,
                        accessible_name_hash=accessible_name_digest(expect.accessible_name),
                        source_evidence=evidence[0],
                    ),
                    properties=expect.properties,
                )
                builder.append(receipt=receipt, after=transition.after, expect=replay_expectation)
                recorded_steps += 1
            state = DiscoveryState(capture=receipt.after, snapshot=transition.after, index=transition.next_index)
        return self._terminal(DiscoveryRunStatus.EXHAUSTED, self._limits.max_turns, tool_calls, receipts, 'turn_budget')

    @staticmethod
    def _terminal(status: DiscoveryRunStatus, turns: int, tool_calls: int, receipts, reason: str) -> DiscoveryRun:
        return DiscoveryRun(
            status=status,
            turns=turns,
            tool_calls=tool_calls,
            receipts=tuple(receipts),
            reason_code=reason,
        )


__all__ = [
    'AxPostconditionIntent',
    'ClickDecision',
    'CompleteDecision',
    'DiscoveryAgent',
    'DiscoveryDecision',
    'DiscoveryEnvironment',
    'DiscoveryLimits',
    'DiscoveryRun',
    'DiscoveryRunStatus',
    'DiscoveryState',
    'DiscoveryTransition',
    'DiscoveryTurn',
    'IndexedDiscoveryHarness',
    'NavigateDecision',
]
