"""Template shared by every deterministic modality pruner.

A pruner decides *what survives*; it should not also re-implement digest validation, policy
hashing, fragment addressing, budget capping, and omission accounting. Those are identical
for every modality and are owned here, so a new pruner is one `reduce` method plus the
`name`/`version`/`evidence_kind` identity triple.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from yosoi.observations.models.artifact import EvidenceKind
from yosoi.observations.models.view import PrunedFragment, PrunedView, RegionCoverage, RegionRef
from yosoi.observations.pruning._shared import pruning_policy_hash, pruning_stats, require_prunable
from yosoi.observations.pruning.protocol import PruningInput, PruningPolicy


@dataclass(frozen=True, slots=True)
class PruneCandidate:
    """One piece of evidence a pruner proposes to keep, addressed inside its artifact.

    `coverage` is required when the locator addresses a repeat region and forbidden
    otherwise; `PrunedFragment` enforces it rather than trusting each pruner to remember.
    """

    locator: str
    label: str
    summary: str
    coverage: RegionCoverage | None = None


@dataclass(frozen=True, slots=True)
class Reduction:
    """A pruner's proposal: ordered candidates plus the population they were drawn from.

    `source_items` is the population this pruner actually considered, not the whole
    artifact — two pruners over the same document (head and body) each account for their
    own region, so neither can claim credit for the other's omissions.
    """

    candidates: tuple[PruneCandidate, ...]
    source_items: int


def clip(value: str, limit: int) -> str:
    """Collapse whitespace and bound one summary to the policy's per-fragment limit."""
    collapsed = ' '.join(value.split())
    return collapsed[:limit]


class SemanticPruner(ABC):
    """Deterministic, modality-local reducer with shared identity and accounting."""

    name: ClassVar[str]
    version: ClassVar[str]
    evidence_kind: ClassVar[EvidenceKind]

    def prune(self, source: PruningInput, policy: PruningPolicy) -> PrunedView:
        """Validate identity, run the modality reduction, and account for what was dropped."""
        require_prunable(source, self.evidence_kind, policy)
        reduction = self.reduce(source.data, policy)
        retained = reduction.candidates[: policy.max_fragments]

        fragments = tuple(
            PrunedFragment(
                ref=RegionRef(
                    snapshot_id=source.source.snapshot_id,
                    artifact_sha256=source.source.sha256,
                    modality=self.evidence_kind,
                    locator=candidate.locator,
                ),
                ordinal=ordinal,
                label=candidate.label,
                summary=clip(candidate.summary, policy.max_fragment_chars),
                coverage=candidate.coverage,
            )
            for ordinal, candidate in enumerate(retained)
        )
        output_bytes = len('\n'.join(f'{f.label}\t{f.summary}' for f in fragments).encode())
        # Accounting is per ADDRESS, not per fragment: one element can declare more than one
        # thing, so counting fragments would let "retained" exceed the population it came from.
        addressed = {fragment.ref.locator for fragment in fragments}

        return PrunedView(
            source=source.source,
            pruner_name=self.name,
            pruner_version=self.version,
            policy_hash=pruning_policy_hash(policy),
            fragments=fragments,
            stats=pruning_stats(
                source=source,
                source_items=reduction.source_items,
                retained_items=len(addressed),
                output_bytes=output_bytes,
                truncated=len(retained) < len(reduction.candidates),
            ),
        )

    @abstractmethod
    def reduce(self, data: bytes, policy: PruningPolicy) -> Reduction:
        """Propose what survives for this modality. Pure, deterministic, no I/O."""


__all__ = ['PruneCandidate', 'Reduction', 'SemanticPruner', 'clip']
