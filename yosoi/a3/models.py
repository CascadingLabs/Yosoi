"""Immutable action-episode and exact replay contracts.

The transition ledger remains the source of truth. These models are conservative projections:
they retain source receipt fingerprints and evidence references, but a replay must produce new
captures and receipts before it is considered successful.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from yosoi.actions.models import (
    ActionKind,
    ActionSpec,
    AssertionStatus,
    CaptureRef,
    EffectClass,
    OutcomeStatus,
    ResponseExpectationSpec,
    TransitionReceipt,
)
from yosoi.observations.models.artifact import EvidenceKind
from yosoi.observations.models.snapshot import ObservationSnapshot
from yosoi.observations.models.view import RegionRef

A3_ACTION_SCHEMA_VERSION = 'a3action1'
_SHA256 = r'^[0-9a-f]{64}$'
_SAFE_CODE = r'^[a-z][a-z0-9_.-]{0,127}$'


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid', strict=True)


class ReplayTargetSignature(_FrozenModel):
    """Evidence-derived target identity that can be rebound to a fresh AX capture."""

    semantic_role: str = Field(pattern=r'^[a-z][a-z0-9_-]{0,63}$')
    accessible_name_hash: str = Field(pattern=_SHA256)
    source_evidence: RegionRef

    @model_validator(mode='after')
    def _requires_ax_evidence(self) -> ReplayTargetSignature:
        if self.source_evidence.modality is not EvidenceKind.AX_TREE:
            raise ValueError('action replay targets require AX evidence')
        return self


class AxPropertyExpectation(_FrozenModel):
    """One bounded accessibility property required on the matched postcondition node."""

    name: str = Field(pattern=_SAFE_CODE)
    value: str | bool | int

    @model_validator(mode='after')
    def _bounded_value(self) -> AxPropertyExpectation:
        if isinstance(self.value, str) and (not self.value or len(self.value) > 256):
            raise ValueError('AX property strings must be non-empty and bounded')
        return self


class ReplayExpectation(_FrozenModel):
    """Machine-readable, versioned postcondition saved during discovery."""

    assertion_id: str = Field(pattern=_SAFE_CODE)
    verifier_id: str = Field(default='ax-target', pattern=_SAFE_CODE)
    verifier_version: str = Field(default='v1', pattern=_SAFE_CODE)
    target: ReplayTargetSignature
    properties: tuple[AxPropertyExpectation, ...] = Field(default=(), max_length=8)

    @model_validator(mode='after')
    def _unique_properties(self) -> ReplayExpectation:
        names = [item.name for item in self.properties]
        if len(names) != len(set(names)):
            raise ValueError('AX postcondition properties cannot repeat')
        return self


class ActionEpisodeStep(_FrozenModel):
    """One proven discovery transition plus its explicit replay postcondition."""

    receipt: TransitionReceipt
    expect: ReplayExpectation

    @model_validator(mode='after')
    def _proven_success(self) -> ActionEpisodeStep:
        if self.receipt.outcome is not OutcomeStatus.SUCCESS:
            raise ValueError('episode steps require successful source receipts')
        if self.receipt.after is None:
            raise ValueError('episode steps require an after capture')
        if self.expect.target.source_evidence.snapshot_id != self.receipt.after.snapshot_id:
            raise ValueError('postcondition evidence must belong to the source after capture')
        if not any(
            result.assertion_id == self.expect.assertion_id and result.status is AssertionStatus.PASSED
            for result in self.receipt.assertions
        ):
            raise ValueError('replay postcondition must name a passing source assertion')
        return self


class ActionEpisode(_FrozenModel):
    """Ordered source-of-truth discovery journey."""

    schema_version: Literal['a3action1'] = A3_ACTION_SCHEMA_VERSION
    episode_id: str = Field(min_length=1, max_length=256)
    snapshots: tuple[ObservationSnapshot, ...] = Field(min_length=2, max_length=65)
    steps: tuple[ActionEpisodeStep, ...] = Field(min_length=1, max_length=64)

    @model_validator(mode='after')
    def _contiguous_lineage(self) -> ActionEpisode:  # noqa: C901 — one model-level invariant audit
        for current, following in zip(self.steps, self.steps[1:], strict=False):
            if current.receipt.after != following.receipt.before:
                raise ValueError('episode receipts must form one contiguous capture lineage')
        fingerprints = [step.receipt.fingerprint for step in self.steps]
        if len(fingerprints) != len(set(fingerprints)):
            raise ValueError('episode receipts cannot repeat')
        if len({step.receipt.policy.policy_version for step in self.steps}) != 1:
            raise ValueError('episode steps must share one policy version')
        if len({step.receipt.redaction_version for step in self.steps}) != 1:
            raise ValueError('episode steps must share one redaction version')
        if any(step.expect.verifier_id != 'ax-target' or step.expect.verifier_version != 'v1' for step in self.steps):
            raise ValueError('episode contains an unsupported verifier binding')
        snapshot_by_id = {snapshot.snapshot_id: snapshot for snapshot in self.snapshots}
        if len(snapshot_by_id) != len(self.snapshots):
            raise ValueError('episode snapshots cannot repeat')
        if any(snapshot.episode_id != self.episode_id for snapshot in self.snapshots):
            raise ValueError('episode snapshots must share the declared episode identity')
        if len({snapshot.run_id for snapshot in self.snapshots}) != 1:
            raise ValueError('episode snapshots must come from one discovery run')
        if len({snapshot.requested_profile for snapshot in self.snapshots}) != 1:
            raise ValueError('episode snapshots must use one capture profile')
        required_ids = {
            capture.snapshot_id
            for step in self.steps
            for capture in (step.receipt.before, step.receipt.after)
            if capture is not None
        }
        if set(snapshot_by_id) != required_ids:
            raise ValueError('episode snapshot catalog must exactly cover receipt lineage')
        for step in self.steps:
            before = snapshot_by_id[step.receipt.before.snapshot_id]
            after_ref = step.receipt.after
            if after_ref is None:
                raise ValueError('episode step lost its after capture')
            after = snapshot_by_id[after_ref.snapshot_id]
            if _capture_identity(before) != step.receipt.before or _capture_identity(after) != after_ref:
                raise ValueError('receipt capture identity disagrees with the snapshot catalog')
            _require_region(before, *(step.receipt.action.target.evidence if step.receipt.action.target else ()))
            _require_region(after, step.expect.target.source_evidence)
        return self

    def canonical_json(self) -> str:
        """Serialize the episode deterministically, excluding volatile receipt timing."""
        payload = {
            'schema_version': self.schema_version,
            'episode_id': self.episode_id,
            'snapshots': [snapshot.model_dump(mode='json') for snapshot in self.snapshots],
            'steps': [
                {'receipt': step.receipt.canonical_dict(), 'expect': step.expect.model_dump(mode='json')}
                for step in self.steps
            ],
        }
        return json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True)

    @property
    def fingerprint(self) -> str:
        """Return stable identity for this exact proven discovery journey."""
        return hashlib.sha256(self.canonical_json().encode()).hexdigest()


class ActionReplayStep(_FrozenModel):
    """One exact guarded step projected from a successful discovery receipt."""

    step_id: str = Field(pattern=_SAFE_CODE)
    kind: ActionKind
    effect: EffectClass
    target: ReplayTargetSignature | None = None
    url: str | None = None
    response_expectation: ResponseExpectationSpec | None = None
    expect: ReplayExpectation
    source_receipt_fingerprint: str = Field(pattern=_SHA256)

    @model_validator(mode='after')
    def _closed_action_shape(self) -> ActionReplayStep:
        if self.kind is ActionKind.NAVIGATE:
            ActionSpec(
                kind=self.kind,
                effect=self.effect,
                url=self.url,
                response_expectation=self.response_expectation,
            )
            if self.target is not None:
                raise ValueError('navigate replay steps cannot carry a target')
        elif self.kind is ActionKind.CLICK:
            if self.target is None or self.url is not None:
                raise ValueError('click replay steps require only a rebound target')
        else:
            raise ValueError('exact action replay currently supports only navigate and click')
        return self


class ActionReplayPlan(_FrozenModel):
    """LLM-free exact replay projection over one proven episode."""

    schema_version: Literal['a3action1'] = A3_ACTION_SCHEMA_VERSION
    plan_id: str = Field(pattern=_SHA256)
    source_episode_fingerprint: str = Field(pattern=_SHA256)
    policy_version: str = Field(pattern=_SAFE_CODE)
    redaction_version: str = Field(pattern=_SAFE_CODE)
    steps: tuple[ActionReplayStep, ...] = Field(min_length=1, max_length=64)


def _capture_identity(snapshot: ObservationSnapshot) -> CaptureRef:
    manifest_sha256 = hashlib.sha256(snapshot.model_dump_json().encode()).hexdigest()
    return CaptureRef(
        snapshot_id=snapshot.snapshot_id,
        manifest_sha256=manifest_sha256,
        parent_snapshot_id=snapshot.parent_snapshot_id,
    )


def _require_region(snapshot: ObservationSnapshot, *regions: RegionRef) -> None:
    artifacts = {(artifact.kind, artifact.sha256) for artifact in snapshot.artifacts}
    if any((region.modality, region.artifact_sha256) not in artifacts for region in regions):
        raise ValueError('episode region evidence is absent from its snapshot manifest')


class ReplayRunStatus(str, Enum):
    """Terminal state of a fresh-session exact replay."""

    COMPLETED = 'completed'
    DRIFTED = 'drifted'


class ActionReplayRun(_FrozenModel):
    """Fresh replay evidence; source receipts are never reused as success authority."""

    plan_id: str = Field(pattern=_SHA256)
    status: ReplayRunStatus
    receipts: tuple[TransitionReceipt, ...] = Field(max_length=64)
    final_capture: CaptureRef | None = None
    failed_step_id: str | None = Field(default=None, pattern=_SAFE_CODE)

    @model_validator(mode='after')
    def _coherent_terminal_state(self) -> ActionReplayRun:
        if self.status is ReplayRunStatus.COMPLETED:
            if self.failed_step_id is not None:
                raise ValueError('completed replay cannot carry a failed step')
            if not self.receipts or any(receipt.outcome is not OutcomeStatus.SUCCESS for receipt in self.receipts):
                raise ValueError('completed replay requires new successful receipts')
            if self.final_capture is None or self.final_capture != self.receipts[-1].after:
                raise ValueError('completed replay must expose its final proven capture')
        elif self.failed_step_id is None:
            raise ValueError('drifted replay requires the failed step id')
        return self


__all__ = [
    'A3_ACTION_SCHEMA_VERSION',
    'ActionEpisode',
    'ActionEpisodeStep',
    'ActionReplayPlan',
    'ActionReplayRun',
    'ActionReplayStep',
    'AxPropertyExpectation',
    'ReplayExpectation',
    'ReplayRunStatus',
    'ReplayTargetSignature',
]
