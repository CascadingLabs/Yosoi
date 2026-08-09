"""Index diffing: what it compares, what it refuses to compare, and what it admits it missed."""

from __future__ import annotations

from yosoi.observations.artifacts import MemoryArtifactStore
from yosoi.observations.index.compiler import ObservationIndexCompiler
from yosoi.observations.index.diff import ChangeKind, diff_indexes
from yosoi.observations.index.paging import PageRequest
from yosoi.observations.models import (
    CaptureProfile,
    DomAttribute,
    DomNode,
    DomSnapshot,
    EvidenceKind,
    ObservationSnapshot,
)
from yosoi.observations.models.dom import serialize_dom_snapshot
from yosoi.observations.pruning import DomPruner, PruningInput, PruningPolicy


def _index(root: DomNode, snapshot_id: str):
    """Compile one rendered-DOM snapshot into the index a consumer would hold."""
    snapshot = DomSnapshot(snapshot_id=snapshot_id, root=root)
    data = serialize_dom_snapshot(snapshot)
    store = MemoryArtifactStore()
    ref = store.put(snapshot_id=snapshot_id, kind=EvidenceKind.RENDERED_DOM, media_type='application/json', data=data)
    manifest = ObservationSnapshot(
        run_id='run',
        episode_id=snapshot_id,
        snapshot_id=snapshot_id,
        requested_profile=CaptureProfile.BROWSER_HEADLESS,
        artifacts=(ref,),
    )
    view = DomPruner().prune(PruningInput(source=ref, data=data), PruningPolicy())
    return ObservationIndexCompiler().compile(manifest, (view,))


def _page(*, heading: str = 'Catalogue', note: str = 'in stock', extra: bool = False) -> DomNode:
    """A small page with an anchored heading, an anchored note, and an optional extra section."""
    children = [
        DomNode(
            node_id='heading',
            tag='h1',
            attributes=(DomAttribute(name='id', value='page-heading'),),
            text=heading,
        ),
        DomNode(
            node_id='note',
            tag='p',
            attributes=(DomAttribute(name='class', value='stock-note'),),
            text=note,
        ),
    ]
    if extra:
        children.append(
            DomNode(
                node_id='banner',
                tag='aside',
                attributes=(DomAttribute(name='id', value='promo'),),
                text='Sale',
            )
        )
    return DomNode(
        node_id='root', tag='html', children=(DomNode(node_id='main', tag='main', children=tuple(children)),)
    )


def test_recapturing_an_unchanged_page_produces_an_empty_diff() -> None:
    """The property everything else rests on: identity comes from the page, not the capture."""
    before = _index(_page(), 'capture-1')
    after = _index(_page(), 'capture-2')

    diff = diff_indexes(before, after)

    assert diff.changes == ()
    assert diff.unchanged > 0
    assert diff.before_snapshot_id == 'capture-1'
    assert diff.after_snapshot_id == 'capture-2'


def test_a_shifted_position_is_not_a_change() -> None:
    """Inserting content above shifts every ordinal beneath it and changes nothing.

    A diff keyed on position reports the whole page as churn here. This is the single measurement
    that justified anchoring, so it is the one the diff must not throw away.
    """
    before = _index(_page(), 'before')
    after = _index(_page(extra=True), 'after')

    diff = diff_indexes(before, after)
    touched = {change.label for change in diff.changes}

    assert not diff.of_kind(ChangeKind.REMOVED), 'nothing was removed by an insertion'
    assert any('aside' in label for label in touched), 'the inserted section is the addition'
    assert not any(label.startswith('h1') for label in touched), 'the heading only moved; it did not change'


def test_edited_text_is_reported_as_a_change_naming_the_field() -> None:
    before = _index(_page(heading='Catalogue'), 'before')
    after = _index(_page(heading='Clearance'), 'after')

    changed = diff_indexes(before, after).of_kind(ChangeKind.CHANGED)

    assert [change.label for change in changed] == ['h1#page-heading']
    assert changed[0].fields == ('summary',)
    assert 'Catalogue' in changed[0].summary
    assert 'Clearance' in changed[0].summary
    assert changed[0].before is not None
    assert changed[0].after is not None
    assert changed[0].before != changed[0].after, 'each side addresses its own snapshot'


