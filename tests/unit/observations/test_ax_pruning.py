"""Deterministic AX-pruner tests over small synthetic accessibility trees."""

from __future__ import annotations

import pytest

from yosoi.observations.artifacts import MemoryArtifactStore
from yosoi.observations.ax_tree import (
    DEFAULT_PROPERTY_VALUES,
    ax_attributes,
    ax_label,
    ax_locator,
    ax_member_variants,
    ax_region_coverage,
    ax_shape_signature,
    ax_subtree_text,
    node_id_from_locator,
)
from yosoi.observations.index.addressing import ObservationAddressError, parse_address, ref_id
from yosoi.observations.index.inspect import InspectionBudget, ObservationInspector
from yosoi.observations.index.paging import PageRequest
from yosoi.observations.models import (
    AxCapability,
    AxCapabilityKind,
    AxNode,
    AxProperty,
    AxRelation,
    AxRelationKind,
    AxSnapshot,
    CaptureProfile,
    EvidenceKind,
    ObservationSnapshot,
    RegionRef,
)
from yosoi.observations.models.ax import serialize_ax_snapshot
from yosoi.observations.pruning import AxPruner, PruningInput, PruningPolicy
from yosoi.observations.pruning.ax import MAX_DEPTH


def _snapshot(nodes: tuple[AxNode, ...], *, snapshot_id: str = 'snap', capabilities=()) -> AxSnapshot:
    return AxSnapshot(snapshot_id=snapshot_id, root_id=nodes[0].node_id, nodes=nodes, capabilities=capabilities)


def _checkbox(node_id: str, name: str, *, checked: bool, extra: tuple[AxProperty, ...] = ()) -> AxNode:
    return AxNode(
        node_id=node_id,
        parent_id='root',
        role='checkbox',
        name=name,
        properties=(AxProperty(name='checked', value='true' if checked else 'false'), *extra),
    )


def _form(count: int = 4) -> AxSnapshot:
    """A group of checkboxes that differ only in `checked`."""
    members = tuple(_checkbox(f'c{i}', f'Task {i}', checked=i % 2 == 0) for i in range(count))
    root = AxNode(
        node_id='root',
        role='group',
        name='Tasks',
        child_ids=tuple(member.node_id for member in members),
        properties=(AxProperty(name='setsize', value=str(count)),),
    )
    return _snapshot((root, *members))


def _prune(snapshot: AxSnapshot, policy: PruningPolicy | None = None, page: PageRequest | None = None):
    data = serialize_ax_snapshot(snapshot)
    artifact = MemoryArtifactStore().put(
        snapshot_id=snapshot.snapshot_id, kind=EvidenceKind.AX_TREE, media_type='application/json', data=data
    )
    return AxPruner().prune(PruningInput(source=artifact, data=data), policy or PruningPolicy(), page)


def _bind(snapshot: AxSnapshot):
    data = serialize_ax_snapshot(snapshot)
    store = MemoryArtifactStore()
    artifact = store.put(
        snapshot_id=snapshot.snapshot_id, kind=EvidenceKind.AX_TREE, media_type='application/json', data=data
    )
    manifest = ObservationSnapshot(
        run_id='r',
        episode_id='e',
        snapshot_id=snapshot.snapshot_id,
        requested_profile=CaptureProfile.BROWSER_HEADLESS,
        artifacts=(artifact,),
    )
    view = AxPruner().prune(PruningInput(source=artifact, data=data), PruningPolicy())
    return view, ObservationInspector(store, manifest)


def test_the_pruner_identifies_itself_and_its_modality() -> None:
    pruner = AxPruner()
    assert pruner.name == 'ax'
    assert pruner.version != 'scaffold'
    assert pruner.evidence_kind is EvidenceKind.AX_TREE


def test_a_payload_must_agree_with_its_artifact() -> None:
    snapshot = _form()
    data = serialize_ax_snapshot(snapshot)
    artifact = MemoryArtifactStore().put(
        snapshot_id='a-different-capture', kind=EvidenceKind.AX_TREE, media_type='application/json', data=data
    )
    with pytest.raises(ValueError, match='disagrees with its artifact'):
        AxPruner().prune(PruningInput(source=artifact, data=data), PruningPolicy())


