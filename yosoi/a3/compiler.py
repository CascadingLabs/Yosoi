"""Conservative compilation from proven action episodes to exact replay plans."""

from __future__ import annotations

import hashlib
import json

from yosoi.a3.models import (
    ActionEpisode,
    ActionEpisodeStep,
    ActionReplayPlan,
    ActionReplayStep,
    ReplayExpectation,
    ReplayTargetSignature,
)
from yosoi.actions.adapters.voidcrawl import capture_ref_for
from yosoi.actions.models import ActionKind, TransitionReceipt
from yosoi.observations.models.snapshot import ObservationSnapshot


class ActionReplayCompileError(ValueError):
    """Raised when discovery evidence cannot safely become an exact replay step."""


class ActionEpisodeBuilder:
    """Record a contiguous discovery episode as successful transitions arrive."""

    def __init__(self, *, episode_id: str, initial: ObservationSnapshot) -> None:
        """Start recording from one exact initial capture."""
        if initial.episode_id != episode_id:
            raise ValueError('initial snapshot belongs to another episode')
        self._episode_id = episode_id
        self._snapshots = [initial]
        self._steps: list[ActionEpisodeStep] = []

    def append(
        self,
        *,
        receipt: TransitionReceipt,
        after: ObservationSnapshot,
        expect: ReplayExpectation,
    ) -> None:
        """Append one freshly proven edge and reject any lineage discontinuity immediately."""
        if receipt.before != capture_ref_for(self._snapshots[-1]):
            raise ValueError('receipt does not continue the recorded episode')
        if receipt.after != capture_ref_for(after):
            raise ValueError('after snapshot does not match the transition receipt')
        step = ActionEpisodeStep(receipt=receipt, expect=expect)
        tentative = ActionEpisode(
            episode_id=self._episode_id,
            snapshots=(*self._snapshots, after),
            steps=(*self._steps, step),
        )
        self._snapshots = list(tentative.snapshots)
        self._steps = list(tentative.steps)

    def build(self) -> ActionEpisode:
        """Return the immutable episode accumulated so far."""
        return ActionEpisode(
            episode_id=self._episode_id,
            snapshots=tuple(self._snapshots),
            steps=tuple(self._steps),
        )


def compile_action_episode(episode: ActionEpisode) -> ActionReplayPlan:
    """Compile only proven navigate/click receipts without widening their applicability."""
    steps: list[ActionReplayStep] = []
    for index, source in enumerate(episode.steps):
        action = source.receipt.action
        if action.kind not in {ActionKind.NAVIGATE, ActionKind.CLICK}:
            raise ActionReplayCompileError(f'unsupported replay action: {action.kind.value}')
        target = None
        if action.kind is ActionKind.CLICK:
            original = action.target
            if original is None or original.semantic_role is None or original.accessible_name_hash is None:
                raise ActionReplayCompileError('click receipt lacks a rebindable AX target signature')
            ax_refs = [ref for ref in original.evidence if ref.modality.value == 'ax_tree']
            if len(ax_refs) != 1:
                raise ActionReplayCompileError('click receipt requires exactly one AX evidence reference')
            target = ReplayTargetSignature(
                semantic_role=original.semantic_role,
                accessible_name_hash=original.accessible_name_hash,
                source_evidence=ax_refs[0],
            )
        steps.append(
            ActionReplayStep(
                step_id=f'step-{index + 1}',
                kind=action.kind,
                effect=action.effect,
                target=target,
                url=action.url,
                response_expectation=action.response_expectation,
                expect=source.expect,
                source_receipt_fingerprint=source.receipt.fingerprint,
            )
        )
    source_fingerprint = episode.fingerprint
    identity = json.dumps(
        {
            'source_episode_fingerprint': source_fingerprint,
            'steps': [step.model_dump(mode='json') for step in steps],
        },
        sort_keys=True,
        separators=(',', ':'),
        ensure_ascii=True,
    )
    return ActionReplayPlan(
        plan_id=hashlib.sha256(identity.encode()).hexdigest(),
        source_episode_fingerprint=source_fingerprint,
        policy_version=episode.steps[0].receipt.policy.policy_version,
        redaction_version=episode.steps[0].receipt.redaction_version,
        steps=tuple(steps),
    )


__all__ = ['ActionEpisodeBuilder', 'ActionReplayCompileError', 'compile_action_episode']
