"""Phase-2 deterministic DOM-pruner tests over synthetic TodoMVC-shaped snapshots."""

from __future__ import annotations

import pytest

from yosoi.observations.artifacts import MemoryArtifactStore
from yosoi.observations.dom_tree import dom_locator
from yosoi.observations.index.addressing import ObservationAddressError, parse_address
from yosoi.observations.index.inspect import InspectionBudget, ObservationInspector
from yosoi.observations.models import (
    CaptureProfile,
    DomAttribute,
    DomNode,
    DomRuntimeState,
    DomSnapshot,
    DomVisibility,
    EvidenceKind,
    ObservationSnapshot,
    RegionRef,
)
from yosoi.observations.models.dom import serialize_dom_snapshot
from yosoi.observations.models.view import PrunedFragment
from yosoi.observations.pruning import DomPruner, PruningInput, PruningPolicy
from yosoi.observations.pruning.dom import MAX_DEPTH


def _reduce(snapshot: DomSnapshot):
    data = serialize_dom_snapshot(snapshot)
    ref = MemoryArtifactStore().put(
        snapshot_id=snapshot.snapshot_id,
        kind=EvidenceKind.RENDERED_DOM,
        media_type='application/json',
        data=data,
    )
    return DomPruner().prune(PruningInput(source=ref, data=data), PruningPolicy())


def _todo(
    node_id: str, text: str, *, checked: bool = False, visibility: DomVisibility = DomVisibility.VISIBLE
) -> DomNode:
    return DomNode(
        node_id=node_id,
        tag='li',
        attributes=(DomAttribute(name='class', value='todo completed' if checked else 'todo'),),
        text=text,
        visibility=visibility,
        runtime=DomRuntimeState(checked=checked),
    )


def test_todomvc_active_items_collapse_with_complete_coverage() -> None:
    root = DomNode(
        node_id='root',
        tag='html',
        children=(
            DomNode(
                node_id='todo-list',
                tag='ul',
                attributes=(DomAttribute(name='id', value='todo-list'),),
                declared_count=3,
                children=(_todo('todo-1', 'Buy milk'), _todo('todo-2', 'Read design'), _todo('todo-3', 'Ship beta')),
            ),
        ),
    )

    view = _reduce(DomSnapshot(snapshot_id='s0', root=root))
    regions = [fragment for fragment in view.fragments if fragment.coverage is not None]

    assert len(regions) == 1
    assert regions[0].coverage is not None
    assert regions[0].coverage.model_dump() == {'observed': 3, 'declared': 3, 'complete': True}
    assert regions[0].summary.startswith('×3 li.todo')
    assert any(fragment.label == 'li.todo' for fragment in view.fragments)


def test_collapsed_region_names_which_members_it_collapsed() -> None:
    """A region must say WHICH members it stands for, not only how many.

    Found against a live TodoMVC capture: the region reported a count and a state tally and
    carried no todo text, so nothing in the index distinguished a list of groceries from a
    list of build failures without spending an `expand` first.
    """
    root = DomNode(
        node_id='root',
        tag='html',
        children=(
            DomNode(
                node_id='todo-list',
                tag='ul',
                children=(_todo('todo-1', 'Buy milk'), _todo('todo-2', 'Read design'), _todo('todo-3', 'Ship beta')),
            ),
        ),
    )

    view = _reduce(DomSnapshot(snapshot_id='s0', root=root))
    region = next(fragment for fragment in view.fragments if fragment.coverage is not None)

    assert '"Buy milk"' in region.summary
    assert '"Read design"' in region.summary
    assert '"Ship beta"' in region.summary


def test_region_sampling_is_bounded_and_says_how_many_it_withheld() -> None:
    """Sampling must not turn a 50-member region back into 50 members of summary."""
    members = tuple(_todo(f'todo-{index}', f'Item {index}') for index in range(50))
    root = DomNode(
        node_id='root',
        tag='html',
        children=(DomNode(node_id='todo-list', tag='ul', children=members),),
    )

    view = _reduce(DomSnapshot(snapshot_id='s0', root=root))
    region = next(fragment for fragment in view.fragments if fragment.coverage is not None)

    assert '"Item 0"' in region.summary
    assert '"Item 3"' not in region.summary, 'only the first few members are sampled'
    assert '+47 more' in region.summary, 'the withheld count must be stated, not implied'