def test_identical_input_and_policy_produce_byte_identical_output() -> None:
    first, second = _prune(_form()), _prune(_form())
    assert first.model_dump_json() == second.model_dump_json()


def test_shape_ignores_names_values_and_state_values() -> None:
    """The DOM pruner's measured mistake, refused here: discriminants are not shape."""
    left = _checkbox('a', 'Buy milk', checked=True)
    right = _checkbox('b', 'Ship beta', checked=False)
    assert ax_shape_signature(left, {}) == ax_shape_signature(right, {})


def test_shape_separates_levels_because_a_heading_level_is_structure() -> None:
    def heading(node_id: str, level: str) -> AxNode:
        return AxNode(node_id=node_id, role='heading', name='x', properties=(AxProperty(name='level', value=level),))

    assert ax_shape_signature(heading('a', '1'), {}) != ax_shape_signature(heading('b', '2'), {})


def test_shape_separates_the_ignored_band_from_the_live_one() -> None:
    live = AxNode(node_id='a', role='button', name='Delete')
    hidden = AxNode(
        node_id='b',
        role='button',
        name='Delete',
        ignored=True,
        ignored_reasons=(AxProperty(name='ariaHiddenElement', value='true'),),
    )
    assert ax_shape_signature(live, {}) != ax_shape_signature(hidden, {})


def test_a_run_of_same_shape_controls_collapses_to_one_region() -> None:
    view = _prune(_form(count=6))
    regions = [fragment for fragment in view.fragments if fragment.coverage is not None]

    assert len(regions) == 1
    assert regions[0].coverage is not None
    assert regions[0].coverage.observed == 6
    assert regions[0].coverage.declared == 6
    assert regions[0].coverage.complete is True
    # Six controls cost the region entry alone: a childless member's exemplar would only restate it.
    assert len(view.fragments) == 2


def test_a_collapsed_region_reports_the_state_it_collapsed_over() -> None:
    view = _prune(_form(count=4))
    region = next(fragment for fragment in view.fragments if fragment.coverage is not None)
    assert 'checked=true×2' in region.summary
    assert 'checked=false×2' in region.summary


def test_members_that_share_every_state_say_so_rather_than_saying_nothing() -> None:
    members = tuple(AxNode(node_id=f'm{i}', parent_id='root', role='listitem', name=f'Item {i}') for i in range(3))
    root = AxNode(node_id='root', role='list', name='Items', child_ids=tuple(member.node_id for member in members))
    region = next(f for f in _prune(_snapshot((root, *members))).fragments if f.coverage is not None)
    assert 'members share every state' in region.summary


def test_ignored_nodes_are_emitted_with_the_browsers_own_reason() -> None:
    hidden = AxNode(
        node_id='hidden',
        parent_id='root',
        role='button',
        ignored=True,
        ignored_reasons=(AxProperty(name='ariaHiddenElement', value='true'),),
    )
    root = AxNode(node_id='root', role='RootWebArea', name='Doc', child_ids=('hidden',))
    view = _prune(_snapshot((root, hidden)))

    entry = next(fragment for fragment in view.fragments if 'ignored[' in fragment.summary)
    assert 'ariaHiddenElement' in entry.summary
    # No keep/drop predicate: the ignored node is addressable like anything else.
    assert view.stats.retained_items == 2


def test_relationships_are_reported_as_edges_with_their_targets() -> None:
    root = AxNode(node_id='root', role='RootWebArea', name='Doc', child_ids=('tab', 'panel'))
    tab = AxNode(
        node_id='tab',
        parent_id='root',
        role='tab',
        name='One',
        relations=(AxRelation(kind=AxRelationKind.CONTROLS, target_node_id='panel'),),
    )
    panel = AxNode(node_id='panel', parent_id='root', role='tabpanel', name='One panel')
    view = _prune(_snapshot((root, tab, panel)))

    entry = next(fragment for fragment in view.fragments if fragment.label.startswith('tab '))
    assert 'controls→tabpanel "One panel"' in entry.summary


