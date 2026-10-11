"""Typed locator outcomes preserve Rust evidence and terminal distinctions."""

from __future__ import annotations

import json
from typing import Annotated, Literal, Self

from pydantic import (
    Field,
    JsonValue,
    TypeAdapter,
    ValidationInfo,
    field_validator,
    model_validator,
)

from . import _native
from ._models import ImmutableModel
from .scalars import (
    RUST_DOMAIN_VALIDATED,
    DocumentEpoch,
    DocumentId,
    DomNodeId,
    JsonCoordinate,
    OutputId,
    RegionId,
)

U32 = Annotated[int, Field(strict=True, ge=0, le=(1 << 32) - 1)]
"""Strict integer from zero through the u32 maximum. Booleans, floating-point values,
and numeric strings are not coerced.
"""
PositiveU32 = Annotated[int, Field(strict=True, gt=0, le=(1 << 32) - 1)]
"""Strict positive u32 integer. Zero and numeric coercions are rejected; units belong
to the consuming field.
"""
U64 = Annotated[int, Field(strict=True, ge=0, le=(1 << 64) - 1)]
"""Strict integer from zero through the u64 maximum, without numeric coercion. Units
and evidence meaning belong to the consuming field.
"""
ResourceLimit = Literal[
    "input_bytes",
    "nodes",
    "selector_visits",
    "query_bytes",
    "query_steps",
    "regions",
    "matches",
    "captures",
    "depth",
    "output_bytes",
]
"""Locator resource classifications for byte, node, visit, query, region, match,
capture, depth, and output accounting. Each named counter has its own units.
"""
DocumentClassName = Literal[
    "source_html",
    "source_xml",
    "source_json",
    "source_text",
    "rendered_dom",
    "accessibility_tree",
]
"""Serialized document capability names. Source HTML/XML/JSON/text, rendered DOM, and
accessibility-tree evidence remain distinct.
"""


class ByteRange(ImmutableModel):
    """Half-open byte offsets in an owned source payload, allowing empty ranges.

    Attributes:
        start: Inclusive starting byte offset.
        end: Exclusive ending byte offset, not less than start. Bounds and UTF-8
            boundaries are not verified against a document.
    """
    start: U64
    end: U64

    @model_validator(mode="after")
    def _rust_validate(self, info: ValidationInfo) -> Self:
        if info.context is not RUST_DOMAIN_VALIDATED:
            _native.validate_domain_model("byte_range", self.model_dump_json())
        return self

    @classmethod
    def try_new(cls, start: int, end: int) -> Self:
        """Validate half-open byte offsets through the Rust constructor.

        Args:
            start: Inclusive source-byte offset.
            end: Exclusive offset; equality permits an empty range.

        Returns:
            Validated offsets without a source-payload bounds or UTF-8 boundary check.

        Raises:
            LocatorError: The range is reversed or its wire values are invalid.
        """
        value = _native.validate_domain_model(
            "byte_range", json.dumps({"start": start, "end": end})
        )
        return cls.model_validate_json(value, context=RUST_DOMAIN_VALIDATED)


class TextRange(ImmutableModel):
    """Half-open Unicode-scalar offsets in decoded text, allowing empty ranges.

    Attributes:
        start: Inclusive scalar offset, not a UTF-8 byte or grapheme index.
        end: Exclusive scalar offset, not less than start. Text bounds are not verified.
    """
    start: U64
    end: U64

    @model_validator(mode="after")
    def _rust_validate(self, info: ValidationInfo) -> Self:
        if info.context is not RUST_DOMAIN_VALIDATED:
            _native.validate_domain_model("text_range", self.model_dump_json())
        return self

    @classmethod
    def try_new(cls, start: int, end: int) -> Self:
        """Validate half-open Unicode-scalar offsets through Rust.

        Args:
            start: Inclusive decoded-text scalar offset.
            end: Exclusive scalar offset; equality permits an empty range.

        Returns:
            Validated offsets without checking text bounds or grapheme boundaries.

        Raises:
            LocatorError: The range is reversed or its wire values are invalid.
        """
        value = _native.validate_domain_model(
            "text_range", json.dumps({"start": start, "end": end})
        )
        return cls.model_validate_json(value, context=RUST_DOMAIN_VALIDATED)


