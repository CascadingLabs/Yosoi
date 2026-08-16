"""Versioned structured artifacts for one raw accessibility-tree capture.

The canonical artifact is RAW AX evidence, as CDP's `Accessibility.getFullAXTree` reports it: a
flat node list carrying `nodeId`/`parentId`/`childIds`, the computed `role`/`name`/`value`/
`description`, the node's `properties`, and — the part every compaction throws away first —
`ignored` plus `ignoredReasons`.

`yosoi/core/fetcher/dom/ax.py` already has an `AxSnapshot`, and it is deliberately not reused
here: it drops ignored nodes, keeps only role/name pairs it can click, and exists to detect
triggers. That is a *view*. `ignoredReasons` is the finding a QA reader most needs — "this
button is `aria-hidden`" is a defect, not noise — so it has to survive into canonical evidence,
and evidence has to be preserved before anything compacts it.

Three shape decisions that are not incidental:

* **Flat, not nested.** The producer's own shape. It also sidesteps the recursive-JSON depth
  ceiling `models/dom.py` documents as `MAX_PARSED_DEPTH`: an AX tree of any depth is one list.
* **A graph, not a tree.** `labelledby`, `describedby`, `controls`, `owns`, `activedescendant`,
  `flowto`, `details`, and `errormessage` all cross the hierarchy. They are explicit edge facts,
  the way `DomNode.shadow_root` and `portal_target_id` are, and are never flattened into
  `child_ids` — a label that lives elsewhere in the document is exactly the relationship a
  reader is asking about.
* **Ignored nodes are a band, never a filter.** They stay in `nodes` with their reasons attached.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

AX_SCHEMA_VERSION = 'ax1'


class AxCapabilityKind(str, Enum):
    """Facts an accessibility-tree producer may or may not have captured."""

    IGNORED_NODES = 'ignored_nodes'
    """Whether nodes the browser ignored were retained with their reasons."""

    PROPERTIES = 'properties'
    """Whether computed ARIA states and properties were captured per node."""

    RELATIONSHIPS = 'relationships'
    """Whether cross-hierarchy edges (labelledby, controls, owns, …) were captured."""

    DOM_CORRELATION = 'dom_correlation'
    """Whether an AX node can be joined to a node of the rendered-DOM artifact.

    `backendDOMNodeId` is the join key the browser offers, and our DOM artifact addresses nodes
    by JS-walk path ids instead, so nothing on either side can be matched to the other today.
    Declared explicitly and unavailable rather than omitted: a cross-modal contradiction that
    cannot be computed must read as "not measured", never as "no contradiction found".
    """

    VISIBLE_TEXT_COVERAGE = 'visible_text_coverage'
    """Whether the AX tree is a complete account of the page's visible information.

    Structurally never available, and the validator enforces that. The browser omits from the AX
    tree whatever it judges non-semantic — presentational containers, decorative images, text it
    folds into an ancestor's computed name — so a thing's absence from AX is a statement about the
    browser's accessibility computation and not about the page. Encoded as a capability because a
    comment cannot be read by a consumer deciding how far to trust an empty result.
    """

    FRAME_TRAVERSAL = 'frame_traversal'
    """Whether accessibility trees of nested frames were captured alongside the main frame."""


class AxCapability(BaseModel):
    """Explicit availability for one accessibility-capture capability."""

    model_config = ConfigDict(frozen=True, extra='forbid')

    kind: AxCapabilityKind
    available: bool
    reason: str | None = None

    @model_validator(mode='after')
    def _require_reason_when_unavailable(self) -> AxCapability:
        if not self.available and not self.reason:
            raise ValueError('an unavailable AX capability must state a reason')
        if self.kind is AxCapabilityKind.VISIBLE_TEXT_COVERAGE and self.available:
            raise ValueError(
                'AX absence is never proof that visible information does not exist; '
                'visible_text_coverage cannot be declared available'
            )
        return self


class AxRelationKind(str, Enum):
    """Cross-hierarchy accessibility edges, kept as edges rather than as children."""

    LABELLED_BY = 'labelledby'
    DESCRIBED_BY = 'describedby'
    CONTROLS = 'controls'
    OWNS = 'owns'
    ACTIVE_DESCENDANT = 'activedescendant'
    FLOW_TO = 'flowto'
    DETAILS = 'details'
    ERROR_MESSAGE = 'errormessage'


class AxProperty(BaseModel):
    """One computed accessibility property, with its value flattened to text.

    CDP wraps every value in an `AXValue` carrying a type and, for relationship properties, a
    list of related nodes. The type is not retained: what discriminates one control from another
    is `checked=true` versus `checked=false`, and the related-node lists are modelled as
    `AxRelation` edges instead of being buried inside a property's value.
    """

    model_config = ConfigDict(frozen=True, extra='forbid')

    name: str = Field(min_length=1)
    value: str


class AxRelation(BaseModel):
    """One explicit accessibility edge from a node to something it points at.

    The target is described by whatever the producer could resolve. All three fields can be
    thin at once and the edge still matters: `aria-labelledby` naming an id that does not
    exist is a real accessibility defect, and an edge that had to be dropped because its
    target was unresolvable would delete the evidence of it.
    """

    model_config = ConfigDict(frozen=True, extra='forbid')

    kind: AxRelationKind
    target_node_id: str | None = None
    """The AX node this edge points at, when the producer could resolve one."""

    target_backend_dom_node_id: int | None = None
    """The browser's DOM node id for the target, kept even when no AX node corresponds."""

    target_text: str = ''
    """The `idref` or text the browser reported for the target, verbatim."""

    @model_validator(mode='after')
    def _require_some_target(self) -> AxRelation:
        if self.target_node_id is None and self.target_backend_dom_node_id is None and not self.target_text:
            raise ValueError(f'AX {self.kind.value} edge names no target at all')
        return self


