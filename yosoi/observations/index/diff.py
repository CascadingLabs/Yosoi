"""Compare two indexes over identity, not position.

This is what `ref_id` was built for. A `RegionRef` carries a snapshot id and an artifact digest,
so it can never compare equal across captures — by construction, not by accident. Comparing two
snapshots therefore needs a value derived from the *page*, and `IndexEntry.ref_id` is it.

Three rules make a diff trustworthy, and each of them exists because its opposite produces a
convincing lie:

* **Position is not identity.** Ordinals are deliberately ignored. Inserting one section near the
  top of a document shifts every ordinal beneath it while changing nothing, and a diff keyed on
  position reports the whole page as churn. The `reference_stability` gate measures exactly this:
  `section_above` loses no identities at all.

* **An entry with no identity is not "added".** A quarter of a real page earns no `ref_id` —
  20 of 79 entries on books.toscrape — because the page offers nothing durable to anchor them to.
  Those entries cannot be matched across captures, and pretending otherwise would report 20
  removals and 20 additions for a page that did not change. They are counted and named as
  unmatchable instead, which is a smaller claim and a true one.

* **A diff of a paged index is a diff of a page.** Two 271,134-candidate reductions do not compare
  in one bounded answer, so the comparison is windowed like everything else here and states the
  population it did not reach.

What this deliberately does NOT do is match *similar* entries. There is no fuzzy fallback pairing
an entry whose identity vanished with one that appeared — that is the "probably the same thing"
inference the whole identity tier refuses, and at diff time it would silently turn a real removal
plus a real addition into a fabricated modification.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, computed_field

from yosoi.observations.index.paging import PageRequest, paginate
from yosoi.observations.models.index import IndexEntry, ObservationIndex
from yosoi.observations.models.view import Pagination, RegionCoverage, RegionRef


class ChangeKind(str, Enum):
    """Structural change classification between indexed snapshots."""

    ADDED = 'added'
    REMOVED = 'removed'
    CHANGED = 'changed'


class IndexChange(BaseModel):
    """One addressable change between two observation indexes.

    Both refs are carried when an entry survived: a reader who wants the evidence needs the
    address inside the snapshot it lives in, and the two are different addresses to the same
    identified thing.
    """

    model_config = ConfigDict(frozen=True)

    kind: ChangeKind
    ref_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    before: RegionRef | None = None
    after: RegionRef | None = None
    fields: tuple[str, ...] = ()
    """Which comparable fields differ. Empty for an addition or a removal."""

    summary: str = ''

    @property
    def coverage_shrank(self) -> bool:
        """Whether this change is a region observing fewer members than it did before.

        Called out because it is the shape a virtualisation bug takes: the region is still there,
        still complete-looking, and holds fewer records than the capture before it.
        """
        return 'coverage' in self.fields


class ObservationDiff(BaseModel):
    """Bounded structural comparison between two exact snapshot indexes."""

    model_config = ConfigDict(frozen=True)

    before_snapshot_id: str = Field(min_length=1)
    after_snapshot_id: str = Field(min_length=1)
    changes: tuple[IndexChange, ...] = ()
    unchanged: int = Field(default=0, ge=0)
    without_identity_before: int = Field(default=0, ge=0)
    without_identity_after: int = Field(default=0, ge=0)
    page: Pagination | None = None

    @computed_field
    @property
    def truncated(self) -> bool:
        """Whether changes exist beyond this window."""
        return self.page is not None and not self.page.complete

    def of_kind(self, kind: ChangeKind) -> tuple[IndexChange, ...]:
        """Return the changes of one kind, in the diff's own order."""
        return tuple(change for change in self.changes if change.kind is kind)

    def describe(self) -> str:
        """State the comparison in one line, including what could not be compared.

        The unmatchable counts are part of the result, not a footnote. A diff reporting "3
        changes" over an index where 200 entries carry no identity has compared a fraction of the
        page, and a reader who is not told that will believe the rest held still.
        """
        counts = ', '.join(
            f'{len(self.of_kind(kind))} {kind.value}'
            for kind in (ChangeKind.CHANGED, ChangeKind.ADDED, ChangeKind.REMOVED)
        )
        line = f'{counts}; {self.unchanged} unchanged'
        if self.without_identity_before or self.without_identity_after:
            line += (
                f'; {self.without_identity_before}→{self.without_identity_after} entries carry no identity '
                'and were NOT compared'
            )
        if self.truncated and self.page is not None:
            beyond = self.page.total - (self.page.offset + self.page.returned)
            line += f'; {beyond} further changes beyond this page (next offset {self.page.next_offset})'
        return line