class ExpandedNamePathSegment(ImmutableModel):
    """Namespace-qualified XML element identity within a tree path.

    Attributes:
        namespace_uri: Namespace URI independent of source prefix spelling, or None for
            an unqualified name.
        local_name: Retained nonempty local name; no tree membership is checked.
        same_name_sibling_index: One-based index among siblings with the same expanded
            name.
    """
    namespace_uri: str | None = None
    local_name: str
    same_name_sibling_index: PositiveU32

    @model_validator(mode="after")
    def _rust_validate(self, info: ValidationInfo) -> Self:
        if info.context is not RUST_DOMAIN_VALIDATED:
            _native.validate_domain_model(
                "expanded_name_path_segment", self.model_dump_json(exclude_none=True)
            )
        return self

    @classmethod
    def try_new(
        cls, namespace_uri: str | None, local_name: str, same_name_sibling_index: int
    ) -> Self:
        """Validate an owned XML expanded-name path segment through Rust.

        Args:
            namespace_uri: Namespace URI, or None for an unqualified name.
            local_name: Nonempty local element name, independent of prefix spelling.
            same_name_sibling_index: One-based index among same-expanded-name siblings.

        Returns:
            A segment without verifying membership in any source tree.

        Raises:
            LocatorError: The local name is empty or the sibling index is invalid.
        """
        value = _native.validate_domain_model(
            "expanded_name_path_segment",
            json.dumps(
                {
                    "namespace_uri": namespace_uri,
                    "local_name": local_name,
                    "same_name_sibling_index": same_name_sibling_index,
                }
            ),
        )
        return cls.model_validate_json(value, context=RUST_DOMAIN_VALIDATED)


class TreeCoordinate(ImmutableModel):
    """Source-tree location with optional byte and expanded-name evidence.

    Attributes:
        child_path: Nonempty sequence of positive, one-based child indices.
        source_bytes: Exact source-payload byte range, when available.
        expanded_name_path: Nonempty XML expanded-name path, when supplied.
            Correspondence with child_path or bytes is not checked against document
            contents.
    """
    child_path: tuple[PositiveU32, ...]
    source_bytes: ByteRange | None = None
    expanded_name_path: tuple[ExpandedNamePathSegment, ...] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def _rust_validate(self, info: ValidationInfo) -> Self:
        if info.context is not RUST_DOMAIN_VALIDATED:
            _native.validate_domain_model("tree_coordinate", self.model_dump_json())
        return self

    @classmethod
    def try_new(
        cls, child_path: tuple[int, ...], source_bytes: ByteRange | None = None
    ) -> Self:
        """Validate a child path and retain optional exact-byte evidence.

        Args:
            child_path: Nonempty sequence of positive one-based child indices.
            source_bytes: Exact source-byte range, when available.

        Returns:
            A coordinate without verifying tree membership or payload bounds.

        Raises:
            LocatorError: The child path or supplied wire data is invalid.
        """
        wire = {
            "child_path": child_path,
            "source_bytes": (
                None if source_bytes is None else source_bytes.model_dump(mode="json")
            ),
        }
        value = _native.validate_domain_model("tree_coordinate", json.dumps(wire))
        return cls.model_validate_json(value, context=RUST_DOMAIN_VALIDATED)

    @classmethod
    def with_expanded_name_path(
        cls,
        child_path: tuple[int, ...],
        source_bytes: ByteRange | None,
        expanded_name_path: tuple[ExpandedNamePathSegment, ...],
    ) -> Self:
        """Retain child-path, byte, and XML expanded-name evidence.

        Args:
            child_path: Nonempty sequence of positive one-based child indices.
            source_bytes: Exact source-byte range, when available.
            expanded_name_path: Nonempty sequence of validated expanded-name segments.

        Returns:
            A coordinate without verifying correspondence between the paths and bytes.

        Raises:
            LocatorError: A path is empty or its supplied structure is invalid.
        """
        wire = {
            "child_path": child_path,
            "source_bytes": (
                None if source_bytes is None else source_bytes.model_dump(mode="json")
            ),
            "expanded_name_path": [
                item.model_dump(mode="json") for item in expanded_name_path
            ],
        }
        value = _native.validate_domain_model("tree_coordinate", json.dumps(wire))
        return cls.model_validate_json(value, context=RUST_DOMAIN_VALIDATED)


