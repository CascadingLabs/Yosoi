"""Pydantic locator authoring; Rust compiles and executes every plan."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal, Self

from pydantic import PrivateAttr, field_serializer, model_validator

from . import _native
from ._models import ImmutableModel
from .outcomes import (
    AccessibilityCoordinate,  # noqa: F401
    AccessibilityLocation,  # noqa: F401
    ByteRange,  # noqa: F401
    Completeness,  # noqa: F401
    DecodedTextCoordinate,  # noqa: F401
    DecodedTextLocation,  # noqa: F401
    DomCoordinate,  # noqa: F401
    ExpandedNamePathSegment,  # noqa: F401
    Finding,  # noqa: F401
    IncompleteEvidence,  # noqa: F401
    JsonLocation,  # noqa: F401
    LocateOutcome,  # noqa: F401
    LocateResult,  # noqa: F401
    NativeCoordinate,  # noqa: F401
    NodeReference,  # noqa: F401
    ProjectedValue,  # noqa: F401
    RegionLineage,  # noqa: F401
    RenderedDomLocation,  # noqa: F401
    ResourceLimit,  # noqa: F401
    SourceTreeLocation,  # noqa: F401
    TextRange,  # noqa: F401
    TreeCoordinate,  # noqa: F401
)
from .outcomes import Failure as LocateFailure  # noqa: F401
from .scalars import DomNodeId, JsonCoordinate, OutputId, RegionId  # noqa: F401

QueryKind = Literal[
    "css",
    "xpath",
    "tree_text_contains",
    "json_pointer",
    "json_path",
    "role",
    "accessible_name",
    "accessibility_text",
    "accessibility_state",
    "text_literal",
    "regex",
]
ProjectionKind = Literal["text", "attribute", "value", "node", "name", "captures"]


class NamespaceBinding(ImmutableModel):
    prefix: str
    namespace_uri: str


class AccessibilityStateAtom(ImmutableModel):
    name: Literal["expanded", "focused"]
    value: bool


class QueryAtom(ImmutableModel):
    kind: Literal[
        "css",
        "x_path",
        "tree_text_contains",
        "json_pointer",
        "json_path",
        "accessibility_role",
        "accessible_name",
        "accessibility_text",
        "accessibility_state",
        "text_literal",
        "text_regex",
    ]
    value: str | AccessibilityStateAtom

    @property
    def expression(self) -> str:
        return (
            self.value.name
            if isinstance(self.value, AccessibilityStateAtom)
            else self.value
        )


QueryResultShape = Literal[
    "tree_nodes", "json_values", "accessibility_nodes", "text_ranges"
]
AccessibilityStateName = Literal["expanded", "focused"]


class QuerySpec(ImmutableModel):
    """Portable Rust query semantics, independently of Python authoring syntax."""

    atom: QueryAtom
    result_shape: QueryResultShape
    namespace_bindings: tuple[NamespaceBinding, ...] = ()

    @model_validator(mode="after")
    def _rust_validate(self) -> Self:
        _native.compiled_query_info(self.model_dump_json())
        return self

    @classmethod
    def new(cls, atom: QueryAtom, result_shape: QueryResultShape) -> Self:
        return cls(atom=atom, result_shape=result_shape)

    @property
    def query_bytes(self) -> int:
        return json.loads(_native.compiled_query_info(self.model_dump_json()))[
            "query_bytes"
        ]

    def with_namespace(self, prefix: str, uri: str) -> Self:
        return type(self).model_validate_json(
            _native.compiled_query_namespace(self.model_dump_json(), prefix, uri)
        )

    def with_default_namespace(self, uri: str) -> Self:
        return type(self).model_validate_json(
            _native.compiled_query_namespace(self.model_dump_json(), None, uri)
        )

    def to_query(self) -> Query:
        return Query.from_compiled(self)


class Query(ImmutableModel):
    kind: QueryKind
    expression: str
    namespaces: tuple[NamespaceBinding, ...] = ()
    state: bool | None = None
    within: Region | None = None

    @field_serializer("namespaces", when_used="json")
    def _namespace_wire(self, value: tuple[NamespaceBinding, ...]) -> dict[str, str]:
        return {item.prefix: item.namespace_uri for item in value}

    @model_validator(mode="after")
    def _rust_validate(self) -> Self:
        if len({item.prefix for item in self.namespaces}) != len(self.namespaces):
            raise _native.LocatorError("duplicate namespace prefix")
        _native.validate_query(self.model_dump_json(exclude_none=True))
        return self

    def model_copy(
        self, *, update: Mapping[str, Any] | None = None, deep: bool = False
    ) -> Self:
        if update or deep:
            return type(self).model_validate({**self.model_dump(), **(update or {})})
        return super().model_copy()

    def compiled(self) -> QuerySpec:
        return QuerySpec.model_validate(
            json.loads(
                _native.authored_query_info(self.model_dump_json(exclude_none=True))
            )["query"]
        )

    @property
    def atom(self) -> QueryAtom:
        return self.compiled().atom

    @property
    def result_shape(self) -> QueryResultShape:
        return self.compiled().result_shape

    @property
    def namespace_bindings(self) -> tuple[NamespaceBinding, ...]:
        return self.compiled().namespace_bindings

    @property
    def query_bytes(self) -> int:
        return self.compiled().query_bytes

    @classmethod
    def from_compiled(cls, spec: QuerySpec | Mapping[str, Any]) -> Self:
        if not isinstance(spec, QuerySpec):
            spec = QuerySpec.model_validate(spec)
        kind = {
            "x_path": "xpath",
            "accessibility_role": "role",
            "text_regex": "regex",
        }.get(spec.atom.kind, spec.atom.kind)
        state = (
            spec.atom.value.value
            if isinstance(spec.atom.value, AccessibilityStateAtom)
            else None
        )
        return cls.model_validate(
            {
                "kind": kind,
                "expression": spec.atom.expression,
                "namespaces": spec.namespace_bindings,
                "state": state,
            }
        )

    def with_namespace(self, prefix: str, uri: str) -> Query:
        _native.validate_namespace(self.model_dump_json(exclude_none=True), prefix, uri)
        if any(item.prefix == prefix for item in self.namespaces):
            raise _native.LocatorError("duplicate namespace prefix")
        binding = NamespaceBinding(prefix=prefix, namespace_uri=uri)
        return self.model_copy(update={"namespaces": (*self.namespaces, binding)})

    def with_default_namespace(self, uri: str) -> Query:
        _native.validate_namespace(self.model_dump_json(exclude_none=True), None, uri)
        binding = NamespaceBinding(prefix="", namespace_uri=uri)
        return self.model_copy(update={"namespaces": (*self.namespaces, binding)})

    def each_as_region(self, id: str) -> Region:
        return Region(id=id, query=self)

    def text(self) -> Locator:
        return Locator(query=self, projection="text")

    def attribute(self, name: str) -> Locator:
        return Locator(query=self, projection="attribute", attribute=name)

    def value(self) -> Locator:
        return Locator(query=self, projection="value")

    def node(self) -> Locator:
        return Locator(query=self, projection="node")

    def name(self) -> Locator:
        return Locator(query=self, projection="name")

    def captures(self, *names: str) -> Locator:
        return Locator(query=self, projection="captures", captures=tuple(names))


class Region(ImmutableModel):
    id: RegionId
    query: Query

    @model_validator(mode="after")
    def _rust_validate(self) -> Self:
        _native.validate_region_id(self.id)
        if self.query.within is not None:
            raise _native.LocatorError("nested regions are not supported")
        return self

    def find(self, query: Query) -> Query:
        return query.model_copy(update={"within": self})


class Locator(ImmutableModel):
    query: Query
    projection: ProjectionKind
    attribute: str | None = None
    captures: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _rust_validate(self) -> Self:
        _native.validate_locator(self.model_dump_json(exclude_none=True))
        return self


class Output(ImmutableModel):
    id: OutputId
    locator: Locator

    @model_validator(mode="after")
    def _rust_validate(self) -> Self:
        _native.validate_output_id(self.id)
        return self


class Plan(ImmutableModel):
    outputs: tuple[Output, ...]
    _handle: _native.Plan = PrivateAttr()

    def model_post_init(self, context: object) -> None:
        if isinstance(context, _native.Plan):
            self._handle = context
            return
        declarations = [
            item.model_dump(mode="json", exclude_none=True) for item in self.outputs
        ]
        self._handle = _native.Plan(json.dumps(declarations))

    @classmethod
    def from_compiled(cls, value: str | Mapping[str, Any]) -> Self:
        """Import a portable Rust Plan; Rust validates all compiled invariants."""
        handle = _native.Plan.from_json(
            value if isinstance(value, str) else json.dumps(value)
        )
        wire = json.loads(handle.to_json())
        regions = {
            item["id"]: Region(id=item["id"], query=Query.from_compiled(item["query"]))
            for item in wire["regions"]
        }
        projections = {
            "descendant_text": "text",
            "matched_text": "text",
            "accessibility_text": "text",
            "attribute": "attribute",
            "json_value": "value",
            "node_reference": "node",
            "accessible_name": "name",
            "matched_text_with_captures": "captures",
        }
        outputs = []
        for item in wire["outputs"]:
            query = Query.from_compiled(item["query"])
            if item["parent_region"] is not None:
                query = regions[item["parent_region"]].find(query)
            projected = item["projection"]
            projection = projections[projected["kind"]]
            locator = Locator.model_validate(
                {
                    "query": query,
                    "projection": projection,
                    "attribute": projected.get("value")
                    if projection == "attribute"
                    else None,
                    "captures": projected["value"]["names"]
                    if projection == "captures"
                    else (),
                }
            )
            outputs.append(Output(id=item["id"], locator=locator))
        return cls.model_validate({"outputs": outputs}, context=handle)

    def compiled(self) -> dict[str, object]:
        """Inspect the portable plan compiled by Rust."""
        return json.loads(self._handle.to_json())

    def model_copy(
        self, *, update: Mapping[str, Any] | None = None, deep: bool = False
    ) -> Self:
        if update or deep:
            return type(self).model_validate({**self.model_dump(), **(update or {})})
        return super().model_copy()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Plan):
            return NotImplemented
        return self.outputs == other.outputs


def output(id: str | OutputId, locator: Locator) -> Output:
    return Output(id=id, locator=locator)


def css(expression: str) -> Query:
    return Query(kind="css", expression=expression)


def xpath(expression: str) -> Query:
    return Query(kind="xpath", expression=expression)


def tree_text_contains(expression: str) -> Query:
    return Query(kind="tree_text_contains", expression=expression)


def json_pointer(expression: str) -> Query:
    return Query(kind="json_pointer", expression=expression)


def json_path(expression: str) -> Query:
    return Query(kind="json_path", expression=expression)


def role(expression: str) -> Query:
    return Query(kind="role", expression=expression)


def accessible_name(expression: str) -> Query:
    return Query(kind="accessible_name", expression=expression)


def accessibility_text(expression: str) -> Query:
    return Query(kind="accessibility_text", expression=expression)


def accessibility_state(name: AccessibilityStateName, value: bool) -> Query:
    return Query(kind="accessibility_state", expression=name, state=value)


def text_literal(expression: str) -> Query:
    return Query(kind="text_literal", expression=expression)


def regex(expression: str) -> Query:
    return Query(kind="regex", expression=expression)


Query.model_rebuild()

OutputPlan = Locator
NamedOutput = Output
RegionPlan = Region
