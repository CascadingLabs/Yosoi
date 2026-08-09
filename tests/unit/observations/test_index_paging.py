"""Paging over a reduction's candidate space: global ordinals, exact tiling, fuzzy boundaries."""

from __future__ import annotations

import pytest

from yosoi.observations.artifacts import MemoryArtifactStore
from yosoi.observations.index.compiler import ObservationIndexCompiler
from yosoi.observations.index.paging import PAGE_SLACK, PageRequest, paginate
from yosoi.observations.index.render import CharacterEstimator, ObservationIndexRenderer, RenderPolicy
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


def _rows(count: int) -> DomSnapshot:
    """Build `count` STRUCTURALLY VARIED sibling records under one container.

    Uniform records are the case the pruner already answers: 10,000 identical rows collapse to a
    region and an exemplar, and there is nothing left to page. Paging exists for the reduction
    that is legitimately large — records whose shapes cycle, so no run repeats and every record
    earns its own candidate, which is what a real Wikipedia list looks like.
    """
    children = tuple(
        DomNode(
            node_id=f'row-{index}',
            tag='li',
            attributes=(DomAttribute(name='class', value='row'), DomAttribute(name='data-id', value=f'r{index}')),
            text=f'Row {index}',
            children=tuple(
                DomNode(node_id=f'row-{index}-cell-{cell}', tag='span', text=f'c{cell}')
                for cell in range(index % 5 + 1)
            ),
        )
        for index in range(count)
    )
    root = DomNode(
        node_id='root',
        tag='html',
        children=(DomNode(node_id='list', tag='ul', children=children),),
    )
    return DomSnapshot(snapshot_id='paged', root=root)


def _view(snapshot: DomSnapshot, page: PageRequest | None = None):
    data = serialize_dom_snapshot(snapshot)
    store = MemoryArtifactStore()
    ref = store.put(
        snapshot_id=snapshot.snapshot_id, kind=EvidenceKind.RENDERED_DOM, media_type='application/json', data=data
    )
    manifest = ObservationSnapshot(
        run_id='run',
        episode_id='episode',
        snapshot_id=snapshot.snapshot_id,
        requested_profile=CaptureProfile.BROWSER_HEADLESS,
        artifacts=(ref,),
    )
    return DomPruner().prune(PruningInput(source=ref, data=data), PruningPolicy(), page), manifest


def test_pages_tile_the_candidate_space_exactly() -> None:
    """Following `next_offset` must visit every candidate once — no gaps, no repeats."""
    items = list(range(97))
    visited: list[int] = []
    offset: int | None = 0
    while offset is not None:
        window, pagination = paginate(items, PageRequest(offset=offset, limit=20))
        visited.extend(window)
        offset = pagination.next_offset

    assert visited == items


def test_a_page_never_separates_a_bound_candidate_from_its_predecessor() -> None:
    """A region and its exemplar are one unit; the window flexes rather than cutting between."""
    # Every third item is bound to the one before it, so an exact cut at 10 would orphan item 10.
    items = list(range(30))
    bound = {index for index in items if index % 3 == 1}

    window, pagination = paginate(items, PageRequest(limit=10), bound_to_previous=lambda i: i in bound)

    assert pagination.returned == 11, 'the window took one more item rather than cutting a pair'
    assert window[-1] == 10
    assert pagination.next_offset == 11, 'the next page resumes exactly where this one stopped'


def test_a_bound_run_longer_than_the_slack_retracts_instead_of_overshooting() -> None:
    items = list(range(40))
    # One long bound run starting right at the boundary: 10..(10+PAGE_SLACK+3)
    bound = set(range(10, 10 + PAGE_SLACK + 4))

    _, pagination = paginate(items, PageRequest(limit=10), bound_to_previous=lambda i: i in bound)

    assert pagination.returned == 10, 'the boundary was already clean; nothing to flex for'
    assert pagination.next_offset == 10


def test_ordinals_are_global_so_a_reference_means_one_thing_on_every_page() -> None:
    snapshot = _rows(40)
    first, _ = _view(snapshot, PageRequest(offset=0, limit=10))
    second, _ = _view(snapshot, PageRequest(offset=first.page.next_offset or 0, limit=10))

    assert first.fragments[0].ordinal == 0
    assert second.fragments[0].ordinal == first.page.returned, 'page two continues the numbering'
    assert not {f.ordinal for f in first.fragments} & {f.ordinal for f in second.fragments}


def test_a_view_states_the_population_it_did_not_return() -> None:
    snapshot = _rows(40)
    view, _ = _view(snapshot, PageRequest(offset=0, limit=5))

    assert view.page.returned == 5
    assert view.page.total > 5
    assert view.page.complete is False
    assert view.page.next_offset == 5


def test_a_complete_reduction_reports_itself_complete() -> None:
    view, _ = _view(_rows(3))

    assert view.page.complete is True
    assert view.page.next_offset is None
    assert view.stats.truncated is False


def test_the_rendered_footer_names_candidates_the_index_does_not_hold() -> None:
    """The failure this replaces: a footer that called 270,134 unindexed candidates inspectable."""
    snapshot = _rows(60)
    view, manifest = _view(snapshot, PageRequest(offset=0, limit=6))
    index = ObservationIndexCompiler().compile(manifest, (view,))

    rendered = ObservationIndexRenderer().render(
        index, RenderPolicy(tokenizer_id=CharacterEstimator().id, token_budget=4_000)
    )

    assert index.page is not None
    assert f'of {index.page.total}' in rendered.text
    assert 'are NOT in it' in rendered.text
    assert 'next page at offset' in rendered.text


def test_a_whole_index_still_reports_a_plain_footer() -> None:
    view, manifest = _view(_rows(3))
    index = ObservationIndexCompiler().compile(manifest, (view,))

    rendered = ObservationIndexRenderer().render(
        index, RenderPolicy(tokenizer_id=CharacterEstimator().id, token_budget=4_000)
    )

    assert 'are NOT in it' not in rendered.text
    assert 'inspect any by its [ordinal]' in rendered.text


@pytest.mark.parametrize('offset', [0, 3, 11])
def test_every_page_resolves_its_own_references(offset: int) -> None:
    """A paged reference is still an exact reference, not a weaker one."""
    from yosoi.observations.index.inspect import InspectionBudget, ObservationInspector

    snapshot = _rows(30)
    data = serialize_dom_snapshot(snapshot)
    store = MemoryArtifactStore()
    ref = store.put(
        snapshot_id=snapshot.snapshot_id, kind=EvidenceKind.RENDERED_DOM, media_type='application/json', data=data
    )
    manifest = ObservationSnapshot(
        run_id='run',
        episode_id='episode',
        snapshot_id=snapshot.snapshot_id,
        requested_profile=CaptureProfile.BROWSER_HEADLESS,
        artifacts=(ref,),
    )
    view = DomPruner().prune(PruningInput(source=ref, data=data), PruningPolicy(), PageRequest(offset=offset, limit=4))
    inspector = ObservationInspector(store, manifest)

    for fragment in view.fragments:
        budget = InspectionBudget()
        if fragment.coverage is not None:
            assert inspector.expand(fragment.ref, budget).members
        else:
            assert inspector.inspect(fragment.ref, budget).returned_bytes > 0