class DomCoordinate(ImmutableModel):
    """Rendered DOM node identity scoped to one immutable snapshot epoch.

    Attributes:
        document_epoch: Snapshot epoch needed to interpret the node ID.
        node_id: Positive snapshot-local identity, without a live DOM membership check.
    """
    document_epoch: DocumentEpoch
    node_id: DomNodeId

    @model_validator(mode="after")
    def _rust_validate(self, info: ValidationInfo) -> Self:
        if info.context is not RUST_DOMAIN_VALIDATED:
            _native.validate_domain_model("dom_coordinate", self.model_dump_json())
        return self

    @classmethod
    def new(cls, document_epoch: DocumentEpoch, node_id: DomNodeId) -> Self:
        """Pair a document epoch with a rendered-DOM node identity.

        Args:
            document_epoch: Immutable rendered-DOM snapshot epoch.
            node_id: Positive snapshot-local identity.

        Returns:
            A coordinate without querying the DOM or verifying snapshot membership.

        Raises:
            LocatorError: Supplied values cannot form valid Rust coordinate data.
        """
        value = _native.validate_domain_model(
            "dom_coordinate",
            json.dumps(
                {"document_epoch": int(document_epoch), "node_id": int(node_id)}
            ),
        )
        return cls.model_validate_json(value, context=RUST_DOMAIN_VALIDATED)


class AccessibilityCoordinate(ImmutableModel):
    """Accessibility node identity scoped to an immutable snapshot epoch.

    Attributes:
        document_epoch: Snapshot epoch needed to interpret the node ID.
        node_id: Retained nonblank accessibility node identity; no live tree membership
            is checked.
    """
    document_epoch: DocumentEpoch
    node_id: str

    @model_validator(mode="after")
    def _rust_validate(self, info: ValidationInfo) -> Self:
        if info.context is not RUST_DOMAIN_VALIDATED:
            _native.validate_domain_model(
                "accessibility_coordinate", self.model_dump_json()
            )
        return self

    @classmethod
    def try_new(cls, document_epoch: DocumentEpoch, node_id: str) -> Self:
        """Validate accessibility node identity within a supplied epoch.

        Args:
            document_epoch: Immutable accessibility-tree snapshot epoch.
            node_id: Nonblank identity whose original spelling is retained.

        Returns:
            A coordinate without checking node membership in a live tree.

        Raises:
            LocatorError: The node identity is blank or supplied values are invalid.
        """
        value = _native.validate_domain_model(
            "accessibility_coordinate",
            json.dumps({"document_epoch": int(document_epoch), "node_id": node_id}),
        )
        return cls.model_validate_json(value, context=RUST_DOMAIN_VALIDATED)


class DecodedTextCoordinate(ImmutableModel):
    """Paired source-byte and decoded-text scalar offsets for a match.

    Attributes:
        byte_range: Exact retained-source byte range.
        scalar_range: Decoded-text Unicode-scalar range. Correspondence between ranges
            is supplied by the caller, not verified against text.
    """
    byte_range: ByteRange
    scalar_range: TextRange

    @model_validator(mode="after")
    def _rust_validate(self, info: ValidationInfo) -> Self:
        if info.context is not RUST_DOMAIN_VALIDATED:
            _native.validate_domain_model(
                "decoded_text_coordinate", self.model_dump_json()
            )
        return self

    @classmethod
    def new(cls, byte_range: ByteRange, scalar_range: TextRange) -> Self:
        """Pair source-byte and decoded-text scalar ranges.

        Args:
            byte_range: Exact retained-source byte offsets.
            scalar_range: Decoded-text Unicode-scalar offsets for the same match.

        Returns:
            A coordinate without verifying correspondence between the supplied ranges.

        Raises:
            LocatorError: Supplied range data cannot form a valid Rust coordinate.
        """
        value = _native.validate_domain_model(
            "decoded_text_coordinate",
            json.dumps(
                {
                    "byte_range": byte_range.model_dump(mode="json"),
                    "scalar_range": scalar_range.model_dump(mode="json"),
                }
            ),
        )
        return cls.model_validate_json(value, context=RUST_DOMAIN_VALIDATED)