class AxNode(BaseModel):
    """One node of the captured accessibility tree, preserved before any compaction."""

    model_config = ConfigDict(frozen=True, extra='forbid')

    node_id: str = Field(min_length=1)
    parent_id: str | None = None
    child_ids: tuple[str, ...] = ()
    role: str = ''
    name: str = ''
    value: str = ''
    description: str = ''
    properties: tuple[AxProperty, ...] = ()
    ignored: bool = False
    ignored_reasons: tuple[AxProperty, ...] = ()
    relations: tuple[AxRelation, ...] = ()
    backend_dom_node_id: int | None = None

    @model_validator(mode='after')
    def _validate_node(self) -> AxNode:
        names = [prop.name for prop in self.properties]
        if len(names) != len(set(names)):
            raise ValueError(f'AX node {self.node_id!r} has duplicate properties')
        if len(self.child_ids) != len(set(self.child_ids)):
            raise ValueError(f'AX node {self.node_id!r} lists a child twice')
        if self.node_id in self.child_ids:
            raise ValueError(f'AX node {self.node_id!r} is its own child')
        if self.ignored_reasons and not self.ignored:
            raise ValueError(f'AX node {self.node_id!r} states ignored reasons without being ignored')
        return self

    @property
    def state_names(self) -> tuple[str, ...]:
        """Return the property names this node carries, sorted; the node's state SHAPE.

        Names without values on purpose. `checked=true` and `checked=false` are two states of one
        control, and a shape that separated them would refuse to collapse the very run a reader
        wants collapsed. The values are discriminants and belong in the region summary.
        """
        return tuple(sorted(prop.name for prop in self.properties))


