"""Unit tests for the canonical accessibility-tree artifact contract."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from yosoi.observations.models.ax import (
    AX_SCHEMA_VERSION,
    AxCapability,
    AxCapabilityKind,
    AxNode,
    AxProperty,
    AxRelation,
    AxRelationKind,
    AxSnapshot,
    parse_ax_snapshot,
    serialize_ax_snapshot,
)


def _pair(**overrides) -> AxSnapshot:
    """Return a minimal valid two-node snapshot, with fields overridable per test."""
    nodes = (
        AxNode(node_id='1', role='RootWebArea', name='Doc', child_ids=('2',)),
        AxNode(node_id='2', parent_id='1', role='button', name='Save'),
    )
    return AxSnapshot(snapshot_id='snap', root_id='1', nodes=nodes, **overrides)


def test_snapshot_declares_its_schema_and_kind() -> None:
    snapshot = _pair()
    assert snapshot.schema_version == AX_SCHEMA_VERSION
    assert snapshot.kind == 'ax_tree'
    assert snapshot.observed_node_count == 2
    assert snapshot.ignored_node_count == 0


def test_serialization_round_trips_deterministically() -> None:
    snapshot = _pair()
    data = serialize_ax_snapshot(snapshot)
    assert serialize_ax_snapshot(snapshot) == data
    assert parse_ax_snapshot(data) == snapshot


def test_unknown_fields_are_refused() -> None:
    with pytest.raises(ValidationError):
        AxNode.model_validate({'node_id': '1', 'chromeRole': 'button'})


def test_an_unavailable_capability_must_state_a_reason() -> None:
    with pytest.raises(ValidationError):
        AxCapability(kind=AxCapabilityKind.PROPERTIES, available=False)
    assert AxCapability(kind=AxCapabilityKind.PROPERTIES, available=False, reason='not requested').reason


def test_visible_text_coverage_can_never_be_declared_available() -> None:
    """The doctrine as an invariant: AX absence is never proof of visible absence."""
    with pytest.raises(ValidationError):
        AxCapability(kind=AxCapabilityKind.VISIBLE_TEXT_COVERAGE, available=True)


def test_capabilities_are_unique_per_kind() -> None:
    with pytest.raises(ValidationError):
        _pair(
            capabilities=(
                AxCapability(kind=AxCapabilityKind.PROPERTIES, available=True),
                AxCapability(kind=AxCapabilityKind.PROPERTIES, available=False, reason='conflicting'),
            )
        )


def test_the_graph_must_agree_with_itself() -> None:
    with pytest.raises(ValidationError, match='names absent child'):
        AxSnapshot(
            snapshot_id='s',
            root_id='1',
            nodes=(AxNode(node_id='1', role='RootWebArea', child_ids=('missing',)),),
        )
    with pytest.raises(ValidationError, match='disagrees with parent'):
        AxSnapshot(
            snapshot_id='s',
            root_id='1',
            nodes=(
                AxNode(node_id='1', role='RootWebArea', child_ids=('2',)),
                AxNode(node_id='2', parent_id='other', role='button'),
            ),
        )
    with pytest.raises(ValidationError, match='does not list child'):
        AxSnapshot(
            snapshot_id='s',
            root_id='1',
            nodes=(
                AxNode(node_id='1', role='RootWebArea'),
                AxNode(node_id='2', parent_id='1', role='button'),
            ),
        )


def test_nodes_unreachable_from_the_root_are_refused() -> None:
    with pytest.raises(ValidationError, match='unreachable from the root'):
        AxSnapshot(
            snapshot_id='s',
            root_id='1',
            nodes=(
                AxNode(node_id='1', role='RootWebArea'),
                AxNode(node_id='2', parent_id='3', role='button', child_ids=('3',)),
                AxNode(node_id='3', parent_id='2', role='text', child_ids=('2',)),
            ),
        )


def test_the_root_may_not_declare_a_parent() -> None:
    with pytest.raises(ValidationError, match='declares a parent'):
        AxSnapshot(
            snapshot_id='s',
            root_id='2',
            nodes=(
                AxNode(node_id='1', role='RootWebArea', child_ids=('2',)),
                AxNode(node_id='2', parent_id='1', role='button'),
            ),
        )


def test_a_relation_target_inside_the_snapshot_must_exist() -> None:
    with pytest.raises(ValidationError, match='names absent node'):
        AxSnapshot(
            snapshot_id='s',
            root_id='1',
            nodes=(
                AxNode(
                    node_id='1',
                    role='RootWebArea',
                    relations=(AxRelation(kind=AxRelationKind.LABELLED_BY, target_node_id='nope'),),
                ),
            ),
        )


def test_a_relation_whose_target_is_outside_the_tree_is_kept_not_dropped() -> None:
    """An `aria-labelledby` naming something with no AX node is the defect, not a parse error."""
    relation = AxRelation(kind=AxRelationKind.LABELLED_BY, target_text='missing-id')
    snapshot = AxSnapshot(
        snapshot_id='s',
        root_id='1',
        nodes=(AxNode(node_id='1', role='RootWebArea', relations=(relation,)),),
    )
    assert snapshot.root.relations[0].target_node_id is None
    assert snapshot.root.relations[0].target_text == 'missing-id'


def test_a_relation_must_name_some_target() -> None:
    with pytest.raises(ValidationError, match='names no target'):
        AxRelation(kind=AxRelationKind.CONTROLS)


def test_ignored_reasons_require_the_ignored_flag() -> None:
    with pytest.raises(ValidationError, match='without being ignored'):
        AxNode(node_id='1', role='button', ignored_reasons=(AxProperty(name='ariaHiddenElement', value='true'),))


def test_ignored_nodes_are_retained_as_a_band_with_their_reasons() -> None:
    snapshot = AxSnapshot(
        snapshot_id='s',
        root_id='1',
        nodes=(
            AxNode(node_id='1', role='RootWebArea', child_ids=('2',)),
            AxNode(
                node_id='2',
                parent_id='1',
                role='none',
                ignored=True,
                ignored_reasons=(AxProperty(name='ariaHiddenElement', value='true'),),
            ),
        ),
    )
    assert snapshot.ignored_node_count == 1
    assert snapshot.observed_node_count == 2
    assert snapshot.by_id['2'].ignored_reasons[0].name == 'ariaHiddenElement'


def test_duplicate_properties_and_children_are_refused() -> None:
    with pytest.raises(ValidationError, match='duplicate properties'):
        AxNode(
            node_id='1',
            role='button',
            properties=(AxProperty(name='checked', value='true'), AxProperty(name='checked', value='false')),
        )
    with pytest.raises(ValidationError, match='lists a child twice'):
        AxNode(node_id='1', role='button', child_ids=('2', '2'))
    with pytest.raises(ValidationError, match='its own child'):
        AxNode(node_id='1', role='button', child_ids=('1',))


def test_state_names_are_the_shape_and_carry_no_values() -> None:
    node = AxNode(
        node_id='1',
        role='checkbox',
        properties=(AxProperty(name='focusable', value='true'), AxProperty(name='checked', value='true')),
    )
    assert node.state_names == ('checked', 'focusable')


def test_the_snapshot_is_frozen() -> None:
    snapshot = _pair()
    with pytest.raises(ValidationError):
        snapshot.snapshot_id = 'other'