class SourceTreeLocation(ImmutableModel):
    """Tagged HTML/XML tree evidence for a native finding coordinate.

    Attributes:
        kind: Discriminator fixed to source_tree for tagged decoding.
        coordinate: Child path and optional exact-byte or expanded-name evidence.
    """
    kind: Literal["source_tree"]
    coordinate: TreeCoordinate


class JsonLocation(ImmutableModel):
    """Tagged JSON Pointer evidence, without proving document resolution.

    Attributes:
        kind: Discriminator fixed to json for tagged decoding.
        coordinate: Validated pointer spelling; an empty pointer denotes the root.
    """
    kind: Literal["json"]
    coordinate: JsonCoordinate


class RenderedDomLocation(ImmutableModel):
    """Tagged rendered-DOM node evidence within a snapshot epoch.

    Attributes:
        kind: Discriminator fixed to rendered_dom for tagged decoding.
        coordinate: Snapshot epoch paired with a positive node ID.
    """
    kind: Literal["rendered_dom"]
    coordinate: DomCoordinate


class AccessibilityLocation(ImmutableModel):
    """Tagged accessibility node evidence within a snapshot epoch.

    Attributes:
        kind: Discriminator fixed to accessibility for tagged decoding.
        coordinate: Snapshot epoch paired with the retained node identity.
    """
    kind: Literal["accessibility"]
    coordinate: AccessibilityCoordinate


class DecodedTextLocation(ImmutableModel):
    """Tagged byte and Unicode-scalar evidence for a decoded-text match.

    Attributes:
        kind: Discriminator fixed to decoded_text for tagged decoding.
        coordinate: Paired ranges supplied for the same retained match.
    """
    kind: Literal["decoded_text"]
    coordinate: DecodedTextCoordinate


NativeCoordinate = Annotated[
    SourceTreeLocation
    | JsonLocation
    | RenderedDomLocation
    | AccessibilityLocation
    | DecodedTextLocation,
    Field(discriminator="kind"),
]
"""Tagged representation-native location: source tree, JSON Pointer, rendered DOM,
accessibility node, or decoded-text ranges. Interpret it with its document identity
and epoch.
"""


class NodeReference(ImmutableModel):
    """Document-bound native location, without retaining document contents.

    Attributes:
        document_id: Identity of the document required to interpret this reference.
        coordinate: Native location within that document; construction does not resolve
            it.
    """
    document_id: DocumentId
    coordinate: NativeCoordinate

    @model_validator(mode="after")
    def _rust_validate(self, info: ValidationInfo) -> Self:
        if info.context is not RUST_DOMAIN_VALIDATED:
            _native.validate_domain_model("node_reference", self.model_dump_json())
        return self

    @classmethod
    def new(cls, document_id: DocumentId, coordinate: NativeCoordinate) -> Self:
        """Pair a native location with the document needed to interpret it.

        Args:
            document_id: Identity of the retained document.
            coordinate: Native location within that document.

        Returns:
            A reference without resolving the coordinate or retaining document contents.

        Raises:
            LocatorError: Supplied values cannot form a valid Rust node reference.
        """
        wire = {
            "document_id": str(document_id),
            "coordinate": TypeAdapter(NativeCoordinate).dump_python(
                coordinate, mode="json"
            ),
        }
        value = _native.validate_domain_model("node_reference", json.dumps(wire))
        return cls.model_validate_json(value, context=RUST_DOMAIN_VALIDATED)


