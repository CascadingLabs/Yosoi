"""Deterministic flat-index compiler.

Flat, not hierarchical, and deliberately so: progressive-disclosure work (arXiv:2607.17598)
measured a second routing level *hurting* retrieval, so the index an agent holds is one
level deep and detail is one inspection hop away.
"""

from __future__ import annotations

from collections.abc import Sequence

from yosoi.observations.index.addressing import ref_id
from yosoi.observations.models.artifact import EvidenceKind
from yosoi.observations.models.index import IndexEntry, ObservationIndex
from yosoi.observations.models.snapshot import ObservationSnapshot
from yosoi.observations.models.view import Pagination, PrunedView

MODALITY_ORDER: tuple[EvidenceKind, ...] = (
    EvidenceKind.SOURCE_HTML,
    EvidenceKind.RENDERED_DOM,
    EvidenceKind.AX_TREE,
    EvidenceKind.NETWORK,
    EvidenceKind.HEALTH,
    EvidenceKind.VISUAL,
)
"""Fixed modality ordering so index output never depends on caller iteration order."""


class ObservationCompileError(ValueError):
    """Raised when a view cannot be compiled against its declared snapshot."""


def _sort_key(view: PrunedView) -> tuple[int, str, str]:
    """Order views by modality, then pruner, then artifact digest — never by arrival."""
    return (MODALITY_ORDER.index(view.source.kind), view.pruner_name, view.source.sha256)


def _combined_page(views: Sequence[PrunedView]) -> Pagination:
    """Sum the views' windows into the index's own account of what it holds.

    `offset` is the first view's offset because the index is read front to back; what matters
    downstream is `returned` against `total`, which is what tells a reader whether the entries
    they hold are the whole reduction or the first slice of something far larger.
    """
    return Pagination(
        offset=views[0].page.offset,
        limit=max(view.page.limit for view in views),
        returned=sum(view.page.returned for view in views),
        total=sum(view.page.total for view in views),
    )


class ObservationIndexCompiler:
    """Combine explicit modality views into one flat address space."""

    def compile(self, snapshot: ObservationSnapshot, views: Sequence[PrunedView]) -> ObservationIndex:
        """Flatten views into a snapshot-scoped index with deterministic global ordinals."""
        declared = {artifact.sha256: artifact for artifact in snapshot.artifacts}
        for view in views:
            if view.source.snapshot_id != snapshot.snapshot_id:
                raise ObservationCompileError('pruned view belongs to a different snapshot')
            if view.source.sha256 not in declared:
                raise ObservationCompileError('pruned view sources an artifact the snapshot does not declare')
            if declared[view.source.sha256] != view.source:
                raise ObservationCompileError('pruned view artifact reference disagrees with the snapshot manifest')

        ordered = sorted(views, key=_sort_key)
        entries: list[IndexEntry] = []
        seen: set[tuple[str, str]] = set()
        # Each view is numbered above the FULL candidate space of the views before it, not above
        # the entries they happened to return. Basing it on returned counts would renumber every
        # later view whenever an earlier one was fetched at a different page size, and a
        # reference is only durable if its ordinal means one thing.
        base = 0
        for view in ordered:
            for fragment in view.fragments:
                address = (fragment.ref.artifact_sha256, fragment.ref.locator)
                if address in seen:
                    raise ObservationCompileError(f'duplicate index address {fragment.ref.locator!r}')
                seen.add(address)
                entries.append(
                    IndexEntry(
                        ordinal=base + fragment.ordinal,
                        ref=fragment.ref,
                        label=fragment.label,
                        summary=fragment.summary,
                        coverage=fragment.coverage,
                        bound_to_previous=fragment.bound_to_previous,
                        ref_id=ref_id(fragment.ref.modality, fragment.ref.locator),
                    )
                )
            base += view.page.total

        return ObservationIndex(
            snapshot_id=snapshot.snapshot_id,
            sources=tuple(dict.fromkeys(view.source for view in ordered)),
            modalities=tuple(dict.fromkeys(view.source.kind for view in ordered)),
            entries=tuple(entries),
            page=_combined_page(ordered) if ordered else None,
        )


__all__ = ['MODALITY_ORDER', 'ObservationCompileError', 'ObservationIndexCompiler']
