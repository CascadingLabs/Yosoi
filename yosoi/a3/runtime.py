"""LLM-free fresh-session execution for exact action replay plans."""

from __future__ import annotations

from typing import Any, Protocol

from yosoi.a3.models import (
    ActionReplayPlan,
    ActionReplayRun,
    ActionReplayStep,
    ReplayRunStatus,
    ReplayTargetSignature,
)
from yosoi.actions.adapters.voidcrawl import (
    ADAPTER_POLICY_VERSION,
    AdapterCapabilityPolicy,
    AxEvidenceResolver,
    RetainedBrowserTab,
    RetainedVoidCrawlSession,
    accessible_name_digest,
    capture_ref_for,
    default_adapter_errors,
)
from yosoi.actions.models import (
    ActionKind,
    ActionSpec,
    AssertionResult,
    AssertionStatus,
    ElementRef,
    OutcomeStatus,
)
from yosoi.actions.protocols import SettlementResult
from yosoi.actions.runtime import ActionRuntime
from yosoi.observations.models.artifact import EvidenceKind
from yosoi.observations.models.snapshot import ObservationSnapshot
from yosoi.observations.models.view import RegionRef


class ReplaySnapshotCapture(Protocol):
    """Capture boundary retaining manifests and exact decoded AX evidence."""

    async def capture(self, *, parent_snapshot_id: str | None = ...) -> ObservationSnapshot:
        """Capture one state linked to its optional parent."""
        ...

    def snapshot_for(self, snapshot_id: str) -> ObservationSnapshot:
        """Return the retained manifest for one capture id."""
        ...

    def ax_nodes_for(self, snapshot_id: str) -> list[dict[str, Any]]:
        """Return nodes decoded from that snapshot's exact AX artifact."""
        ...


class AxReplayVerifier:
    """Verify one declared AX postcondition against the live retained tab."""

    def __init__(
        self,
        *,
        tab: RetainedBrowserTab,
        capture: ReplaySnapshotCapture,
        step: ActionReplayStep,
        adapter_errors: tuple[type[BaseException], ...],
    ) -> None:
        """Bind one declared postcondition to the retained capture store."""
        del tab, adapter_errors
        self._capture = capture
        self._step = step

    async def verify(
        self,
        before: object,
        action: ActionSpec,
        after: object,
        settlement: SettlementResult,
    ) -> tuple[AssertionResult, ...]:
        """Require exactly one fresh AX node matching the saved semantic signature."""
        del before, action, settlement
        snapshot_id = getattr(after, 'snapshot_id', None)
        if not isinstance(snapshot_id, str):
            return self._failed('after_capture_unavailable')
        target = self._step.expect.target
        try:
            nodes = self._capture.ax_nodes_for(snapshot_id)
        except (KeyError, ValueError):
            return self._failed('ax_evidence_unavailable')
        matches = [
            node
            for node in nodes
            if _ax_text(node, 'role') == target.semantic_role
            and (name := _ax_text(node, 'name'))
            and accessible_name_digest(name) == target.accessible_name_hash
            and all(_ax_property(node, item.name) == item.value for item in self._step.expect.properties)
        ]
        if len(matches) != 1:
            return self._failed('postcondition_missing' if not matches else 'postcondition_ambiguous')
        snapshot = self._capture.snapshot_for(snapshot_id)
        artifact = _single_ax_artifact(snapshot)
        if artifact is None:
            return self._failed('ax_evidence_unavailable')
        evidence = RegionRef(
            snapshot_id=snapshot_id,
            artifact_sha256=artifact.sha256,
            modality=EvidenceKind.AX_TREE,
            locator=f'ax:role/{target.semantic_role}/name-sha256/{target.accessible_name_hash}',
        )
        return (
            AssertionResult(
                assertion_id=self._step.expect.assertion_id,
                status=AssertionStatus.PASSED,
                evidence=(evidence,),
            ),
        )

    def _failed(self, reason: str) -> tuple[AssertionResult, ...]:
        return (
            AssertionResult(
                assertion_id=self._step.expect.assertion_id,
                status=AssertionStatus.FAILED,
                reason_code=reason,
            ),
        )