def test_an_unresolvable_relationship_is_reported_rather_than_hidden() -> None:
    root = AxNode(
        node_id='root',
        role='RootWebArea',
        name='Doc',
        relations=(AxRelation(kind=AxRelationKind.LABELLED_BY, target_text='missing-id'),),
    )
    view = _prune(_snapshot((root,)))
    assert 'labelledby→(unresolved "missing-id")' in view.fragments[0].summary


def test_default_states_are_omitted_and_declared_once_on_the_root() -> None:
    node = AxNode(
        node_id='child',
        parent_id='root',
        role='button',
        name='Save',
        properties=(AxProperty(name='focusable', value=DEFAULT_PROPERTY_VALUES['focusable']),),
    )
    root = AxNode(node_id='root', role='RootWebArea', name='Doc', child_ids=('child',))
    view = _prune(_snapshot((root, node)))

    entry = next(fragment for fragment in view.fragments if fragment.label == 'button "Save"')
    assert 'focusable' not in entry.summary
    assert 'default states omitted' in view.fragments[0].summary


def test_a_state_that_departs_from_the_default_is_printed() -> None:
    node = AxNode(
        node_id='child',
        parent_id='root',
        role='button',
        name='Save',
        properties=(AxProperty(name='focusable', value='false'),),
    )
    root = AxNode(node_id='root', role='RootWebArea', name='Doc', child_ids=('child',))
    view = _prune(_snapshot((root, node)))
    entry = next(fragment for fragment in view.fragments if fragment.label == 'button "Save"')
    assert 'focusable=false' in entry.summary


def test_the_root_entry_states_that_ax_absence_proves_nothing() -> None:
    view = _prune(
        _form(),
    )
    assert 'AX absence is never proof that visible information does not exist' in view.fragments[0].summary


def test_unavailable_capabilities_are_named_in_the_conventions() -> None:
    snapshot = _snapshot(
        (AxNode(node_id='root', role='RootWebArea', name='Doc'),),
        capabilities=(
            AxCapability(
                kind=AxCapabilityKind.DOM_CORRELATION, available=False, reason='no shared join key with the DOM'
            ),
        ),
    )
    assert 'dom_correlation unavailable (no shared join key with the DOM)' in _prune(snapshot).fragments[0].summary


def test_a_label_is_an_executable_click_by_role_target() -> None:
    # Two same-named buttons in differently shaped groups, so neither run collapses and both
    # buttons get their own entry — which is the only case where an occurrence index matters.
    buttons = tuple(AxNode(node_id=f'b{i}', parent_id=f'g{i}', role='button', name='Delete') for i in range(2))
    note = AxNode(node_id='note', parent_id='g1', role='StaticText', name='careful')
    groups = (
        AxNode(node_id='g0', parent_id='root', role='group', name='A', child_ids=('b0',)),
        AxNode(node_id='g1', parent_id='root', role='group', name='B', child_ids=('b1', 'note')),
    )
    root = AxNode(node_id='root', role='RootWebArea', name='Doc', child_ids=('g0', 'g1'))
    view = _prune(_snapshot((root, *groups, *buttons, note)))

    labels = [fragment.label for fragment in view.fragments]
    assert 'button "Delete"' in labels
    # The occurrence index appears only where it changes what would be clicked.
    assert any(label.endswith('#1') for label in labels)
    assert ax_label(buttons[0]) == 'button "Delete"'
    assert ax_label(buttons[1], nth=1) == 'button "Delete" #1'


def test_addresses_are_anchored_on_the_accessible_name_and_earn_an_identity() -> None:
    view = _prune(_form())
    region = next(fragment for fragment in view.fragments if fragment.coverage is not None)
    address = parse_address(region.ref.locator)

    assert address.is_anchored
    assert address.segments[0].anchor == 'name=Tasks'
    assert ref_id(EvidenceKind.AX_TREE, region.ref.locator) is not None


