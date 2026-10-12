"""Pydantic locator authoring; Rust compiles and executes every plan."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal, Self

from pydantic import Field, PrivateAttr, field_serializer, model_validator

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
"""Authored query vocabularies for trees, JSON, accessibility snapshots, and decoded
text. Document capabilities and execution limits are checked separately.
"""
ProjectionKind = Literal["text", "attribute", "value", "node", "name", "captures"]
"""Projection vocabulary preserving text, attributes, JSON values, node references,
accessible names, and named captures. Query/projection compatibility is checked by
Rust.
"""
JsonQuerySyntaxError = Literal[
    "InvalidPointerSyntax",
    "InvalidPointerEscape",
    "InvalidPathSyntax",
    "UnsupportedPathFeature",
]
"""Exact Rust JSON-query syntax classifications, separating invalid pointers, invalid
paths, and unsupported path features.
"""


class NamespaceBinding(ImmutableModel):
    """Query-local XML namespace binding independent of source prefixes.

    Attributes:
        prefix: Authored query prefix; empty denotes a default namespace binding.
        namespace_uri: Nonblank namespace URI used to identify expanded XML names.
    """

    prefix: str
    namespace_uri: str


class AccessibilityStateAtom(ImmutableModel):
    """One supported boolean accessibility-state query operand.

    Attributes:
        name: Supported state name: expanded or focused.
        value: Required boolean state, not a live browser mutation.
    """

    name: Literal["expanded", "focused"]
    value: bool


class QueryAtom(ImmutableModel):
    """Closed portable query meaning, separate from Python authoring syntax.

    Attributes:
        kind: CSS/XPath, JSON, accessibility, or decoded-text operation label.
        value: Authored expression text, or a typed accessibility-state operand.
    """

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
        """Return expression text, or the state name for a boolean state query."""
        return (
            self.value.name
            if isinstance(self.value, AccessibilityStateAtom)
            else self.value
        )


QueryResultShape = Literal[
    "tree_nodes", "json_values", "accessibility_nodes", "text_ranges"
]
"""Portable result capabilities: tree nodes, JSON values, accessibility nodes, or text
ranges. Shape is distinct from match count or evidence completeness.
"""
AccessibilityStateName = Literal["expanded", "focused"]
"""Supported boolean accessibility snapshot state names: expanded and focused. These
queries do not mutate a live browser.
"""


class QuerySpec(ImmutableModel):
    """Portable Rust query semantics with validated result shape.

    Attributes:
        atom: Closed query operation and expression or state operand.
        result_shape: tree_nodes, json_values, accessibility_nodes, or text_ranges
            retains capability distinctions.
        namespace_bindings: Explicit query-local XML namespace mappings; absent bindings
            are not inferred from document prefixes.
    """

    atom: QueryAtom
    result_shape: QueryResultShape
    namespace_bindings: tuple[NamespaceBinding, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )

    @model_validator(mode="after")
    def _rust_validate(self) -> Self:
        _native.compiled_query_info(self.model_dump_json())
        return self

    @classmethod
    def new(cls, atom: QueryAtom, result_shape: QueryResultShape) -> Self:
        """Validate a portable query operation and result shape through Rust.

        Args:
            atom: Closed query operation and authored operand.
            result_shape: Capability shape expected for the operation.

        Returns:
            A validated specification without locating any document evidence.

        Raises:
            LocatorError: Rust query structure or result-shape compatibility is invalid.
        """
        return cls(atom=atom, result_shape=result_shape)

    @property
    def query_bytes(self) -> int:
        """Return Rust-accounted query input bytes, including namespace metadata."""
        return json.loads(_native.compiled_query_info(self.model_dump_json()))[
            "query_bytes"
        ]

    def with_namespace(self, prefix: str, uri: str) -> Self:
        """Attach one explicit XML namespace prefix without searching documents.

        Args:
            prefix: Valid authored query prefix, unique within this declaration.
            uri: Nonblank namespace URI for expanded-name matching.

        Returns:
            A new validated query retaining the original declaration unchanged.

        Raises:
            LocatorError: Prefix, URI, duplicate binding, or query kind is unsupported.
        """
        return type(self).model_validate_json(
            _native.compiled_query_namespace(self.model_dump_json(), prefix, uri)
        )

    def with_default_namespace(self, uri: str) -> Self:
        """Attach an explicit default XML namespace without inferring source prefixes.

        Args:
            uri: Nonblank namespace URI for supported default-namespace query semantics.

        Returns:
            A new validated query with an explicit empty-prefix binding.

        Raises:
            LocatorError: Namespace metadata or query-kind support is invalid.
        """
        return type(self).model_validate_json(
            _native.compiled_query_namespace(self.model_dump_json(), None, uri)
        )

    def to_query(self) -> Query:
        """Reconstruct validated Python authoring intent from portable semantics."""
        return Query.from_compiled(self)


class Query(ImmutableModel):
    """Immutable locator intent compiled and checked by the Rust SDK.

    Attributes:
        kind: Python authoring operation; compiled wire tags can differ.
        expression: Authored query text retained without acquiring or searching
            documents.
        namespaces: Explicit XML bindings, with unique prefixes.
        state: Boolean operand for an accessibility-state query, otherwise None.
        shape: Rust-resolved result capability; it does not prove a document supports
            the query.
        within: Optional single repeated-region scope. Nested region declarations are
            unsupported.
    """

    kind: QueryKind
    expression: str
    namespaces: tuple[NamespaceBinding, ...] = ()
    state: bool | None = None
    shape: QueryResultShape | None = None
    within: Region | None = None

    @field_serializer("namespaces", when_used="json")
    def _namespace_wire(self, value: tuple[NamespaceBinding, ...]) -> dict[str, str]:
        return {item.prefix: item.namespace_uri for item in value}

    @model_validator(mode="after")
    def _rust_validate(self) -> Self:
        if len({item.prefix for item in self.namespaces}) != len(self.namespaces):
            raise _native.LocatorError("duplicate namespace prefix")
        compiled = json.loads(
            _native.authored_query_info(self.model_dump_json(exclude_none=True))
        )["query"]
        object.__setattr__(self, "shape", compiled["result_shape"])
        object.__setattr__(
            self,
            "namespaces",
            tuple(
                NamespaceBinding.model_validate(binding)
                for binding in compiled.get("namespace_bindings", [])
            ),
        )
        return self

    def model_copy(
        self, *, update: Mapping[str, Any] | None = None, deep: bool = False
    ) -> Self:
        """Copy immutable authoring intent and revalidate changed inputs.

        Args:
            update: Optional authoring replacements to validate in Rust.
            deep: Reconstruct the declaration when True.

        Returns:
            A validated copy. Unchanged shallow copies retain compiled ownership.

        Raises:
            LocatorError: Changed declarations fail native semantic validation.
            pydantic.ValidationError: Updated authoring fields are invalid.
        """
        if update or deep:
            return type(self).model_validate({**self.model_dump(), **(update or {})})
        return super().model_copy()

    def compiled(self) -> QuerySpec:
        """Return portable semantics compiled by Rust without executing a locator."""
        return QuerySpec.model_validate(
            json.loads(
                _native.authored_query_info(self.model_dump_json(exclude_none=True))
            )["query"]
        )

    @property
    def atom(self) -> QueryAtom:
        """Return the Rust-compiled closed query operation and operand."""
        return self.compiled().atom

    @property
    def result_shape(self) -> QueryResultShape:
        """Return the Rust-resolved result capability without locating a document."""
        return self.compiled().result_shape

    @property
    def namespace_bindings(self) -> tuple[NamespaceBinding, ...]:
        """Return explicit compiled XML bindings in their retained order."""
        return self.compiled().namespace_bindings

    @property
    def query_bytes(self) -> int:
        """Return query input bytes accounted by the compiled Rust specification."""
        return self.compiled().query_bytes

    @classmethod
    def from_compiled(cls, spec: QuerySpec | Mapping[str, Any]) -> Self:
        """Reconstruct authoring intent from validated portable query semantics.

        Args:
            spec: QuerySpec or mapping containing a Rust-compatible atom and shape.

        Returns:
            A query retaining compiled meaning without acquiring documents.

        Raises:
            LocatorError: Native query semantics cannot be represented.
            pydantic.ValidationError: The portable input structure is invalid.
        """
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
                "shape": spec.result_shape,
            }
        )

    def with_namespace(self, prefix: str, uri: str) -> Query:
        """Attach one explicit XML namespace prefix without searching documents.

        Args:
            prefix: Valid authored query prefix, unique within this declaration.
            uri: Nonblank namespace URI for expanded-name matching.

        Returns:
            A new validated query retaining the original declaration unchanged.

        Raises:
            LocatorError: Prefix, URI, duplicate binding, or query kind is unsupported.
        """
        _native.validate_namespace(self.model_dump_json(exclude_none=True), prefix, uri)
        if any(item.prefix == prefix for item in self.namespaces):
            raise _native.LocatorError("duplicate namespace prefix")
        binding = NamespaceBinding(prefix=prefix, namespace_uri=uri)
        return self.model_copy(update={"namespaces": (*self.namespaces, binding)})

    def with_default_namespace(self, uri: str) -> Query:
        """Attach an explicit default XML namespace without inferring source prefixes.

        Args:
            uri: Nonblank namespace URI for supported default-namespace query semantics.

        Returns:
            A new validated query with an explicit empty-prefix binding.

        Raises:
            LocatorError: Namespace metadata or query-kind support is invalid.
        """
        _native.validate_namespace(self.model_dump_json(exclude_none=True), None, uri)
        binding = NamespaceBinding(prefix="", namespace_uri=uri)
        return self.model_copy(update={"namespaces": (*self.namespaces, binding)})

    def each_as_region(self, id: str) -> Region:
        """Declare this query as one repeated-region root.

        Args:
            id: Authored lineage identity used to group scoped output findings.

        Returns:
            A region declaration without evaluating matches.

        Raises:
            LocatorError: The region identity or nested-region structure is invalid.
        """
        return Region(id=id, query=self)

    def text(self) -> Locator:
        """Request projection of supported text evidence.

        Returns:
            A locator declaration without executing the query or acquiring evidence.

        Raises:
            LocatorError: The query's capability shape cannot support this projection.
        """
        return Locator(query=self, projection="text")

    def attribute(self, name: str) -> Locator:
        """Request named attribute values from a compatible query result.

        Args:
            name: Attribute name to project from matched nodes.

        Returns:
            A locator declaration; no document evidence is acquired.

        Raises:
            LocatorError: Attribute metadata or projection compatibility is invalid.
        """
        return Locator(query=self, projection="attribute", attribute=name)

    def value(self) -> Locator:
        """Request projection of native JSON values.

        Returns:
            A locator declaration without executing the query or acquiring evidence.

        Raises:
            LocatorError: The query's capability shape cannot support this projection.
        """
        return Locator(query=self, projection="value")

    def node(self) -> Locator:
        """Request projection of document-bound node references.

        Returns:
            A locator declaration without executing the query or acquiring evidence.

        Raises:
            LocatorError: The query's capability shape cannot support this projection.
        """
        return Locator(query=self, projection="node")

    def name(self) -> Locator:
        """Request projection of accessible node names.

        Returns:
            A locator declaration without executing the query or acquiring evidence.

        Raises:
            LocatorError: The query's capability shape cannot support this projection.
        """
        return Locator(query=self, projection="name")

    def captures(self, *names: str) -> Locator:
        """Request selected named regex captures alongside matched text.

        Args:
            names: Capture names to retain from a supported text-regex query.

        Returns:
            A projection declaration without executing the query.

        Raises:
            LocatorError: Capture names or query/projection compatibility is invalid.
        """
        return Locator(query=self, projection="captures", captures=tuple(names))


class Region(ImmutableModel):
    """One authored repeated-region query and its lineage identity.

    Attributes:
        id: Unique authored repeated-region identity.
        query: Root query without an existing parent region; nested regions are
            unsupported.
    """

    id: RegionId
    query: Query

    @model_validator(mode="after")
    def _rust_validate(self) -> Self:
        _native.validate_region_id(self.id)
        if self.query.within is not None:
            raise _native.LocatorError("nested regions are not supported")
        return self

    def find(self, query: Query) -> Query:
        """Scope a query within each match of this repeated-region root.

        Args:
            query: Query intent to evaluate inside this region's matched evidence.

        Returns:
            A revalidated query carrying this parent-region declaration.
        """
        return query.model_copy(update={"within": self})


class Locator(ImmutableModel):
    """Query intent paired with an explicit supported projection.

    Attributes:
        query: Query operation and optional repeated-region scope.
        projection: text, attribute, value, node, name, or captures determines emitted
            evidence.
        attribute: Attribute name required for attribute projection, otherwise None.
        captures: Named regex capture selections; Rust checks projection compatibility.
    """

    query: Query
    projection: ProjectionKind
    attribute: str | None = None
    captures: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _rust_validate(self) -> Self:
        _native.validate_locator(self.model_dump_json(exclude_none=True))
        return self


class Output(ImmutableModel):
    """Named projected evidence declaration for a compiled locate plan.

    Attributes:
        id: Authored output identity, unique within its plan.
        locator: Query and projection used to produce this output finding evidence.
    """

    id: OutputId
    locator: Locator

    @model_validator(mode="after")
    def _rust_validate(self) -> Self:
        _native.validate_output_id(self.id)
        return self


class Plan(ImmutableModel):
    """Compiled immutable outputs and repeated-region declarations.

    Attributes:
        outputs: Ordered named output declarations. Native compilation checks IDs,
            projection compatibility, and region structure without acquiring documents.
    """

    outputs: tuple[Output, ...]
    _handle: _native.Plan = PrivateAttr()

    def model_post_init(self, context: object) -> None:
        """Retain an existing native plan or compile declared outputs through Rust."""
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
        """Copy immutable authoring intent and revalidate changed inputs.

        Args:
            update: Optional authoring replacements to validate in Rust.
            deep: Reconstruct the declaration when True.

        Returns:
            A validated copy. Unchanged shallow copies retain compiled ownership.

        Raises:
            LocatorError: Changed declarations fail native semantic validation.
            pydantic.ValidationError: Updated authoring fields are invalid.
        """
        if update or deep:
            return type(self).model_validate({**self.model_dump(), **(update or {})})
        return super().model_copy()

    def __eq__(self, other: object) -> bool:
        """Compare ordered authoring outputs rather than native-handle identity.

        Args:
            other: Another plan to compare.

        Returns:
            Ordered output equality; other operand types return NotImplemented.
        """
        if not isinstance(other, Plan):
            return NotImplemented
        return self.outputs == other.outputs


def output(id: str | OutputId, locator: Locator) -> Output:
    """Name one explicit query and projection declaration.

    Args:
        id: Authored output identity to validate and retain.
        locator: Query and projection selecting the finding evidence.

    Returns:
        An output declaration; plan construction checks identity uniqueness.

    Raises:
        LocatorError: The authored output identity is invalid.
    """
    return Output(id=id, locator=locator)


def css(expression: str) -> Query:
    """Author CSS tree-node query intent without document I/O.

    Args:
        expression: Authored expression in the selected query vocabulary.

    Returns:
        Immutable Rust-checked intent, not acquired matches. Execution can still
        reject document capabilities, parser support, or resource limits.

    Raises:
        LocatorError: Authored expression or supported syntax checks reject input.
    """
    return Query(kind="css", expression=expression)


def xpath(expression: str) -> Query:
    """Author XPath tree-node query intent without document I/O.

    Args:
        expression: Authored expression in the selected query vocabulary.

    Returns:
        Immutable Rust-checked intent, not acquired matches. Execution can still
        reject document capabilities, parser support, or resource limits.

    Raises:
        LocatorError: Authored expression or supported syntax checks reject input.
    """
    return Query(kind="xpath", expression=expression)


def tree_text_contains(expression: str) -> Query:
    """Author tree descendant-text substring query intent without document I/O.

    Args:
        expression: Authored expression in the selected query vocabulary.

    Returns:
        Immutable Rust-checked intent, not acquired matches. Execution can still
        reject document capabilities, parser support, or resource limits.

    Raises:
        LocatorError: Authored expression or supported syntax checks reject input.
    """
    return Query(kind="tree_text_contains", expression=expression)


def json_pointer(expression: str) -> Query:
    """Author JSON Pointer value query intent without document I/O.

    Args:
        expression: Authored expression in the selected query vocabulary.

    Returns:
        Immutable Rust-checked intent, not acquired matches. Execution can still
        reject document capabilities, parser support, or resource limits.

    Raises:
        LocatorError: Authored expression or supported syntax checks reject input.
    """
    return Query(kind="json_pointer", expression=expression)


def json_path(expression: str) -> Query:
    """Author supported Rust JSONPath value query intent without document I/O.

    Args:
        expression: Authored expression in the selected query vocabulary.

    Returns:
        Immutable Rust-checked intent, not acquired matches. Execution can still
        reject document capabilities, parser support, or resource limits.

    Raises:
        LocatorError: Authored expression or supported syntax checks reject input.
    """
    return Query(kind="json_path", expression=expression)


def role(expression: str) -> Query:
    """Author accessibility role query intent without document I/O.

    Args:
        expression: Authored expression in the selected query vocabulary.

    Returns:
        Immutable Rust-checked intent, not acquired matches. Execution can still
        reject document capabilities, parser support, or resource limits.

    Raises:
        LocatorError: Authored expression or supported syntax checks reject input.
    """
    return Query(kind="role", expression=expression)


def accessible_name(expression: str) -> Query:
    """Author accessible node name query intent without document I/O.

    Args:
        expression: Authored expression in the selected query vocabulary.

    Returns:
        Immutable Rust-checked intent, not acquired matches. Execution can still
        reject document capabilities, parser support, or resource limits.

    Raises:
        LocatorError: Authored expression or supported syntax checks reject input.
    """
    return Query(kind="accessible_name", expression=expression)


def accessibility_text(expression: str) -> Query:
    """Author accessibility node text query intent without document I/O.

    Args:
        expression: Authored expression in the selected query vocabulary.

    Returns:
        Immutable Rust-checked intent, not acquired matches. Execution can still
        reject document capabilities, parser support, or resource limits.

    Raises:
        LocatorError: Authored expression or supported syntax checks reject input.
    """
    return Query(kind="accessibility_text", expression=expression)


def accessibility_state(name: AccessibilityStateName, value: bool) -> Query:
    """Declare a boolean accessibility-state query without browser I/O.

    Args:
        name: Supported state name, expanded or focused.
        value: Required boolean state.

    Returns:
        Accessibility-node query intent for an immutable supported snapshot.
    """
    return Query(kind="accessibility_state", expression=name, state=value)


def text_literal(expression: str) -> Query:
    """Author decoded-text literal range query intent without document I/O.

    Args:
        expression: Authored expression in the selected query vocabulary.

    Returns:
        Immutable Rust-checked intent, not acquired matches. Execution can still
        reject document capabilities, parser support, or resource limits.

    Raises:
        LocatorError: Authored expression or supported syntax checks reject input.
    """
    return Query(kind="text_literal", expression=expression)


def regex(expression: str) -> Query:
    """Author decoded-text regular-expression range query intent without document I/O.

    Args:
        expression: Authored expression in the selected query vocabulary.

    Returns:
        Immutable Rust-checked intent, not acquired matches. Execution can still
        reject document capabilities, parser support, or resource limits.

    Raises:
        LocatorError: Authored expression or supported syntax checks reject input.
    """
    return Query(kind="regex", expression=expression)


Query.model_rebuild()

OutputPlan = Locator
"""Alias for the query-plus-projection Locator declaration. A compiled collection of
named outputs is represented by Plan instead.
"""
NamedOutput = Output
"""Alias for an Output declaration pairing an authored identity with its query and
projection. Output identity uniqueness is checked when a Plan is compiled.
"""
RegionPlan = Region
"""Alias for a repeated-region declaration carrying a root query and lineage identity.
Nested repeated regions are unsupported.
"""