class ActionReplayExecutor:
    """Replay an exact plan on one borrowed tab and emit new transition receipts."""

    def __init__(
        self,
        *,
        tab: RetainedBrowserTab,
        capture: ReplaySnapshotCapture,
        redaction_version: str,
        adapter_errors: tuple[type[BaseException], ...] | None = None,
    ) -> None:
        """Bind the one borrowed tab and replay-aware capture boundary."""
        self._tab = tab
        self._capture = capture
        self._redaction_version = redaction_version
        self._adapter_errors = default_adapter_errors() if adapter_errors is None else adapter_errors

    async def replay(self, plan: ActionReplayPlan, *, initial: ObservationSnapshot) -> ActionReplayRun:
        """Execute left-to-right, stopping at the first edge that cannot be freshly proved."""
        if plan.policy_version != ADAPTER_POLICY_VERSION or plan.redaction_version != self._redaction_version:
            return ActionReplayRun(
                plan_id=plan.plan_id,
                status=ReplayRunStatus.DRIFTED,
                receipts=(),
                failed_step_id=plan.steps[0].step_id,
            )
        current = initial
        receipts = []
        for step in plan.steps:
            before = capture_ref_for(current)
            try:
                action = _bind_action(step, current)
            except ReplayDriftError:
                return ActionReplayRun(
                    plan_id=plan.plan_id,
                    status=ReplayRunStatus.DRIFTED,
                    receipts=tuple(receipts),
                    failed_step_id=step.step_id,
                )
            session = RetainedVoidCrawlSession(
                tab=self._tab,
                capture=self._capture,
                active=before,
                adapter_errors=self._adapter_errors,
            )
            runtime = ActionRuntime(
                session=session,
                resolver=AxEvidenceResolver(tab=self._tab, adapter_errors=self._adapter_errors),
                policy=AdapterCapabilityPolicy(tab=self._tab),
                verifier=AxReplayVerifier(
                    tab=self._tab,
                    capture=self._capture,
                    step=step,
                    adapter_errors=self._adapter_errors,
                ),
                redaction_version=self._redaction_version,
            )
            receipt = await runtime.perform(before=before, action=action)
            receipts.append(receipt)
            if receipt.outcome is not OutcomeStatus.SUCCESS or receipt.after is None:
                return ActionReplayRun(
                    plan_id=plan.plan_id,
                    status=ReplayRunStatus.DRIFTED,
                    receipts=tuple(receipts),
                    final_capture=receipt.after,
                    failed_step_id=step.step_id,
                )
            current = self._capture.snapshot_for(receipt.after.snapshot_id)
        return ActionReplayRun(
            plan_id=plan.plan_id,
            status=ReplayRunStatus.COMPLETED,
            receipts=tuple(receipts),
            final_capture=receipts[-1].after,
        )


def _bind_action(step: ActionReplayStep, snapshot: ObservationSnapshot) -> ActionSpec:
    if step.kind is ActionKind.NAVIGATE:
        return ActionSpec(
            kind=step.kind,
            effect=step.effect,
            url=step.url,
            response_expectation=step.response_expectation,
        )
    if step.target is None:
        raise ValueError('click replay step is missing its target signature')
    return ActionSpec(
        kind=step.kind,
        effect=step.effect,
        target=_bind_target(step.target, snapshot),
        response_expectation=step.response_expectation,
    )


def _bind_target(target: ReplayTargetSignature, snapshot: ObservationSnapshot) -> ElementRef:
    artifact = _single_ax_artifact(snapshot)
    if artifact is None:
        raise ReplayDriftError('fresh replay capture lacks unique AX evidence')
    evidence = RegionRef(
        snapshot_id=snapshot.snapshot_id,
        artifact_sha256=artifact.sha256,
        modality=EvidenceKind.AX_TREE,
        locator=f'ax:role/{target.semantic_role}/name-sha256/{target.accessible_name_hash}',
    )
    return ElementRef(
        snapshot_id=snapshot.snapshot_id,
        evidence=(evidence,),
        semantic_role=target.semantic_role,
        accessible_name_hash=target.accessible_name_hash,
    )


class ReplayDriftError(ValueError):
    """Fresh evidence cannot safely satisfy an exact replay binding."""


def _single_ax_artifact(snapshot: ObservationSnapshot):
    artifacts = [artifact for artifact in snapshot.artifacts if artifact.kind is EvidenceKind.AX_TREE]
    return artifacts[0] if len(artifacts) == 1 else None


def _ax_property(node: dict[str, Any], name: str) -> object:
    properties = node.get('properties')
    if not isinstance(properties, list):
        return None
    for item in properties:
        if isinstance(item, dict) and item.get('name') == name:
            value = item.get('value')
            return value.get('value') if isinstance(value, dict) else value
    return None


def _ax_text(node: dict[str, Any], key: str) -> str:
    value = node.get(key)
    if isinstance(value, dict):
        inner = value.get('value')
        return inner if isinstance(inner, str) else ''
    return value if isinstance(value, str) else ''


__all__ = ['ActionReplayExecutor', 'AxReplayVerifier', 'ReplaySnapshotCapture']