def test_region_sampling_crosses_a_shadow_boundary() -> None:
    """A member whose text lives in a shadow root is still distinguished in the index."""
    hosts = tuple(
        DomNode(
            node_id=f'card-{index}',
            tag='div',
            attributes=(DomAttribute(name='class', value='card'),),
            shadow_root=DomNode(node_id=f'card-{index}-shadow', tag='#shadow-root', text=f'Card {index}'),
        )
        for index in range(2)
    )
    root = DomNode(node_id='root', tag='html', children=(DomNode(node_id='deck', tag='div', children=hosts),))

    view = _reduce(DomSnapshot(snapshot_id='s0', root=root))
    region = next(fragment for fragment in view.fragments if fragment.coverage is not None)

    assert '"Card 0"' in region.summary
    assert '"Card 1"' in region.summary


def test_runtime_state_prevents_active_and_completed_merge() -> None:
    root = DomNode(
        node_id='root',
        tag='html',
        children=(
            DomNode(
                node_id='todo-list',
                tag='ul',
                children=(_todo('todo-1', 'A'), _todo('todo-2', 'B', checked=True), _todo('todo-3', 'C')),
            ),
        ),
    )

    view = _reduce(DomSnapshot(snapshot_id='s1', root=root))

    assert not [fragment for fragment in view.fragments if fragment.coverage is not None]
    assert sum(fragment.label == 'li.todo' for fragment in view.fragments) == 2
    assert sum(fragment.label == 'li.todo.completed' for fragment in view.fragments) == 1


def test_virtualized_region_reports_incomplete_declared_coverage() -> None:
    root = DomNode(
        node_id='root',
        tag='html',
        children=(
            DomNode(
                node_id='todo-list',
                tag='ul',
                declared_count=10_000,
                children=(_todo('todo-1', 'A'), _todo('todo-2', 'B')),
            ),
        ),
    )

    view = _reduce(DomSnapshot(snapshot_id='virtual', root=root))
    region = next(fragment for fragment in view.fragments if fragment.coverage is not None)

    assert region.coverage is not None
    assert region.coverage.observed == 2
    assert region.coverage.declared == 10_000
    assert region.coverage.complete is False
    assert 'observed=2/10000' in region.summary


def test_hidden_empty_wrappers_are_omitted_but_hidden_content_is_retained() -> None:
    root = DomNode(
        node_id='root',
        tag='html',
        children=(
            DomNode(node_id='empty-hidden', tag='div', visibility=DomVisibility.DISPLAY_NONE),
            DomNode(node_id='unknown-wrapper', tag='div', visibility=DomVisibility.UNKNOWN),
            DomNode(
                node_id='hidden-modal',
                tag='dialog',
                visibility=DomVisibility.HIDDEN,
                text='Delete all todos?',
            ),
        ),
    )

    view = _reduce(DomSnapshot(snapshot_id='hidden', root=root))
    locators = {fragment.ref.locator for fragment in view.fragments}

    assert dom_locator('empty-hidden') not in locators
    assert dom_locator('unknown-wrapper') in locators
    assert dom_locator('hidden-modal') in locators
    assert any('Delete all todos?' in fragment.summary for fragment in view.fragments)


def test_dom_inspect_and_expand_resolve_exact_snapshot_json() -> None:
    root = DomNode(
        node_id='root',
        tag='html',
        children=(
            DomNode(
                node_id='todo-list',
                tag='ul',
                declared_count=2,
                children=(_todo('todo-1', 'A'), _todo('todo-2', 'B')),
            ),
        ),
    )
    snapshot = DomSnapshot(snapshot_id='inspect', root=root)
    data = serialize_dom_snapshot(snapshot)
    store = MemoryArtifactStore()
    ref = store.put(
        snapshot_id='inspect',
        kind=EvidenceKind.RENDERED_DOM,
        media_type='application/json',
        data=data,
    )
    view = DomPruner().prune(PruningInput(source=ref, data=data), PruningPolicy())
    region = next(fragment for fragment in view.fragments if fragment.coverage is not None)
    manifest = ObservationSnapshot(
        run_id='run',
        episode_id='episode',
        snapshot_id='inspect',
        requested_profile=CaptureProfile.BROWSER_HEADLESS,
        artifacts=(ref,),
    )

    inspector = ObservationInspector(store, manifest)
    page = inspector.expand(region.ref, InspectionBudget(max_items=10))
    detail = inspector.inspect(page.members[1].ref, InspectionBudget())

    assert page.coverage.complete is True
    assert [member.label for member in page.members] == ['li.todo', 'li.todo']
    assert DomNode.model_validate_json(detail.content).text == 'B'


