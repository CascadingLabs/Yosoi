"""Versioned structured artifacts for one rendered-DOM capture."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DOM_SCHEMA_VERSION = 'dom1'


class DomCapabilityKind(str, Enum):
    """Runtime facts a DOM producer may or may not have captured."""

    VISIBILITY = 'visibility'
    GEOMETRY = 'geometry'
    RUNTIME_STATE = 'runtime_state'
    SHADOW_DOM = 'shadow_dom'
    PORTALS = 'portals'
    DECLARED_COUNTS = 'declared_counts'


class DomCapability(BaseModel):
    """Explicit availability for one DOM-specific capture capability."""

    model_config = ConfigDict(frozen=True, extra='forbid')

    kind: DomCapabilityKind
    available: bool
    reason: str | None = None

    @model_validator(mode='after')
    def _require_reason_when_unavailable(self) -> DomCapability:
        if not self.available and not self.reason:
            raise ValueError('an unavailable DOM capability must state a reason')
        return self


class DomVisibility(str, Enum):
    """Producer-reported visibility state; this is not inferred from source markup."""

    VISIBLE = 'visible'
    HIDDEN = 'hidden'
    DISPLAY_NONE = 'display_none'
    OFFSCREEN = 'offscreen'
    INERT = 'inert'
    UNKNOWN = 'unknown'


class DomAttribute(BaseModel):
    """One ordered DOM attribute, preserving the captured attribute vocabulary."""

    model_config = ConfigDict(frozen=True, extra='forbid')

    name: str = Field(min_length=1)
    value: str


class DomGeometry(BaseModel):
    """Layout facts captured for one node at the snapshot boundary."""

    model_config = ConfigDict(frozen=True, extra='forbid')

    x: float
    y: float
    width: float = Field(ge=0)
    height: float = Field(ge=0)
    in_viewport: bool


class DomRuntimeState(BaseModel):
    """Interactive state that is not reliably recoverable from HTML attributes."""

    model_config = ConfigDict(frozen=True, extra='forbid')

    value: str | None = None
    checked: bool | None = None
    selected: bool | None = None
    expanded: bool | None = None
    pressed: bool | None = None
    disabled: bool | None = None
    focused: bool | None = None


class DomNode(BaseModel):
    """One element in the captured rendered-DOM tree.

    ``shadow_root`` and ``portal_target_id`` are explicit edges rather than flattened child
    markup. This keeps browser boundaries visible to the future pruner and inspector.
    """

    model_config = ConfigDict(frozen=True, extra='forbid')

    node_id: str = Field(min_length=1)
    tag: str = Field(min_length=1)
    attributes: tuple[DomAttribute, ...] = ()
    text: str = ''
    visibility: DomVisibility = DomVisibility.UNKNOWN
    geometry: DomGeometry | None = None
    runtime: DomRuntimeState | None = None
    declared_count: int | None = Field(default=None, ge=0)
    children: tuple[DomNode, ...] = ()
    shadow_root: DomNode | None = None
    portal_target_id: str | None = None

    @model_validator(mode='after')
    def _validate_attributes(self) -> DomNode:
        names = [attribute.name for attribute in self.attributes]
        if len(names) != len(set(names)):
            raise ValueError(f'DOM node {self.node_id!r} has duplicate attributes')
        return self


class DomSnapshot(BaseModel):
    """Self-describing, immutable JSON payload for one rendered-DOM observation."""

    model_config = ConfigDict(frozen=True, extra='forbid')

    schema_version: str = DOM_SCHEMA_VERSION
    kind: Literal['rendered_dom'] = 'rendered_dom'
    snapshot_id: str = Field(min_length=1)
    root: DomNode
    capabilities: tuple[DomCapability, ...] = ()
    viewport_width: int | None = Field(default=None, ge=0)
    viewport_height: int | None = Field(default=None, ge=0)

    @model_validator(mode='after')
    def _validate_graph(self) -> DomSnapshot:
        nodes: list[DomNode] = []

        def visit(node: DomNode) -> None:
            nodes.append(node)
            for child in node.children:
                visit(child)
            if node.shadow_root is not None:
                visit(node.shadow_root)

        visit(self.root)
        node_ids = [node.node_id for node in nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError('DOM node ids must be unique across light and shadow trees')

        capability_kinds = [capability.kind for capability in self.capabilities]
        if len(capability_kinds) != len(set(capability_kinds)):
            raise ValueError('DOM capabilities must contain at most one entry per kind')

        known_ids = set(node_ids)
        dangling_portals = [
            node.portal_target_id
            for node in nodes
            if node.portal_target_id is not None and node.portal_target_id not in known_ids
        ]
        if dangling_portals:
            raise ValueError(f'DOM portal targets do not resolve: {dangling_portals!r}')
        return self

    @property
    def observed_node_count(self) -> int:
        """Count observed element nodes, including nodes inside shadow roots."""
        count = 0

        def visit(node: DomNode) -> None:
            nonlocal count
            count += 1
            for child in node.children:
                visit(child)
            if node.shadow_root is not None:
                visit(node.shadow_root)

        visit(self.root)
        return count


def serialize_dom_snapshot(snapshot: DomSnapshot) -> bytes:
    """Encode a DOM snapshot with deterministic field order and UTF-8 JSON."""
    return snapshot.model_dump_json(exclude_none=False).encode('utf-8')


def parse_dom_snapshot(data: bytes) -> DomSnapshot:
    """Validate canonical DOM JSON before a pruner or inspector consumes it."""
    return DomSnapshot.model_validate_json(data)


__all__ = [
    'DOM_SCHEMA_VERSION',
    'DomAttribute',
    'DomCapability',
    'DomCapabilityKind',
    'DomGeometry',
    'DomNode',
    'DomRuntimeState',
    'DomSnapshot',
    'DomVisibility',
    'parse_dom_snapshot',
    'serialize_dom_snapshot',
]