class Complete(ImmutableModel):
    """Evidence supports complete coverage of the requested locator scope.

    Attributes:
        status: Discriminator fixed to complete for tagged decoding. This is a
            scope-specific evidence claim, not whole-site completeness.
    """
    status: Literal["complete"]


class Partial(ImmutableModel):
    """Known evidence loss prevents an unqualified complete absence claim.

    Attributes:
        status: Discriminator fixed to partial for tagged decoding.
        reason_code: Structural explanation of evidence loss, without source excerpts.
        lost_items: Number of omitted items when known; None does not mean zero loss.
    """
    status: Literal["partial"]
    reason_code: str
    lost_items: U64 | None = None


class Unknown(ImmutableModel):
    """Evidence completeness could not be established for the requested scope.

    Attributes:
        status: Discriminator fixed to unknown for tagged decoding.
        reason_code: Structural explanation of unresolved evidence coverage.
    """
    status: Literal["unknown"]
    reason_code: str


Completeness = Annotated[Complete | Partial | Unknown, Field(discriminator="status")]
"""Tagged complete, partial, or unknown coverage of requested evidence. Complete
coverage is scoped to the operation, not an exhaustive claim about a site.
"""
IncompleteEvidence = Annotated[Partial | Unknown, Field(discriminator="status")]
"""Partial or unknown evidence that cannot establish complete absence. Known loss and
unestablished coverage remain distinct.
"""


class TextValue(ImmutableModel):
    """Owned decoded text emitted by a text projection.

    Attributes:
        kind: Discriminator fixed to text for tagged decoding.
        value: Complete projected text retained as a Python string.
    """
    kind: Literal["text"]
    value: str


class CapturedText(ImmutableModel):
    """Projected text and named regular-expression capture values.

    Attributes:
        text: Full projected text independent of captured subexpressions.
        captures: Capture names mapped to their matched text. The mapping contents
            remain mutable even though model attribute assignment is frozen.
    """
    text: str
    captures: dict[str, str]


class TextWithCaptures(ImmutableModel):
    """Tagged text projection with named regular-expression captures.

    Attributes:
        kind: Discriminator fixed to text_with_captures for tagged decoding.
        value: Full projected text paired with its named capture values.
    """
    kind: Literal["text_with_captures"]
    value: CapturedText


class Attribute(ImmutableModel):
    """One projected attribute name and decoded value.

    Attributes:
        name: Name selected by the attribute projection.
        value: Retained decoded attribute value.
    """
    name: str
    value: str


class AttributeValue(ImmutableModel):
    """Tagged attribute projection retaining its name as well as its value.

    Attributes:
        kind: Discriminator fixed to attribute for tagged decoding.
        value: Projected attribute name and decoded text.
    """
    kind: Literal["attribute"]
    value: Attribute


class JsonValueProjection(ImmutableModel):
    """Tagged JSON projection using Rust JSON value equality.

    Attributes:
        kind: Discriminator fixed to json for tagged decoding.
        value: Retained native JSON shape; nonfinite numbers are rejected. Nested
            collections remain mutable despite frozen model attributes.
    """
    kind: Literal["json"]
    value: JsonValue

    @field_validator("value")
    @classmethod
    def _require_json_numbers(cls, value: JsonValue, info: ValidationInfo) -> JsonValue:
        if info.context is RUST_DOMAIN_VALIDATED:
            return value
        # JSON cannot encode non-finite numbers. Reject them before Pydantic's
        # default JSON serializer could silently replace them with null.
        json.dumps(value, allow_nan=False)
        return value

    def __eq__(self, other: object) -> bool:
        """Compare complete JSON projections using Rust equality.

        Args:
            other: Another tagged JSON projection to compare.

        Returns:
            Rust JSON value equality, preserving distinctions that ordinary Python
            numeric equality can collapse. Other operand types return NotImplemented.
        """
        if not isinstance(other, JsonValueProjection):
            return NotImplemented
        return projected_values_equal(self, other)


