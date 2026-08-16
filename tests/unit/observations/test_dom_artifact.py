"""Phase-1 contract tests for the structured rendered-DOM artifact."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from yosoi.observations.models import (
    DomAttribute,
    DomCapability,
    DomCapabilityKind,
    DomGeometry,
    DomNode,
    DomRuntimeState,
    DomSnapshot,
    DomVisibility,
)
from yosoi.observations.models.dom import MAX_PARSED_DEPTH, parse_dom_snapshot, serialize_dom_snapshot


def _snapshot() -> DomSnapshot:
    portal_target = DomNode(node_id='modal-root', tag='div', visibility=DomVisibility.VISIBLE)
    shadow = DomNode(
        node_id='shadow-root',
        tag='#shadow-root',
        children=(DomNode(node_id='shadow-button', tag='button', text='Save'),),
    )
    root = DomNode(
        node_id='document',
        tag='html',
        attributes=(DomAttribute(name='lang', value='en'),),
        children=(
            DomNode(
                node_id='app',
                tag='main',
                declared_count=10_000,
                visibility=DomVisibility.VISIBLE,
                geometry=DomGeometry(x=0, y=0, width=800, height=600, in_viewport=True),
                children=(
                    DomNode(
                        node_id='row-1',
                        tag='article',
                        text='First row',
                        runtime=DomRuntimeState(selected=True),
                    ),
                    DomNode(node_id='row-2', tag='article', text='Second row', visibility=DomVisibility.OFFSCREEN),
                ),
                shadow_root=shadow,
            ),
            portal_target,
            DomNode(node_id='modal', tag='dialog', portal_target_id='modal-root'),
        ),
    )
    return DomSnapshot(
        snapshot_id='snapshot-1',
        root=root,
        capabilities=(
            DomCapability(kind=DomCapabilityKind.VISIBILITY, available=True),
            DomCapability(
                kind=DomCapabilityKind.DECLARED_COUNTS, available=False, reason='producer did not expose ARIA counts'
            ),
        ),
        viewport_width=800,
        viewport_height=600,
    )


def test_dom_snapshot_is_deterministic_and_round_trips() -> None:
    snapshot = _snapshot()

    encoded = serialize_dom_snapshot(snapshot)

    assert encoded == serialize_dom_snapshot(snapshot)
    assert parse_dom_snapshot(encoded) == snapshot
    assert snapshot.observed_node_count == 8
    assert b'"visibility":"offscreen"' in encoded
    assert b'"selected":true' in encoded
    assert b'"portal_target_id":"modal-root"' in encoded


def test_dom_snapshot_is_frozen() -> None:
    with pytest.raises(ValidationError, match='frozen'):
        _snapshot().snapshot_id = 'other'  # type: ignore[misc]


def test_unavailable_capability_requires_reason() -> None:
    with pytest.raises(ValidationError, match='must state a reason'):
        DomCapability(kind=DomCapabilityKind.SHADOW_DOM, available=False)


def test_dom_snapshot_rejects_duplicate_node_ids() -> None:
    root = DomNode(
        node_id='root',
        tag='html',
        children=(DomNode(node_id='same', tag='div'), DomNode(node_id='same', tag='span')),
    )

    with pytest.raises(ValidationError, match='node ids must be unique'):
        DomSnapshot(snapshot_id='snapshot-1', root=root)


def test_dom_snapshot_rejects_dangling_portal_target() -> None:
    root = DomNode(
        node_id='root', tag='html', children=(DomNode(node_id='dialog', tag='dialog', portal_target_id='missing'),)
    )

    with pytest.raises(ValidationError, match='portal targets do not resolve'):
        DomSnapshot(snapshot_id='snapshot-1', root=root)


def test_dom_snapshot_preserves_ordered_attributes_and_runtime_state() -> None:
    snapshot = _snapshot()
    node = snapshot.root.children[0].children[0]

    assert node.runtime is not None
    assert node.runtime.selected is True
    assert [attribute.name for attribute in snapshot.root.attributes] == ['lang']

    with pytest.raises(ValidationError, match='duplicate attributes'):
        DomNode(
            node_id='duplicate-attrs',
            tag='div',
            attributes=(DomAttribute(name='class', value='a'), DomAttribute(name='class', value='b')),
        )


def _chain(depth: int) -> DomNode:
    """Build one element chain `depth` levels deep."""
    node = DomNode(node_id=f'n{depth}', tag='div', text='leaf')
    for level in range(depth - 1, -1, -1):
        node = DomNode(node_id=f'n{level}', tag='div', children=(node,))
    return node


def test_dom_snapshot_parses_at_the_stated_depth_limit() -> None:
    """MAX_PARSED_DEPTH is a measured fact, so it must stay true as pydantic moves."""
    data = serialize_dom_snapshot(DomSnapshot(snapshot_id='deep', root=_chain(MAX_PARSED_DEPTH)))

    assert parse_dom_snapshot(data).snapshot_id == 'deep'


def test_dom_snapshot_names_the_depth_limit_instead_of_leaking_a_json_error() -> None:
    """A page that nests too far is a capture problem, not a corrupt artifact.

    The parser's own message talks about JSON recursion, which sends the reader looking
    for malformed bytes that are not there.
    """
    data = serialize_dom_snapshot(DomSnapshot(snapshot_id='deep', root=_chain(MAX_PARSED_DEPTH + 1)))

    with pytest.raises(ValueError, match=f'nests deeper than {MAX_PARSED_DEPTH} elements'):
        parse_dom_snapshot(data)


def test_dom_snapshot_still_reports_ordinary_validation_failures() -> None:
    """The depth branch must not swallow every other way a payload can be wrong."""
    with pytest.raises(ValidationError, match='snapshot_id'):
        parse_dom_snapshot(b'{"schema_version":"dom1","kind":"rendered_dom"}')