def test_a_node_the_tree_cannot_name_is_refused_an_identity_but_still_resolves() -> None:
    unnamed = tuple(AxNode(node_id=f'g{i}', parent_id='root', role='generic') for i in range(2))
    root = AxNode(node_id='root', role='generic', child_ids=('g0', 'g1'))
    view, inspector = _bind(_snapshot((root, *unnamed)))

    positional = [fragment for fragment in view.fragments if ref_id(EvidenceKind.AX_TREE, fragment.ref.locator) is None]
    assert positional, 'a tree offering no unique key must refuse at least one identity'
    assert inspector.inspect(positional[0].ref, InspectionBudget()).returned_bytes > 0


def test_two_captures_of_one_tree_agree_on_identity_and_differ_on_location() -> None:
    first = _prune(_form(), None)
    second = _prune(_form(count=4).model_copy(update={'snapshot_id': 'other'}))

    assert [f.ref for f in first.fragments] != [f.ref for f in second.fragments]
    assert [ref_id(EvidenceKind.AX_TREE, f.ref.locator) for f in first.fragments] == [
        ref_id(EvidenceKind.AX_TREE, f.ref.locator) for f in second.fragments
    ]


def test_expand_returns_durably_keyed_members_and_inspect_returns_canonical_bytes() -> None:
    view, inspector = _bind(_form(count=5))
    region = next(fragment for fragment in view.fragments if fragment.coverage is not None)
    page = inspector.expand(region.ref, InspectionBudget())

    assert [member.label for member in page.members] == [f'checkbox "Task {i}"' for i in range(5)]
    assert all(member.stable for member in page.members)
    assert page.coverage.declared == 5
    detail = AxNode.model_validate_json(inspector.inspect(page.members[3].ref, InspectionBudget()).content)
    assert detail.name == 'Task 3'


def test_expand_pages_a_region_and_reports_truncation() -> None:
    view, inspector = _bind(_form(count=5))
    region = next(fragment for fragment in view.fragments if fragment.coverage is not None)
    first = inspector.expand(region.ref, InspectionBudget(max_items=2))
    rest = inspector.expand(region.ref, InspectionBudget(max_items=2), offset=2)

    assert first.truncated is True
    assert [member.ordinal for member in rest.members] == [2, 3]


def test_rebinding_carries_an_exemplar_route_onto_another_member() -> None:
    """Nested regions: the walk descends into one member, and identity does the rest."""
    rows = []
    cells = []
    for row in range(2):
        rows.append(
            AxNode(
                node_id=f'r{row}',
                parent_id='grid',
                role='row',
                name=f'Row {row}',
                child_ids=(f'r{row}c0', f'r{row}c1'),
            )
        )
        cells.extend(
            AxNode(
                node_id=f'r{row}c{column}',
                parent_id=f'r{row}',
                role='gridcell',
                name=f'cell {row}-{column}',
            )
            for column in range(2)
        )
    grid = AxNode(node_id='grid', role='grid', name='Deploys', child_ids=('r0', 'r1'))
    view, inspector = _bind(_snapshot((grid, *rows, *cells)))

    outer = next(fragment for fragment in view.fragments if fragment.coverage is not None)
    member = inspector.expand(outer.ref, InspectionBudget()).members[0]
    rebound = inspector.rebind(member.ref, 'name=Row 1')
    assert AxNode.model_validate_json(inspector.inspect(rebound, InspectionBudget()).content).name == 'Row 1'


def test_a_malformed_or_foreign_reference_fails_closed() -> None:
    view, inspector = _bind(_form())
    ref = view.fragments[0].ref
    with pytest.raises(ObservationAddressError):
        inspector.inspect(ref.model_copy(update={'snapshot_id': 'elsewhere'}), InspectionBudget())
    with pytest.raises(ObservationAddressError):
        inspector.inspect(
            RegionRef(
                snapshot_id=ref.snapshot_id,
                artifact_sha256=ref.artifact_sha256,
                modality=EvidenceKind.AX_TREE,
                locator=ax_locator('absent-node'),
            ),
            InspectionBudget(),
        )