class AxSnapshot(BaseModel):
    """Self-describing, immutable JSON payload for one raw accessibility-tree observation."""

    model_config = ConfigDict(frozen=True, extra='forbid')

    schema_version: str = AX_SCHEMA_VERSION
    kind: Literal['ax_tree'] = 'ax_tree'
    snapshot_id: str = Field(min_length=1)
    root_id: str = Field(min_length=1)
    nodes: tuple[AxNode, ...] = Field(min_length=1)
    capabilities: tuple[AxCapability, ...] = ()

    @model_validator(mode='after')
    def _validate_graph(self) -> AxSnapshot:
        by_id = {node.node_id: node for node in self.nodes}
        if len(by_id) != len(self.nodes):
            raise ValueError('AX node ids must be unique within one snapshot')

        root = by_id.get(self.root_id)
        if root is None:
            raise ValueError(f'AX root {self.root_id!r} is absent from the node list')
        if root.parent_id is not None:
            raise ValueError(f'AX root {self.root_id!r} declares a parent')

        for node in self.nodes:
            _check_edges(node, by_id)

        reached = _reachable(root, by_id)
        if len(reached) != len(by_id):
            orphans = sorted(set(by_id) - reached)
            raise ValueError(f'AX nodes unreachable from the root: {orphans[:5]!r}')

        capability_kinds = [capability.kind for capability in self.capabilities]
        if len(capability_kinds) != len(set(capability_kinds)):
            raise ValueError('AX capabilities must contain at most one entry per kind')
        return self

    @property
    def by_id(self) -> dict[str, AxNode]:
        """Return the node list indexed by node id."""
        return {node.node_id: node for node in self.nodes}

    @property
    def root(self) -> AxNode:
        """Return the root node of this accessibility tree."""
        return self.by_id[self.root_id]

    @property
    def observed_node_count(self) -> int:
        """Count every captured node, ignored ones included."""
        return len(self.nodes)

    @property
    def ignored_node_count(self) -> int:
        """Count nodes the browser excluded from the accessibility tree."""
        return sum(node.ignored for node in self.nodes)


def _check_edges(node: AxNode, by_id: dict[str, AxNode]) -> None:
    """Check one node's containment and relationship edges against the whole node list.

    Both directions of containment, not just one. A `childIds` entry the parent claims and the
    child denies is the difference between a graph and two opinions about a graph, and either
    half alone would let one through.
    """
    for child_id in node.child_ids:
        child = by_id.get(child_id)
        if child is None:
            raise ValueError(f'AX node {node.node_id!r} names absent child {child_id!r}')
        if child.parent_id != node.node_id:
            raise ValueError(f'AX child {child_id!r} disagrees with parent {node.node_id!r}')
    if node.parent_id is not None:
        parent = by_id.get(node.parent_id)
        if parent is None:
            raise ValueError(f'AX node {node.node_id!r} names absent parent {node.parent_id!r}')
        if node.node_id not in parent.child_ids:
            raise ValueError(f'AX parent {node.parent_id!r} does not list child {node.node_id!r}')
    for relation in node.relations:
        if relation.target_node_id is not None and relation.target_node_id not in by_id:
            raise ValueError(
                f'AX {relation.kind.value} edge from {node.node_id!r} names absent node {relation.target_node_id!r}'
            )


def _reachable(root: AxNode, by_id: dict[str, AxNode]) -> set[str]:
    """Return the ids reachable from the root through `child_ids` alone.

    Relations are excluded deliberately: an edge is not containment, and letting a `controls`
    edge make a detached node "reachable" would hide exactly the orphan this check exists for.
    """
    seen: set[str] = set()
    stack = [root.node_id]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(child for child in by_id[current].child_ids if child not in seen)
    return seen


def serialize_ax_snapshot(snapshot: AxSnapshot) -> bytes:
    """Encode an AX snapshot with deterministic field order and UTF-8 JSON."""
    return snapshot.model_dump_json(exclude_none=False).encode('utf-8')


def parse_ax_snapshot(data: bytes) -> AxSnapshot:
    """Validate canonical AX JSON before a pruner or inspector consumes it.

    No depth guard, unlike `parse_dom_snapshot`: the producer's shape is a flat list, so an AX
    tree 200 levels deep is 200 entries of one array and never reaches the JSON parser's
    recursion limit.
    """
    return AxSnapshot.model_validate_json(data)


__all__ = [
    'AX_SCHEMA_VERSION',
    'AxCapability',
    'AxCapabilityKind',
    'AxNode',
    'AxProperty',
    'AxRelation',
    'AxRelationKind',
    'AxSnapshot',
    'parse_ax_snapshot',
    'serialize_ax_snapshot',
]