_COMPARABLE = ('label', 'summary', 'coverage')
"""What a change is measured over.

`ordinal` is excluded on purpose — it is position, and position moves for reasons that are not
changes. `ref` is excluded because it CANNOT compare equal across captures; it is the thing
identity exists to replace.
"""


def _differing_fields(before: IndexEntry, after: IndexEntry) -> tuple[str, ...]:
    """Return the comparable fields on which two entries of one identity disagree."""
    return tuple(name for name in _COMPARABLE if getattr(before, name) != getattr(after, name))


def _coverage_note(before: RegionCoverage | None, after: RegionCoverage | None) -> str:
    """Describe a coverage move in the terms a reader acts on."""
    if before is None or after is None:
        return 'became a region' if after is not None else 'stopped being a region'
    if after.observed < before.observed:
        return f'observes {before.observed} → {after.observed} members (FEWER)'
    if after.observed > before.observed:
        return f'observes {before.observed} → {after.observed} members'
    return f'declared {before.declared} → {after.declared}'


def _change_summary(fields: tuple[str, ...], before: IndexEntry, after: IndexEntry) -> str:
    """Describe what moved, field by field, without restating what held still."""
    parts: list[str] = []
    if 'label' in fields:
        parts.append(f'label {before.label!r} → {after.label!r}')
    if 'coverage' in fields:
        parts.append(_coverage_note(before.coverage, after.coverage))
    if 'summary' in fields:
        parts.append(f'summary {before.summary!r} → {after.summary!r}')
    return '; '.join(parts)


def _identified(index: ObservationIndex) -> dict[str, IndexEntry]:
    """Index entries by identity, skipping the ones that have none."""
    return {entry.ref_id: entry for entry in index.entries if entry.ref_id is not None}


def diff_indexes(
    before: ObservationIndex,
    after: ObservationIndex,
    page: PageRequest | None = None,
) -> ObservationDiff:
    """Compare two indexes by identity and return one bounded page of the differences.

    Ordering approximates reading the *after* index front to back — a change is placed by where
    it now sits, or by where it used to sit if it is gone — then by kind and identity so the
    result is byte-identical across runs.
    """
    before_by_id = _identified(before)
    after_by_id = _identified(after)

    changes: list[tuple[tuple[int, str, str], IndexChange]] = []
    unchanged = 0

    for ref_id, after_entry in after_by_id.items():
        before_entry = before_by_id.get(ref_id)
        if before_entry is None:
            changes.append(
                (
                    (after_entry.ordinal, ChangeKind.ADDED.value, ref_id),
                    IndexChange(
                        kind=ChangeKind.ADDED,
                        ref_id=ref_id,
                        label=after_entry.label,
                        after=after_entry.ref,
                        summary=after_entry.summary,
                    ),
                )
            )
            continue
        fields = _differing_fields(before_entry, after_entry)
        if not fields:
            unchanged += 1
            continue
        changes.append(
            (
                (after_entry.ordinal, ChangeKind.CHANGED.value, ref_id),
                IndexChange(
                    kind=ChangeKind.CHANGED,
                    ref_id=ref_id,
                    label=after_entry.label,
                    before=before_entry.ref,
                    after=after_entry.ref,
                    fields=fields,
                    summary=_change_summary(fields, before_entry, after_entry),
                ),
            )
        )

    for ref_id, before_entry in before_by_id.items():
        if ref_id in after_by_id:
            continue
        changes.append(
            (
                (before_entry.ordinal, ChangeKind.REMOVED.value, ref_id),
                IndexChange(
                    kind=ChangeKind.REMOVED,
                    ref_id=ref_id,
                    label=before_entry.label,
                    before=before_entry.ref,
                    summary=before_entry.summary,
                ),
            )
        )

    ordered = [change for _, change in sorted(changes, key=lambda item: item[0])]
    window, pagination = paginate(ordered, page or PageRequest())
    return ObservationDiff(
        before_snapshot_id=before.snapshot_id,
        after_snapshot_id=after.snapshot_id,
        changes=window,
        unchanged=unchanged,
        without_identity_before=len(before.entries) - len(before_by_id),
        without_identity_after=len(after.entries) - len(after_by_id),
        page=pagination,
    )


__all__ = ['ChangeKind', 'IndexChange', 'ObservationDiff', 'diff_indexes']