def test_paging_tiles_the_candidate_space_exactly() -> None:
    snapshot = _form(count=3)
    total = _prune(snapshot).page.total
    seen: list[int] = []
    offset = 0
    while offset < total:
        page = _prune(snapshot, PruningPolicy(), PageRequest(offset=offset, limit=1))
        seen.extend(fragment.ordinal for fragment in page.fragments)
        offset = page.page.offset + page.page.returned
    assert seen == list(range(total))


def test_accounting_never_claims_more_than_the_tree_held() -> None:
    view = _prune(_form(count=6))
    assert view.stats.source_items == 7
    assert view.stats.retained_items <= view.stats.source_items
    assert view.stats.retained_items + view.stats.omitted_items == view.stats.source_items


def test_coverage_is_only_claimed_when_the_declaration_covers_the_whole_collection() -> None:
    members = tuple(AxNode(node_id=f'o{i}', parent_id='list', role='option', name=f'Option {i}') for i in range(2))
    header = AxNode(node_id='header', parent_id='list', role='columnheader', name='Header')
    container = AxNode(
        node_id='list',
        role='listbox',
        name='Options',
        child_ids=('header', 'o0', 'o1'),
        properties=(AxProperty(name='setsize', value='50'),),
    )
    # Two of three children are the run, so the container's declared total describes something else.
    assert ax_region_coverage(container, members).declared is None
    assert ax_region_coverage(container, (header, *members)).declared == 50


def test_the_walk_discloses_where_it_stopped_descending() -> None:
    depth = MAX_DEPTH + 3
    nodes = [
        AxNode(node_id='n0', role='generic', name='root', child_ids=('n1',)),
        *(
            AxNode(
                node_id=f'n{level}',
                parent_id=f'n{level - 1}',
                role='generic',
                name='deepest' if level == depth else f'level {level}',
                child_ids=(f'n{level + 1}',) if level < depth else (),
            )
            for level in range(1, depth + 1)
        ),
    ]
    view = _prune(_snapshot(tuple(nodes)))

    assert any('below index depth' in fragment.summary for fragment in view.fragments)
    assert not any('deepest' in fragment.label for fragment in view.fragments)


def test_locators_round_trip_and_reject_foreign_paths() -> None:
    assert node_id_from_locator(ax_locator('a/b c')) == 'a/b c'
    with pytest.raises(ValueError, match='not an accessibility-tree locator'):
        node_id_from_locator('/dom/node/1')


def test_attribute_order_leads_with_the_accessible_name() -> None:
    """Order is the identity decision: the shared recipe uses only the first attribute."""
    node = AxNode(
        node_id='1',
        role='button',
        name='Save',
        properties=(AxProperty(name='focusable', value='true'),),
    )
    assert ax_attributes(node)[0] == ('name', 'Save')
    assert ax_attributes(AxNode(node_id='2', role='generic'))[0] == ('role', 'generic')


def test_subtree_text_collapses_the_repeated_text_shell() -> None:
    text = AxNode(node_id='t', parent_id='b', role='StaticText', name='Promote')
    button = AxNode(node_id='b', role='button', name='Promote', child_ids=('t',))
    assert ax_subtree_text(button, {'b': button, 't': text}) == 'Promote'


def test_variants_look_below_the_repeated_element() -> None:
    """State often lives one level down, in the control a wrapper repeats around."""
    wrappers = []
    boxes = []
    for index in range(2):
        wrappers.append(AxNode(node_id=f'w{index}', parent_id='root', role='none', child_ids=(f'c{index}',)))
        boxes.append(
            AxNode(
                node_id=f'c{index}',
                parent_id=f'w{index}',
                role='checkbox',
                name=f'Box {index}',
                properties=(AxProperty(name='checked', value='true' if index else 'false'),),
            )
        )
    root = AxNode(node_id='root', role='group', name='Boxes', child_ids=('w0', 'w1'))
    snapshot = _snapshot((root, *wrappers, *boxes))
    variants = ax_member_variants(wrappers, snapshot.by_id)
    assert 'checked=true×1' in variants
    assert 'checked=false×1' in variants