class NodeValue(ImmutableModel):
    """Tagged document-bound node reference rather than a content copy.

    Attributes:
        kind: Discriminator fixed to node for tagged decoding.
        value: Document identity and native coordinate; retain the document to interpret
            it.
    """
    kind: Literal["node"]
    value: NodeReference


ProjectedValue = Annotated[
    TextValue | TextWithCaptures | AttributeValue | JsonValueProjection | NodeValue,
    Field(discriminator="kind"),
]
"""Tagged text, captured text, attribute, JSON, or document-bound node value.
Projection identity retains information omitted by convenience value accessors.
"""


def projected_values_equal(left: ProjectedValue, right: ProjectedValue) -> bool:
    """Compare complete projection values with the Rust SDK's equality rules."""
    return _native.projected_value_equal(
        left.model_dump_json(), right.model_dump_json()
    )


def projected_values_not_equal(left: ProjectedValue, right: ProjectedValue) -> bool:
    """Return the complementary Rust projection comparison."""
    return not projected_values_equal(left, right)


class RegionLineage(ImmutableModel):
    """Parent repeated-region identity and location for a finding.

    Attributes:
        region_id: Authored repeated-region identifier.
        region_ordinal: Recorded region ordinal, preserved without renumbering.
        coordinate: Native location of the repeated parent region.
    """
    region_id: RegionId
    region_ordinal: U64
    coordinate: NativeCoordinate

    @model_validator(mode="after")
    def _rust_validate(self, info: ValidationInfo) -> Self:
        if info.context is not RUST_DOMAIN_VALIDATED:
            _native.validate_domain_model("region_lineage", self.model_dump_json())
        return self

    @classmethod
    def new(
        cls, region_id: RegionId, region_ordinal: int, coordinate: NativeCoordinate
    ) -> Self:
        """Create parent-region lineage while validating wire structure.

        Args:
            region_id: Authored region identifier.
            region_ordinal: Recorded unsigned ordinal, preserved without renumbering.
            coordinate: Native parent-region location.

        Returns:
            Lineage without verifying a region plan or resolving document coordinates.

        Raises:
            LocatorError: Supplied values cannot form valid Rust lineage data.
        """
        wire = {
            "region_id": str(region_id),
            "region_ordinal": region_ordinal,
            "coordinate": TypeAdapter(NativeCoordinate).dump_python(
                coordinate, mode="json"
            ),
        }
        value = _native.validate_domain_model("region_lineage", json.dumps(wire))
        return cls.model_validate_json(value, context=RUST_DOMAIN_VALIDATED)


