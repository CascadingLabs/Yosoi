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
from yosoi.observations.pruning import DomPruner, PruningInput, PruningPolicy


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