def test_duplicate_content_keys_fall_back_to_declared_positional_members() -> None:
    root = DomNode(
        node_id='root',
        tag='html',
        children=(
            DomNode(
                node_id='todo-list',
                tag='ul',
                children=(_todo('todo-1', 'same'), _todo('todo-2', 'same')),
            ),
        ),
    )
    snapshot = DomSnapshot(snapshot_id='duplicate-keys', root=root)
    data = serialize_dom_snapshot(snapshot)
    store = MemoryArtifactStore()
    ref = store.put(
        snapshot_id='duplicate-keys',
        kind=EvidenceKind.RENDERED_DOM,
        media_type='application/json',
        data=data,
    )
    view = DomPruner().prune(PruningInput(source=ref, data=data), PruningPolicy())
    region = next(fragment for fragment in view.fragments if fragment.coverage is not None)
    manifest = ObservationSnapshot(
        run_id='run',
        episode_id='episode',
        snapshot_id='duplicate-keys',
        requested_profile=CaptureProfile.BROWSER_HEADLESS,
        artifacts=(ref,),
    )

    page = ObservationInspector(store, manifest).expand(region.ref, InspectionBudget(max_items=10))

    assert 'some members are positional' in region.summary
    assert [member.stable for member in page.members] == [False, False]
    assert all('&ordinal=' in member.ref.locator for member in page.members)


def test_dom_expand_does_not_promote_container_count_for_state_subset() -> None:
    root = DomNode(
        node_id='root',
        tag='html',
        children=(
            DomNode(
                node_id='todo-list',
                tag='ul',
                declared_count=3,
                children=(_todo('todo-1', 'A'), _todo('todo-2', 'B'), _todo('todo-3', 'C', checked=True)),
            ),
        ),
    )
    snapshot = DomSnapshot(snapshot_id='mixed', root=root)
    data = serialize_dom_snapshot(snapshot)
    store = MemoryArtifactStore()
    ref = store.put(
        snapshot_id='mixed',
        kind=EvidenceKind.RENDERED_DOM,
        media_type='application/json',
        data=data,
    )
    view = DomPruner().prune(PruningInput(source=ref, data=data), PruningPolicy())
    region = next(fragment for fragment in view.fragments if fragment.coverage is not None)
    manifest = ObservationSnapshot(
        run_id='run',
        episode_id='episode',
        snapshot_id='mixed',
        requested_profile=CaptureProfile.BROWSER_HEADLESS,
        artifacts=(ref,),
    )

    page = ObservationInspector(store, manifest).expand(region.ref, InspectionBudget(max_items=10))

    assert page.coverage.declared is None
    assert page.coverage.complete is False


def _keyed_list_workload(
    snapshot_id: str, *, declared: int | None = 2
) -> tuple[MemoryArtifactStore, ObservationSnapshot, PrunedFragment]:
    """Build a two-member keyed region and return its store, manifest, and pruned region."""
    root = DomNode(
        node_id='root',
        tag='html',
        children=(
            DomNode(
                node_id='todo-list',
                tag='ul',
                declared_count=declared,
                children=(
                    DomNode(
                        node_id='todo-1',
                        tag='li',
                        attributes=(DomAttribute(name='class', value='todo'), DomAttribute(name='data-id', value='a')),
                        text='Buy milk',
                        visibility=DomVisibility.VISIBLE,
                    ),
                    DomNode(
                        node_id='todo-2',
                        tag='li',
                        attributes=(DomAttribute(name='class', value='todo'), DomAttribute(name='data-id', value='b')),
                        text='Ship beta',
                        visibility=DomVisibility.VISIBLE,
                    ),
                ),
            ),
        ),
    )
    data = serialize_dom_snapshot(DomSnapshot(snapshot_id=snapshot_id, root=root))
    store = MemoryArtifactStore()
    ref = store.put(
        snapshot_id=snapshot_id,
        kind=EvidenceKind.RENDERED_DOM,
        media_type='application/json',
        data=data,
    )
    view = DomPruner().prune(PruningInput(source=ref, data=data), PruningPolicy())
    region = next(fragment for fragment in view.fragments if fragment.coverage is not None)
    manifest = ObservationSnapshot(
        run_id='run',
        episode_id='episode',
        snapshot_id=snapshot_id,
        requested_profile=CaptureProfile.BROWSER_HEADLESS,
        artifacts=(ref,),
    )
    return store, manifest, region


def test_dom_rebind_carries_a_route_onto_another_member() -> None:
    """Rebinding a DOM member must resolve through the DOM, not through the HTML parser.

    The inspector read DOM JSON with lxml here, so a rebind naming a real member failed as
    'segment resolved to 0 nodes' — the address grammar blamed for a modality mistake.
    """
    store, manifest, region = _keyed_list_workload('rebind')
    inspector = ObservationInspector(store, manifest)
    exemplar = inspector.expand(region.ref, InspectionBudget(max_items=10)).members[0]

    rebound = inspector.rebind(exemplar.ref, 'data-id=b')
    detail = inspector.inspect(rebound, InspectionBudget())

    assert 'key=data-id%3Db' in rebound.locator
    assert DomNode.model_validate_json(detail.content).text == 'Ship beta'


