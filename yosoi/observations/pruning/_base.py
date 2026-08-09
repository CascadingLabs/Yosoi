"""Template shared by every deterministic modality pruner.

A pruner decides *what survives*; it should not also re-implement digest validation, policy
hashing, fragment addressing, budget capping, and omission accounting. Those are identical
for every modality and are owned here, so a new pruner is one `reduce` method plus the
`name`/`version`/`evidence_kind` identity triple.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from typing import ClassVar

from yosoi.observations.index.paging import PageRequest, paginate
from yosoi.observations.models.artifact import EvidenceKind
from yosoi.observations.models.view import Granularity, PrunedFragment, PrunedView, RegionCoverage, RegionRef
from yosoi.observations.pruning._shared import pruning_policy_hash, pruning_stats, require_prunable
from yosoi.observations.pruning.granularity import DESCENT_NOTICE, collapse
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
    depth: int = 0
    """How deep in the walk this candidate sits. The axis progressive collapse cuts on."""

    descends: bool = False
    """Whether content exists below this candidate that the walk may not have indexed."""

    bound_to_previous: bool = False
    """Whether a page boundary must not fall immediately before this candidate.

    A region and the exemplar that shows its shape are one unit. Split across pages, the region
    stands alone with no shape and the exemplar stands alone with no context, so the exemplar
    declares the binding and `paginate` honours it instead of cutting.
    """


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

    def reduce_once(self, source: PruningInput, policy: PruningPolicy) -> Reduction:
        """Validate the artifact and walk it once, returning the reusable candidate space.

        Split out from `prune` because a reduction is expensive and every page of it is the same
        reduction. Walking the HTML Living Standard costs 10.7s and yields 271,134 candidates; a
        272-page sweep that called `prune` per page re-walked all of it 272 times for ~49 minutes
        of duplicated work. Nothing was *wrong* with those pages — `reduce` is pure and
        deterministic over `(data, policy)`, so every page saw the same space and tiling held —
        it was pure waste.

        A caller sweeping a large artifact reduces once and calls `view` per page:

            reduction = pruner.reduce_once(source, policy)
            for offset in offsets:
                pruner.view(source, policy, reduction, PageRequest(offset=offset))

        Deliberately an explicit value rather than an internal cache. A cache keyed on the
        artifact digest would hold a quarter-million candidate objects alive for a caller that
        asked for one page, and this package does not keep mutable global state.
        """
        require_prunable(source, self.evidence_kind, policy)
        return self.reduce(source.data, policy)

    def prune(self, source: PruningInput, policy: PruningPolicy, page: PageRequest | None = None) -> PrunedView:
        """Reduce and return one page of the result. Convenience for a single page."""
        return self.view(source, policy, self.reduce_once(source, policy), page)

    def view(
        self,
        source: PruningInput,
        policy: PruningPolicy,
        reduction: Reduction,
        page: PageRequest | None = None,
    ) -> PrunedView:
        """Build one page of a view from an already-computed reduction."""
        # Collapse first, then window. A reduction too large for the budget is served as the WHOLE
        # document at coarser depth; paging then windows whatever that still leaves. Doing it the
        # other way round would window the front of the document and never reach the rest.
        granularity: Granularity | None = None
        coarsened: tuple[PruneCandidate, ...] = reduction.candidates
        if policy.collapse_to_fit:
            coarsened, granularity = collapse(reduction.candidates, policy.max_fragments)
            coarsened = tuple(
                replace(candidate, summary=f'{candidate.summary}; {DESCENT_NOTICE}')
                if granularity.reduced and candidate.descends and candidate.depth == granularity.depth
                else candidate
                for candidate in coarsened
            )

        request = page or PageRequest(limit=policy.max_fragments)
        retained, pagination = paginate(
            coarsened, request, bound_to_previous=lambda candidate: candidate.bound_to_previous
        )

        fragments = tuple(
            # Ordinals are GLOBAL — the candidate's position in the whole reduction, not in this
            # page. Numbering each page from zero would make `[0]` mean a different thing on
            # every page, and a handle that resolves to the wrong evidence is worse than none.
            PrunedFragment(
                ref=RegionRef(
                    snapshot_id=source.source.snapshot_id,
                    artifact_sha256=source.source.sha256,
                    modality=self.evidence_kind,
                    locator=candidate.locator,
                ),
                ordinal=pagination.offset + position,
                label=candidate.label,
                summary=clip(candidate.summary, policy.max_fragment_chars),
                coverage=candidate.coverage,
                bound_to_previous=candidate.bound_to_previous,
            )
            for position, candidate in enumerate(retained)
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
            page=pagination,
            granularity=granularity,
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