def test_entries_without_identity_are_counted_and_never_reported_as_churn() -> None:
    """A quarter of a real page earns no identity. Calling those added and removed is a lie.

    On books.toscrape that would be 20 spurious removals and 20 spurious additions for a page
    that did not change at all.
    """
    before = _index(_page(), 'before')
    after = _index(_page(), 'after')

    diff = diff_indexes(before, after)

    assert diff.without_identity_before > 0, 'the fixture must contain something unanchorable'
    assert diff.without_identity_before == diff.without_identity_after
    assert diff.changes == (), 'unmatchable entries must not surface as changes'
    assert 'were NOT compared' in diff.describe()


def test_a_removed_identity_is_never_paired_with_an_added_one() -> None:
    """No fuzzy matching. A vanished identity plus a new one is two facts, not one modification."""
    before = _index(_page(note='in stock'), 'before')
    # Restyling the note drops its class-derived anchor and mints a different one.
    after_root = _page()
    restyled = DomNode(
        node_id='note',
        tag='p',
        attributes=(DomAttribute(name='class', value='inventory-note'),),
        text='in stock',
    )
    main = after_root.children[0]
    after = _index(
        DomNode(
            node_id='root',
            tag='html',
            children=(DomNode(node_id='main', tag='main', children=(main.children[0], restyled)),),
        ),
        'after',
    )

    diff = diff_indexes(before, after)

    assert diff.of_kind(ChangeKind.REMOVED), 'the old anchor is gone'
    assert diff.of_kind(ChangeKind.ADDED), 'the new anchor is new'
    assert not any(change.label.startswith('p.') and change.kind is ChangeKind.CHANGED for change in diff.changes)


def test_a_diff_of_many_changes_is_paged_and_states_what_it_left_out() -> None:
    before = _index(_page(), 'before')
    many = DomNode(
        node_id='root',
        tag='html',
        children=(
            DomNode(
                node_id='main',
                tag='main',
                # Structurally varied so they stay individual entries: a run of identical
                # sections would collapse into one region, and a region is one change.
                children=tuple(
                    DomNode(
                        node_id=f'added-{index}',
                        tag='section',
                        attributes=(DomAttribute(name='id', value=f'block-{index}'),),
                        text=f'Block {index}',
                        children=tuple(
                            DomNode(node_id=f'added-{index}-p{leaf}', tag='p', text=f'p{leaf}')
                            for leaf in range(index % 4 + 1)
                        ),
                    )
                    for index in range(30)
                ),
            ),
        ),
    )
    after = _index(many, 'after')

    diff = diff_indexes(before, after, PageRequest(limit=5))

    assert len(diff.changes) == 5
    assert diff.truncated is True
    assert diff.model_dump(mode='json')['truncated'] is True
    assert diff.page is not None
    assert diff.page.total > 5
    assert 'beyond this page' in diff.describe()


def test_a_region_observing_fewer_members_is_flagged_as_coverage() -> None:
    """The shape a virtualisation bug takes: same region, quietly fewer records."""

    def listing(count: int) -> DomNode:
        rows = tuple(
            DomNode(
                node_id=f'row-{index}',
                tag='li',
                attributes=(DomAttribute(name='data-id', value=f'r{index}'),),
                text=f'Row {index}',
            )
            for index in range(count)
        )
        return DomNode(
            node_id='root',
            tag='html',
            children=(
                DomNode(node_id='list', tag='ul', attributes=(DomAttribute(name='id', value='rows'),), children=rows),
            ),
        )

    diff = diff_indexes(_index(listing(6), 'full'), _index(listing(4), 'partial'))
    coverage_changes = [change for change in diff.changes if change.coverage_shrank]

    assert coverage_changes, 'a region that lost members must be reported on its coverage'
    assert 'FEWER' in coverage_changes[0].summary
