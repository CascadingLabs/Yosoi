"""Shared pruning mechanics without modality-specific semantic rules."""

from __future__ import annotations

import hashlib
import json

from yosoi.observations.models.artifact import EvidenceKind, Sensitivity
from yosoi.observations.models.view import PruningStats
from yosoi.observations.pruning.protocol import PruningInput, PruningPolicy


def pruning_policy_hash(policy: PruningPolicy) -> str:
    """Return a stable identity for semantic-pruning policy inputs."""
    payload = json.dumps(policy.model_dump(mode='json'), sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(payload).hexdigest()


def require_prunable(source: PruningInput, expected: EvidenceKind, policy: PruningPolicy) -> None:
    """Fail closed on modality mismatch or restricted evidence without explicit permission."""
    if source.source.kind != expected:
        raise ValueError(f'{expected.value} pruner cannot consume {source.source.kind.value} evidence')
    if source.source.size_bytes != len(source.data):
        raise ValueError('pruning input byte length does not match its artifact reference')
    if hashlib.sha256(source.data).hexdigest() != source.source.sha256:
        raise ValueError('pruning input digest does not match its artifact reference')
    if (
        source.source.sensitivity in {Sensitivity.RESTRICTED, Sensitivity.EPHEMERAL_SECRET}
        and not policy.include_restricted
    ):
        raise PermissionError('restricted observation evidence requires explicit pruning permission')


def pruning_stats(
    *, source: PruningInput, source_items: int, retained_items: int, output_bytes: int, truncated: bool = False
) -> PruningStats:
    """Build consistent non-negative omission accounting for a pruned view."""
    if retained_items > source_items:
        raise ValueError('retained item count cannot exceed source item count')
    return PruningStats(
        source_items=source_items,
        retained_items=retained_items,
        omitted_items=source_items - retained_items,
        source_bytes=len(source.data),
        output_bytes=output_bytes,
        truncated=truncated,
    )


__all__ = ['pruning_policy_hash', 'pruning_stats', 'require_prunable']
