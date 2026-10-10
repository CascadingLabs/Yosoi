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
PositiveU32 = Annotated[int, Field(strict=True, gt=0, le=(1 << 32) - 1)]
U64 = Annotated[int, Field(strict=True, ge=0, le=(1 << 64) - 1)]
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
DocumentClassName = Literal[
    "source_html",
    "source_xml",
    "source_json",
    "source_text",
    "rendered_dom",
    "accessibility_tree",
]


class ByteRange(ImmutableModel):
    start: U64
    end: U64

    @model_validator(mode="after")
    def _rust_validate(self, info: ValidationInfo) -> Self:
        if info.context is not RUST_DOMAIN_VALIDATED:
            _native.validate_domain_model("byte_range", self.model_dump_json())
        return self

    @classmethod
    def try_new(cls, start: int, end: int) -> Self:
        value = _native.validate_domain_model(
            "byte_range", json.dumps({"start": start, "end": end})
        )
        return cls.model_validate_json(value, context=RUST_DOMAIN_VALIDATED)


class TextRange(ImmutableModel):
    start: U64
    end: U64

    @model_validator(mode="after")
    def _rust_validate(self, info: ValidationInfo) -> Self:
        if info.context is not RUST_DOMAIN_VALIDATED:
            _native.validate_domain_model("text_range", self.model_dump_json())
        return self

    @classmethod
    def try_new(cls, start: int, end: int) -> Self:
        value = _native.validate_domain_model(
            "text_range", json.dumps({"start": start, "end": end})
        )
        return cls.model_validate_json(value, context=RUST_DOMAIN_VALIDATED)


class ExpandedNamePathSegment(ImmutableModel):
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
    document_epoch: DocumentEpoch
    node_id: DomNodeId

    @model_validator(mode="after")
    def _rust_validate(self, info: ValidationInfo) -> Self:
        if info.context is not RUST_DOMAIN_VALIDATED:
            _native.validate_domain_model("dom_coordinate", self.model_dump_json())
        return self

    @classmethod
    def new(cls, document_epoch: DocumentEpoch, node_id: DomNodeId) -> Self:
        value = _native.validate_domain_model(
            "dom_coordinate",
            json.dumps(
                {"document_epoch": int(document_epoch), "node_id": int(node_id)}
            ),
        )
        return cls.model_validate_json(value, context=RUST_DOMAIN_VALIDATED)


class AccessibilityCoordinate(ImmutableModel):
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
        value = _native.validate_domain_model(
            "accessibility_coordinate",
            json.dumps({"document_epoch": int(document_epoch), "node_id": node_id}),
        )
        return cls.model_validate_json(value, context=RUST_DOMAIN_VALIDATED)


class DecodedTextCoordinate(ImmutableModel):
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
    kind: Literal["source_tree"]
    coordinate: TreeCoordinate


class JsonLocation(ImmutableModel):
    kind: Literal["json"]
    coordinate: JsonCoordinate


class RenderedDomLocation(ImmutableModel):
    kind: Literal["rendered_dom"]
    coordinate: DomCoordinate


class AccessibilityLocation(ImmutableModel):
    kind: Literal["accessibility"]
    coordinate: AccessibilityCoordinate


class DecodedTextLocation(ImmutableModel):
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


class NodeReference(ImmutableModel):
    document_id: DocumentId
    coordinate: NativeCoordinate

    @model_validator(mode="after")
    def _rust_validate(self, info: ValidationInfo) -> Self:
        if info.context is not RUST_DOMAIN_VALIDATED:
            _native.validate_domain_model("node_reference", self.model_dump_json())
        return self

    @classmethod
    def new(cls, document_id: DocumentId, coordinate: NativeCoordinate) -> Self:
        wire = {
            "document_id": str(document_id),
            "coordinate": TypeAdapter(NativeCoordinate).dump_python(
                coordinate, mode="json"
            ),
        }
        value = _native.validate_domain_model("node_reference", json.dumps(wire))
        return cls.model_validate_json(value, context=RUST_DOMAIN_VALIDATED)


class Complete(ImmutableModel):
    status: Literal["complete"]


class Partial(ImmutableModel):
    status: Literal["partial"]
    reason_code: str
    lost_items: U64 | None = None


class Unknown(ImmutableModel):
    status: Literal["unknown"]
    reason_code: str


Completeness = Annotated[Complete | Partial | Unknown, Field(discriminator="status")]
IncompleteEvidence = Annotated[Partial | Unknown, Field(discriminator="status")]


class TextValue(ImmutableModel):
    kind: Literal["text"]
    value: str


class CapturedText(ImmutableModel):
    text: str
    captures: dict[str, str]


class TextWithCaptures(ImmutableModel):
    kind: Literal["text_with_captures"]
    value: CapturedText


class Attribute(ImmutableModel):
    name: str
    value: str


class AttributeValue(ImmutableModel):
    kind: Literal["attribute"]
    value: Attribute


class JsonValueProjection(ImmutableModel):
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
        if not isinstance(other, JsonValueProjection):
            return NotImplemented
        return projected_values_equal(self, other)


class NodeValue(ImmutableModel):
    kind: Literal["node"]
    value: NodeReference


ProjectedValue = Annotated[
    TextValue | TextWithCaptures | AttributeValue | JsonValueProjection | NodeValue,
    Field(discriminator="kind"),
]


def projected_values_equal(left: ProjectedValue, right: ProjectedValue) -> bool:
    """Compare complete projection values with the Rust SDK's equality rules."""
    return _native.projected_value_equal(
        left.model_dump_json(), right.model_dump_json()
    )


def projected_values_not_equal(left: ProjectedValue, right: ProjectedValue) -> bool:
    """Return the complementary Rust projection comparison."""
    return not projected_values_equal(left, right)


class RegionLineage(ImmutableModel):
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
        if isinstance(self.projected, TextWithCaptures):
            return self.projected.value.text
        if isinstance(self.projected, AttributeValue):
            return self.projected.value.value
        return self.projected.value


class LocateResult(ImmutableModel):
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


class _Outcome(ImmutableModel):
    @property
    def findings(self) -> tuple[Finding, ...]:
        return ()

    def values(
        self, output: str | None = None
    ) -> list[str | JsonValue | NodeReference]:
        return [
            finding.value
            for finding in self.findings
            if output is None or finding.output_id == output
        ]


class Matched(_Outcome):
    status: Literal["matched"]
    result: LocateResult

    @property
    def findings(self) -> tuple[Finding, ...]:
        return self.result.findings


class NoMatch(_Outcome):
    status: Literal["no_match"]
    document_id: DocumentId


class Indeterminate(_Outcome):
    status: Literal["indeterminate"]
    document_id: DocumentId
    completeness: IncompleteEvidence
    reason_code: str


class LocateFailed(_Outcome):
    status: Literal["failed"]
    failure: Failure


LocateOutcome = Annotated[
    Matched | NoMatch | Indeterminate | LocateFailed,
    Field(discriminator="status"),
]
_adapter: TypeAdapter[LocateOutcome] = TypeAdapter(LocateOutcome)


def _read(value: str) -> LocateOutcome:
    return _adapter.validate_json(value, context=RUST_DOMAIN_VALIDATED)