class Finding(ImmutableModel):
    """An ordered locator finding with projection and completeness evidence.

    Attributes:
        document_id: Document identity to which this evidence belongs.
        output_id: Authored output identity producing the finding.
        order: Global deterministic order; results require strictly increasing values.
        coordinate: Native evidence location without a copy of document contents.
        projected: Typed projection, serialized under the Rust field name value. Node
            projections must agree with the finding document and coordinate.
        completeness: Coverage claim inherited from evidence, not independently verified
            here.
        parent_region: Repeated-region lineage, or None for findings without a parent.
    """
    document_id: DocumentId
    output_id: OutputId
    order: U64
    coordinate: NativeCoordinate
    projected: ProjectedValue = Field(alias="value")
    completeness: Completeness
    parent_region: RegionLineage | None = None

    @model_validator(mode="after")
    def _rust_validate(self, info: ValidationInfo) -> Self:
        if info.context is not RUST_DOMAIN_VALIDATED:
            _native.validate_domain_model(
                "finding", self.model_dump_json(exclude_none=True)
            )
        return self

    @classmethod
    def try_new(
        cls,
        document_id: DocumentId,
        output_id: OutputId,
        order: int,
        coordinate: NativeCoordinate,
        projected: ProjectedValue,
        completeness: Completeness,
        parent_region: RegionLineage | None = None,
    ) -> Self:
        """Create a finding and check any projected node-reference identity.

        Args:
            document_id: Identity of the source evidence document.
            output_id: Authored output identifier producing this finding.
            order: Deterministic global order for the finding.
            coordinate: Native evidence location.
            projected: Typed projected value; a node reference must match the finding
                document and coordinate.
            completeness: Supplied evidence coverage claim, not independently verified.
            parent_region: Optional lineage for repeated-region evidence.

        Returns:
            A typed finding without fetching or retaining document contents.

        Raises:
            LocatorError: Projected node identity disagrees or wire data is invalid.
        """
        wire = {
            "document_id": str(document_id),
            "output_id": str(output_id),
            "order": order,
            "coordinate": TypeAdapter(NativeCoordinate).dump_python(
                coordinate, mode="json"
            ),
            "value": TypeAdapter(ProjectedValue).dump_python(projected, mode="json"),
            "completeness": TypeAdapter(Completeness).dump_python(
                completeness, mode="json"
            ),
            "parent_region": (
                None if parent_region is None else parent_region.model_dump(mode="json")
            ),
        }
        value = _native.validate_domain_model("finding", json.dumps(wire))
        return cls.model_validate_json(value, context=RUST_DOMAIN_VALIDATED)

    @property
    def value(self) -> str | JsonValue | NodeReference:
        """Return projection content without its structural projection wrapper.

        Text-with-captures yields full text; attributes yield decoded attribute text.
        Use projected to retain capture names, attribute names, and variant identity.
        """
        if isinstance(self.projected, TextWithCaptures):
            return self.projected.value.text
        if isinstance(self.projected, AttributeValue):
            return self.projected.value.value
        return self.projected.value


class LocateResult(ImmutableModel):
    """Nonempty matched regions or findings in deterministic global order.

    Attributes:
        document_id: Shared identity checked against every finding.
        regions: Unique retained region lineage, including regions with no projected
            findings.
        findings: Findings in strictly increasing global order, each referring only to a
            known parent region.
    """
    document_id: DocumentId
    regions: tuple[RegionLineage, ...]
    findings: tuple[Finding, ...]

    @model_validator(mode="after")
    def _rust_validate(self, info: ValidationInfo) -> Self:
        if info.context is not RUST_DOMAIN_VALIDATED:
            _native.validate_domain_model(
                "locate_result", self.model_dump_json(exclude_none=True)
            )
        return self

    @classmethod
    def try_new(cls, document_id: DocumentId, findings: tuple[Finding, ...]) -> Self:
        """Create an ordered result, deriving regions from finding lineage.

        Args:
            document_id: Shared identity required for every finding.
            findings: Nonempty findings with strictly increasing global order.

        Returns:
            A validated result with unique parent regions derived from the findings.

        Raises:
            LocatorError: Findings are empty, belong to another document, or violate
                deterministic order or supplied wire structure.
        """
        wire = {
            "document_id": str(document_id),
            "findings": [item.model_dump(mode="json") for item in findings],
        }
        value = _native.validate_domain_model("locate_result", json.dumps(wire))
        return cls.model_validate_json(value, context=RUST_DOMAIN_VALIDATED)

    @classmethod
    def try_new_with_regions(
        cls,
        document_id: DocumentId,
        regions: tuple[RegionLineage, ...],
        findings: tuple[Finding, ...],
    ) -> Self:
        """Create a result with explicit matched regions and ordered findings.

        Args:
            document_id: Shared identity required for every finding.
            regions: Unique matched regions, including those without projected findings.
            findings: Findings with strictly increasing order and known parent lineage.

        Returns:
            A validated result; at least one supplied collection must be nonempty.

        Raises:
            LocatorError: Collections are empty, lineage is duplicated or unknown,
                document identities differ, or finding order or wire structure is
                invalid.
        """
        wire = {
            "document_id": str(document_id),
            "regions": [item.model_dump(mode="json") for item in regions],
            "findings": [item.model_dump(mode="json") for item in findings],
        }
        value = _native.validate_domain_model(
            "locate_result_explicit", json.dumps(wire)
        )
        return cls.model_validate_json(value, context=RUST_DOMAIN_VALIDATED)