def test_dom_rebind_refuses_a_key_no_member_carries() -> None:
    store, manifest, region = _keyed_list_workload('rebind-missing')
    inspector = ObservationInspector(store, manifest)
    exemplar = inspector.expand(region.ref, InspectionBudget(max_items=10)).members[0]

    with pytest.raises(ObservationAddressError, match='resolved to 0 members'):
        inspector.rebind(exemplar.ref, 'data-id=absent')


@pytest.mark.parametrize('declared', [2, 5, None])
def test_pruner_and_inspector_agree_on_region_coverage(declared: int | None) -> None:
    """One coverage rule, two consumers. Two formulations drift on `complete`."""
    store, manifest, region = _keyed_list_workload(f'coverage-{declared}', declared=declared)

    page = ObservationInspector(store, manifest).expand(region.ref, InspectionBudget(max_items=10))

    assert page.coverage == region.coverage


def test_expand_bounds_member_summaries_independently_of_the_byte_budget() -> None:
    store, manifest, region = _keyed_list_workload('summary-bound')

    page = ObservationInspector(store, manifest).expand(
        region.ref, InspectionBudget(max_bytes=32_000, max_summary_chars=12)
    )

    assert page.members
    assert all(len(member.summary) <= 12 for member in page.members)


def test_dom_inspection_rejects_payload_bound_to_another_snapshot() -> None:
    root = DomNode(node_id='root', tag='html')
    data = serialize_dom_snapshot(DomSnapshot(snapshot_id='payload', root=root))
    store = MemoryArtifactStore()
    ref = store.put(
        snapshot_id='manifest',
        kind=EvidenceKind.RENDERED_DOM,
        media_type='application/json',
        data=data,
    )
    manifest = ObservationSnapshot(
        run_id='run',
        episode_id='episode',
        snapshot_id='manifest',
        requested_profile=CaptureProfile.BROWSER_HEADLESS,
        artifacts=(ref,),
    )
    inspector = ObservationInspector(store, manifest)

    with pytest.raises(ValueError, match='payload snapshot disagrees'):
        DomPruner().prune(PruningInput(source=ref, data=data), PruningPolicy())
    with pytest.raises(ObservationAddressError, match='payload snapshot disagrees'):
        inspector.inspect(
            ref=RegionRef(
                snapshot_id='manifest',
                artifact_sha256=ref.sha256,
                modality=EvidenceKind.RENDERED_DOM,
                locator=dom_locator('root'),
            ),
            budget=InspectionBudget(),
        )


def test_shadow_root_and_portal_relationships_remain_addressable() -> None:
    root = DomNode(
        node_id='root',
        tag='html',
        children=(
            DomNode(
                node_id='app',
                tag='main',
                shadow_root=DomNode(
                    node_id='shadow-root',
                    tag='#shadow-root',
                    children=(DomNode(node_id='shadow-button', tag='button', text='Save'),),
                ),
            ),
            DomNode(node_id='portal-target', tag='div'),
            DomNode(node_id='dialog', tag='dialog', portal_target_id='portal-target', text='Confirm'),
        ),
    )

    view = _reduce(DomSnapshot(snapshot_id='boundaries', root=root))
    locators = {fragment.ref.locator for fragment in view.fragments}

    assert dom_locator('shadow-root') in locators
    assert dom_locator('shadow-button') in locators
    dialog = next(fragment for fragment in view.fragments if fragment.label == 'dialog')
    assert 'portal→portal-target' in dialog.summary
    assert parse_address(dialog.ref.locator).is_stable


def _deep_chain(depth: int) -> DomNode:
    """Build one element chain `depth` levels deep."""
    node = DomNode(node_id=f'd{depth}', tag='div', text='bottom')
    for level in range(depth - 1, -1, -1):
        node = DomNode(node_id=f'd{level}', tag='div', children=(node,))
    return node


def test_walk_discloses_where_it_stopped_descending() -> None:
    """A subtree the index never visited must be visible as an omission.

    Real pages reach 38 elements deep against a walk ceiling of 24, so this is reachable,
    not theoretical. Without the disclosure the deepest entry reports its child count and
    reads exactly like a fully indexed node, so a reader has no reason to inspect further.
    """
    view = _reduce(DomSnapshot(snapshot_id='deep', root=_deep_chain(MAX_DEPTH + 10)))

    assert 'below index depth' in (view.fragments[-1].summary or '')


def test_a_fully_indexed_tree_is_never_labelled_truncated() -> None:
    """The disclosure must mark real omissions only, or it stops meaning anything."""
    view = _reduce(DomSnapshot(snapshot_id='shallow', root=_deep_chain(3)))

    assert not any('below index depth' in (fragment.summary or '') for fragment in view.fragments)