class Failure(ImmutableModel):
    """Typed terminal locator failure without hostile document excerpts.

    Attributes:
        kind: invalid_plan, parse_failed, unsupported_combination, limit_exhausted, or
            invalid_resource_policy determines which details apply.
        code: Bounded structural parser or plan identifier, when applicable.
        document: Unsupported document class for unsupported_combination.
        limit: Resource whose execution or policy boundary was rejected.
        maximum: Configured maximum in units of the named resource, when applicable.
        observed: Recorded or attempted consumption in the same units, when applicable.
    """
    kind: Literal[
        "invalid_plan",
        "parse_failed",
        "unsupported_combination",
        "limit_exhausted",
        "invalid_resource_policy",
    ]
    code: str | None = Field(default=None, exclude_if=lambda value: value is None)
    document: DocumentClassName | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    limit: ResourceLimit | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    maximum: U64 | None = Field(default=None, exclude_if=lambda value: value is None)
    observed: U64 | None = Field(default=None, exclude_if=lambda value: value is None)


LocateFailure = Failure
"""Alias for typed structural locator failure details, separate from match, complete
absence, or indeterminate evidence.
"""


class _Outcome(ImmutableModel):
    @property
    def findings(self) -> tuple[Finding, ...]:
        """Return no findings for nonmatched outcomes without claiming absence."""
        return ()

    def values(
        self, output: str | None = None
    ) -> list[str | JsonValue | NodeReference]:
        """Collect projection content, optionally filtering one authored output.

        Args:
            output: Output identifier to select, or None for all retained findings.

        Returns:
            A new list of projection contents. An empty list alone cannot distinguish
            complete absence, indeterminate evidence, or failure; inspect the outcome.
        """
        return [
            finding.value
            for finding in self.findings
            if output is None or finding.output_id == output
        ]


class Matched(_Outcome):
    """At least one region or finding matched, possibly with partial evidence.

    Attributes:
        status: Discriminator fixed to matched for tagged decoding.
        result: Validated nonempty region or finding collection. Inspect finding
            completeness before making absence claims.
    """
    status: Literal["matched"]
    result: LocateResult

    @property
    def findings(self) -> tuple[Finding, ...]:
        """Return retained findings in strictly increasing deterministic order."""
        return self.result.findings


class NoMatch(_Outcome):
    """Complete locator execution found no match within the requested scope.

    Attributes:
        status: Discriminator fixed to no_match for tagged decoding.
        document_id: Document whose complete evidence supports this scope-specific
            absence claim.
    """
    status: Literal["no_match"]
    document_id: DocumentId


class Indeterminate(_Outcome):
    """No match was established and incomplete evidence prevents absence claims.

    Attributes:
        status: Discriminator fixed to indeterminate for tagged decoding.
        document_id: Examined document identity.
        completeness: Partial or unknown evidence limiting the absence claim.
        reason_code: Structural explanation of why absence could not be established.
    """
    status: Literal["indeterminate"]
    document_id: DocumentId
    completeness: IncompleteEvidence
    reason_code: str


class LocateFailed(_Outcome):
    """Execution ended with a typed failure instead of a match or absence claim.

    Attributes:
        status: Discriminator fixed to failed for tagged decoding.
        failure: Bounded structural failure details without document excerpts.
    """
    status: Literal["failed"]
    failure: Failure


LocateOutcome = Annotated[
    Matched | NoMatch | Indeterminate | LocateFailed,
    Field(discriminator="status"),
]
"""Tagged matches, complete no-match, indeterminate evidence, or typed failure. An
empty convenience list alone cannot distinguish these states.
"""
_adapter: TypeAdapter[LocateOutcome] = TypeAdapter(LocateOutcome)


def _read(value: str) -> LocateOutcome:
    return _adapter.validate_json(value, context=RUST_DOMAIN_VALIDATED)
