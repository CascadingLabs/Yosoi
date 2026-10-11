"""Runtime-authored Rust Contracts over arbitrary public schemas."""

from __future__ import annotations

import json
from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated, Any, Literal

from pydantic import Field, PrivateAttr, TypeAdapter, field_serializer, model_validator

from . import _native
from ._models import ImmutableModel, NativeAuthoringModel
from .contracts import (
    ContractIssues,
    ContractSchema,
    ExtractionDiagnostic,
    ExtractionLimits,
    FieldIssue,
    Money,
    ValidationLimits,
)
from .documents import BoundDocument, Document, ParsedDocument
from .identities import ContractIdentity
from .locators import Plan
from .outcomes import (
    U64,
    Failure,
    Finding,
    IncompleteEvidence,
    LocateOutcome,
    RegionLineage,
)
from .scalars import RUST_DOMAIN_VALIDATED, FieldId


class RuntimeCandidate(ImmutableModel):
    """Retain raw findings for every field of one runtime candidate.

    Findings have not yet passed cardinality or value conversion checks.

    Attributes:
        document_id: Identity of the document whose evidence was grouped.
        region: Grouping region lineage, or None for an ungrouped candidate.
        fields: Read-only field-to-findings mapping, including empty tuples for missing
            evidence.
    """

    document_id: str
    region: RegionLineage | None = None
    fields: Mapping[str, tuple[Finding, ...]]

    @model_validator(mode="after")
    def _freeze_fields(self) -> RuntimeCandidate:
        object.__setattr__(
            self,
            "fields",
            MappingProxyType(
                {
                    str(FieldId(field_id)): tuple(evidence)
                    for field_id, evidence in self.fields.items()
                }
            ),
        )
        return self

    @field_serializer("fields", when_used="always")
    def _serialize_fields(
        self, value: Mapping[str, tuple[Finding, ...]]
    ) -> dict[str, list[dict[str, Any]]]:
        return {
            str(field_id): [finding.model_dump(mode="json") for finding in evidence]
            for field_id, evidence in value.items()
        }


class RuntimeString(ImmutableModel):
    """Carry a string accepted by runtime Contract validation.

    Attributes:
        type: Wire discriminator identifying a string value.
        value: Validated string content.
    """
    type: Literal["string"]
    value: str


class RuntimeMoneyUsd(ImmutableModel):
    """Carry a USD amount accepted by runtime Contract validation.

    Attributes:
        type: Wire discriminator identifying USD money.
        value: Typed Money value retaining its currency and minor-unit amount.
    """
    type: Literal["money_usd"]
    value: Money


type RuntimeValue = Annotated[
    RuntimeString | RuntimeMoneyUsd, Field(discriminator="type")
]
"""String or USD Money value tagged by its runtime wire type."""


class RuntimeExactlyOne(ImmutableModel):
    """Carry the single value accepted for a required field.

    Attributes:
        cardinality: Wire discriminator for exactly-one cardinality.
        value: Validated value; missing or repeated evidence cannot produce this
            variant.
    """
    cardinality: Literal["exactly_one"]
    value: RuntimeValue


class RuntimeZeroOrOne(ImmutableModel):
    """Carry an optional field after cardinality and conversion checks.

    Attributes:
        cardinality: Wire discriminator for zero-or-one cardinality.
        value: Validated value, or None when the optional field has no evidence.
    """
    cardinality: Literal["zero_or_one"]
    value: RuntimeValue | None


class RuntimeMany(ImmutableModel):
    """Carry all accepted values for a repeated field.

    Attributes:
        cardinality: Wire discriminator for many cardinality.
        values: Ordered validated values; an empty tuple is permitted.
    """
    cardinality: Literal["many"]
    values: tuple[RuntimeValue, ...]


type RuntimeFieldValue = Annotated[
    RuntimeExactlyOne | RuntimeZeroOrOne | RuntimeMany,
    Field(discriminator="cardinality"),
]
"""Validated runtime field value tagged by its declared cardinality."""


class RuntimeValidatedRecord(ImmutableModel):
    """Pair accepted field values with their original candidate evidence.

    Attributes:
        value: Read-only mapping from schema field IDs to typed cardinality/value
            results.
        candidate: Raw grouped findings from which this record was validated.
    """
    value: Mapping[str, RuntimeFieldValue]
    candidate: RuntimeCandidate

    @model_validator(mode="after")
    def _freeze_value(self) -> RuntimeValidatedRecord:
        object.__setattr__(
            self,
            "value",
            MappingProxyType(
                {
                    str(FieldId(field_id)): field_value
                    for field_id, field_value in self.value.items()
                }
            ),
        )
        return self

    @field_serializer("value", when_used="always")
    def _serialize_value(
        self, value: Mapping[str, RuntimeFieldValue]
    ) -> dict[str, dict[str, Any]]:
        return {
            str(field_id): field_value.model_dump(mode="json")
            for field_id, field_value in value.items()
        }


class RuntimeRecordIssue(ImmutableModel):
    """Retain a rejected candidate and its field validation issues.

    Attributes:
        candidate: Raw findings for the candidate that failed validation.
        fields: Field-specific cardinality, conversion, or provenance issues.
    """
    candidate: RuntimeCandidate
    fields: tuple[FieldIssue, ...]


class ArchivedContractCandidateField(ImmutableModel):
    """Store portable evidence for one archived candidate field.

    Attributes:
        id: Schema field identity.
        evidence: Original findings retained for audit or later inspection.
    """
    id: FieldId
    evidence: tuple[Finding, ...] = Field(repr=False)


class ArchivedContractString(ImmutableModel):
    """Store a validated string in the portable archive format.

    Attributes:
        type: Wire discriminator for archived string values.
        value: Retained string content; hidden from the default repr.
    """
    type: Literal["string"]
    value: str = Field(repr=False)


class ArchivedContractMoneyUsd(ImmutableModel):
    """Store USD money as a portable signed minor-unit amount.

    Attributes:
        type: Wire discriminator for archived USD values.
        minor_units: Signed 64-bit count of cents; the DTO bounds the integer without
            revalidating a Contract.
    """
    type: Literal["money_usd"]
    minor_units: Annotated[
        int, Field(strict=True, ge=-(2**63), le=2**63 - 1, repr=False)
    ]


type ArchivedContractValue = Annotated[
    ArchivedContractString | ArchivedContractMoneyUsd, Field(discriminator="type")
]
"""Portable string or signed USD minor-unit value tagged by type."""


class _ArchivedExactlyOne(ImmutableModel):
    cardinality: Literal["exactly_one"]
    value: ArchivedContractValue


class _ArchivedZeroOrOne(ImmutableModel):
    cardinality: Literal["zero_or_one"]
    value: ArchivedContractValue | None


class _ArchivedMany(ImmutableModel):
    cardinality: Literal["many"]
    values: tuple[ArchivedContractValue, ...]


type ArchivedContractFieldValue = Annotated[
    _ArchivedExactlyOne | _ArchivedZeroOrOne | _ArchivedMany,
    Field(discriminator="cardinality"),
]
"""Portable field value tagged as required, optional, or repeated."""


class ArchivedContractField(ImmutableModel):
    """Pair an archived schema field ID with its accepted value.

    Attributes:
        id: Identity of the field in the archive schema.
        value: Portable value with an explicit cardinality discriminator.
    """
    id: FieldId
    value: ArchivedContractFieldValue = Field(repr=False)


class ArchivedValidatedContractRecord(ImmutableModel):
    """Retain accepted portable values together with source evidence.

    Attributes:
        document_id: Identity of the source document.
        region: Grouping region lineage, or None for an ungrouped record.
        fields: Accepted field values in the portable archive representation.
        evidence: Original per-field findings accompanying the accepted values.
    """
    document_id: str
    region: RegionLineage | None = None
    fields: tuple[ArchivedContractField, ...] = Field(repr=False)
    evidence: tuple[ArchivedContractCandidateField, ...] = Field(repr=False)


class ArchivedContractRecordIssue(ImmutableModel):
    """Retain a rejected portable candidate with its field issues.

    Attributes:
        document_id: Identity of the source document.
        region: Grouping region lineage, or None for an ungrouped candidate.
        candidate_fields: Original findings grouped by schema field ID.
        fields: Reasons the candidate did not become an accepted record.
    """
    document_id: str
    region: RegionLineage | None = None
    candidate_fields: tuple[ArchivedContractCandidateField, ...] = Field(repr=False)
    fields: tuple[FieldIssue, ...] = Field(repr=False)


ArchivedExtractionLimitName = Literal[
    "scanned_regions",
    "scanned_findings",
    "matching_findings",
    "candidates",
    "values_per_field",
    "retained_evidence",
    "diagnostics",
]
"""Names of bounded extraction counters recorded in portable failures."""


class _ArchivedInvalidSchema(ImmutableModel):
    kind: Literal["invalid_contract_schema"]


class _ArchivedExtractionCountOverflow(ImmutableModel):
    kind: Literal["count_overflow"]
    limit: ArchivedExtractionLimitName


class _ArchivedGroupingIndexInvariant(ImmutableModel):
    kind: Literal["grouping_index_invariant"]


class _ArchivedExtractionLimitExceeded(ImmutableModel):
    kind: Literal["limit_exceeded"]
    limit: ArchivedExtractionLimitName
    maximum: U64
    observed: U64


type ArchivedExtractionFailure = Annotated[
    _ArchivedInvalidSchema
    | _ArchivedExtractionCountOverflow
    | _ArchivedGroupingIndexInvariant
    | _ArchivedExtractionLimitExceeded,
    Field(discriminator="kind"),
]
"""Portable schema, counting, grouping, or extraction-budget rejection."""


class _ArchivedValidationOverflow(ImmutableModel):
    kind: Literal[
        "field_count_overflow",
        "record_count_overflow",
        "conversion_count_overflow",
        "issue_count_overflow",
        "provenance_count_overflow",
    ]


class _ArchivedValidationLimitExceeded(ImmutableModel):
    kind: Literal[
        "field_limit_exceeded",
        "record_limit_exceeded",
        "conversion_limit_exceeded",
        "issue_limit_exceeded",
        "provenance_limit_exceeded",
    ]
    maximum: U64
    observed: U64


type ArchivedValidationFailure = Annotated[
    _ArchivedInvalidSchema
    | _ArchivedValidationOverflow
    | _ArchivedValidationLimitExceeded,
    Field(discriminator="kind"),
]
"""Portable schema, counting, or validation-budget rejection."""


class _ArchivedOutcomeBase(ImmutableModel):
    pass


class _ArchivedEvaluated(_ArchivedOutcomeBase):
    status: Literal["evaluated"]
    document_id: str
    records: tuple[ArchivedValidatedContractRecord, ...]
    issues: tuple[ArchivedContractRecordIssue, ...]
    extraction_diagnostics: tuple[ExtractionDiagnostic, ...]


class _ArchivedNoMatch(_ArchivedOutcomeBase):
    status: Literal["no_match"]
    document_id: str


class _ArchivedIndeterminate(_ArchivedOutcomeBase):
    status: Literal["indeterminate"]
    document_id: str
    completeness: IncompleteEvidence
    reason_code: str


class _ArchivedLocateFailed(_ArchivedOutcomeBase):
    status: Literal["locate_failed"]
    failure: Failure


class _ArchivedExtractionRejected(_ArchivedOutcomeBase):
    status: Literal["extraction_rejected"]
    failure: ArchivedExtractionFailure


class _ArchivedValidationRejected(_ArchivedOutcomeBase):
    status: Literal["validation_rejected"]
    failure: ArchivedValidationFailure


type ArchivedContractOutcomeData = Annotated[
    _ArchivedEvaluated
    | _ArchivedNoMatch
    | _ArchivedIndeterminate
    | _ArchivedLocateFailed
    | _ArchivedExtractionRejected
    | _ArchivedValidationRejected,
    Field(discriminator="status"),
]
"""Portable outcome variants tagged by evaluation or phase-failure status."""
_archived_outcome_adapter: TypeAdapter[ArchivedContractOutcomeData] = TypeAdapter(
    ArchivedContractOutcomeData
)


class ArchivedContractOutcome:
    """Inspect a portable Contract outcome without a live Rust handle.

    Parsing verifies the archive structure; it does not re-execute extraction or prove
    business success. The original JSON is retained unchanged.

    Attributes:
        view: Immutable status-tagged DTO parsed from the supplied archive JSON.
    """

    __slots__ = ("view", "_json", "_sealed")

    def __init__(self, value: str) -> None:
        """Parse a portable archive and seal its typed view.

        Args:
            value: Archive JSON emitted by Rust or a retained portable artifact.

        Raises:
            ValueError: JSON is malformed or does not match an archive outcome variant.
        """
        wire = json.loads(value)
        self.view: ArchivedContractOutcomeData = (
            _archived_outcome_adapter.validate_python(
                wire, context=RUST_DOMAIN_VALIDATED
            )
        )
        self._json = value
        self._sealed = True

    def __setattr__(self, name: str, value: Any) -> None:
        """Reject attribute replacement once this outcome has been initialized."""
        if getattr(self, "_sealed", False):
            raise AttributeError("ArchivedContractOutcome is read-only")
        object.__setattr__(self, name, value)

    @property
    def status(self) -> str:
        """Return the wire status; it does not alone prove business success."""
        return self.view.status

    @property
    def document_id(self) -> str | None:
        """Return the source document identity when this status carries one."""
        return getattr(self.view, "document_id", None)

    @property
    def completeness(self) -> IncompleteEvidence | None:
        """Return incomplete-evidence details for an indeterminate result, else None."""
        return getattr(self.view, "completeness", None)

    @property
    def reason_code(self) -> str | None:
        """Return the indeterminate reason code, or None for other statuses."""
        return getattr(self.view, "reason_code", None)

    @property
    def failure(
        self,
    ) -> Failure | ArchivedExtractionFailure | ArchivedValidationFailure | None:
        """Return the typed phase failure, or None when this status has no failure."""
        return getattr(self.view, "failure", None)

    @property
    def records(self) -> tuple[ArchivedValidatedContractRecord, ...]:
        """Return accepted records for evaluated results, otherwise an empty tuple."""
        return self.view.records if isinstance(self.view, _ArchivedEvaluated) else ()

    @property
    def issues(self) -> tuple[ArchivedContractRecordIssue, ...]:
        """Return evaluated candidate issues, or an empty tuple otherwise."""
        return self.view.issues if isinstance(self.view, _ArchivedEvaluated) else ()

    @property
    def extraction_diagnostics(self) -> tuple[ExtractionDiagnostic, ...]:
        """Return evaluated extraction diagnostics, otherwise an empty tuple."""
        return (
            self.view.extraction_diagnostics
            if isinstance(self.view, _ArchivedEvaluated)
            else ()
        )

    def to_json(self) -> str:
        """Return the original archive JSON unchanged."""
        return self._json

    def model_dump(self) -> dict[str, Any]:
        """Decode the original wire into a new dictionary."""
        return json.loads(self._json)

    def model_dump_json(self) -> str:
        """Return the original archive JSON unchanged."""
        return self._json


def _archived_outcome(
    handle: _native.ContractOutcome, schema: ContractSchema
) -> ArchivedContractOutcome:
    return ArchivedContractOutcome(handle.to_archived(schema.model_dump_json()))


ExtractionLimitName = Literal[
    "scanned_regions",
    "scanned_findings",
    "matching_findings",
    "candidates",
    "values_per_field",
    "retained_evidence",
    "diagnostics",
]
"""Names of Rust extraction budgets reported by runtime rejection details."""


class _ContractSchemaErrorNoDetails(ImmutableModel):
    pass


class _ContractSchemaErrorFieldDetails(ImmutableModel):
    field: FieldId


class _ContractSchemaErrorVersionDetails(ImmutableModel):
    observed: Annotated[int, Field(strict=True, ge=0, le=(1 << 32) - 1)]


class _ContractSchemaErrorUnit(ImmutableModel):
    variant: Literal[
        "ZeroVersion",
        "EmptyContractId",
        "EmptyFieldId",
        "EmptyContractDescription",
        "NoFields",
        "LengthOverflow",
    ]
    details: _ContractSchemaErrorNoDetails


class _ContractSchemaErrorUnsupportedVersion(ImmutableModel):
    variant: Literal["UnsupportedVersion"]
    details: _ContractSchemaErrorVersionDetails


class _ContractSchemaErrorField(ImmutableModel):
    variant: Literal["EmptyFieldDescription", "EmptyValueType", "DuplicateField"]
    details: _ContractSchemaErrorFieldDetails


type ContractSchemaFailure = Annotated[
    _ContractSchemaErrorUnit
    | _ContractSchemaErrorUnsupportedVersion
    | _ContractSchemaErrorField,
    Field(discriminator="variant"),
]
"""Structured Rust schema error tagged by its variant and typed details."""


class _InvalidSchemaFailure(ImmutableModel):
    kind: Literal["invalid_contract_schema"]
    message: str
    # Keep Rust's Display text intact; structured data is carried separately.
    schema_error: ContractSchemaFailure | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class _ExtractionCountOverflow(ImmutableModel):
    kind: Literal["count_overflow"]
    limit: ExtractionLimitName


class _GroupingIndexInvariant(ImmutableModel):
    kind: Literal["grouping_index_invariant"]


class _ExtractionLimitExceeded(ImmutableModel):
    kind: Literal["limit_exceeded"]
    limit: ExtractionLimitName
    maximum: U64
    observed: U64


type RuntimeExtractionFailure = Annotated[
    _InvalidSchemaFailure
    | _ExtractionCountOverflow
    | _GroupingIndexInvariant
    | _ExtractionLimitExceeded,
    Field(discriminator="kind"),
]
"""Typed schema, counting, grouping, or extraction-budget rejection."""


class _InvalidValidationSchema(ImmutableModel):
    kind: Literal["invalid_contract_schema"]
    message: str
    schema_error: ContractSchemaFailure | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class _ValidationOverflow(ImmutableModel):
    kind: Literal[
        "field_count_overflow",
        "record_count_overflow",
        "conversion_count_overflow",
        "issue_count_overflow",
        "provenance_count_overflow",
    ]


class _ValidationLimitExceeded(ImmutableModel):
    kind: Literal[
        "field_limit_exceeded",
        "record_limit_exceeded",
        "conversion_limit_exceeded",
        "issue_limit_exceeded",
        "provenance_limit_exceeded",
    ]
    maximum: U64
    observed: U64


type RuntimeValidationFailure = Annotated[
    _InvalidValidationSchema | _ValidationOverflow | _ValidationLimitExceeded,
    Field(discriminator="kind"),
]
"""Typed schema, counting, or validation-budget rejection."""


class _RuntimeExtractedBase(ImmutableModel):
    pass


class _RuntimeCandidates(_RuntimeExtractedBase):
    status: Literal["candidates"]
    document_id: str
    candidates: tuple[RuntimeCandidate, ...]
    diagnostics: tuple[ExtractionDiagnostic, ...]


class _RuntimeNoMatch(_RuntimeExtractedBase):
    status: Literal["no_match"]
    document_id: str


class _RuntimeIndeterminate(_RuntimeExtractedBase):
    status: Literal["indeterminate"]
    document_id: str
    completeness: IncompleteEvidence
    reason_code: str


class _RuntimeLocateFailed(_RuntimeExtractedBase):
    status: Literal["locate_failed"]
    failure: Failure


class _RuntimeRejected(_RuntimeExtractedBase):
    status: Literal["rejected"]
    failure: RuntimeExtractionFailure


type RuntimeExtractedData = Annotated[
    _RuntimeCandidates
    | _RuntimeNoMatch
    | _RuntimeIndeterminate
    | _RuntimeLocateFailed
    | _RuntimeRejected,
    Field(discriminator="status"),
]
"""Extraction variants distinguishing candidates from incomplete or failed work."""
_runtime_extracted_adapter: TypeAdapter[RuntimeExtractedData] = TypeAdapter(
    RuntimeExtractedData
)


class _RuntimeOutcomeBase(ImmutableModel):
    pass


class _RuntimeEvaluated(_RuntimeOutcomeBase):
    status: Literal["evaluated"]
    document_id: str
    records: tuple[RuntimeValidatedRecord, ...]
    issues: tuple[RuntimeRecordIssue, ...]
    extraction_diagnostics: tuple[ExtractionDiagnostic, ...]


class _RuntimeOutcomeNoMatch(_RuntimeOutcomeBase):
    status: Literal["no_match"]
    document_id: str


class _RuntimeOutcomeIndeterminate(_RuntimeOutcomeBase):
    status: Literal["indeterminate"]
    document_id: str
    completeness: IncompleteEvidence
    reason_code: str


class _RuntimeOutcomeLocateFailed(_RuntimeOutcomeBase):
    status: Literal["locate_failed"]
    failure: Failure


class _RuntimeExtractionRejected(_RuntimeOutcomeBase):
    status: Literal["extraction_rejected"]
    failure: RuntimeExtractionFailure


class _RuntimeValidationRejected(_RuntimeOutcomeBase):
    status: Literal["validation_rejected"]
    failure: RuntimeValidationFailure


type RuntimeContractOutcomeData = Annotated[
    _RuntimeEvaluated
    | _RuntimeOutcomeNoMatch
    | _RuntimeOutcomeIndeterminate
    | _RuntimeOutcomeLocateFailed
    | _RuntimeExtractionRejected
    | _RuntimeValidationRejected,
    Field(discriminator="status"),
]
"""Validation variants retaining accepted records, issues, or phase failures."""
_runtime_outcome_adapter: TypeAdapter[RuntimeContractOutcomeData] = TypeAdapter(
    RuntimeContractOutcomeData
)


def _complete_candidate_fields(
    candidate: dict[str, Any], schema: ContractSchema
) -> dict[str, Any]:
    present = candidate.get("fields", {})
    candidate["fields"] = {
        field.id: present.get(field.id, []) for field in schema.fields
    }
    return candidate


def _complete_outcome_candidates(
    wire: dict[str, Any], schema: ContractSchema
) -> dict[str, Any]:
    for record in wire.get("records", []):
        _complete_candidate_fields(record["candidate"], schema)
    for issue in wire.get("issues", []):
        _complete_candidate_fields(issue["candidate"], schema)
    return wire


class RuntimeExtracted:
    """Inspect runtime extraction results while retaining the Rust handle.

    The Python view includes empty tuples for missing candidate fields. JSON
    serialization preserves the original Rust wire, which may omit those entries.

    Attributes:
        contract_schema: Schema used to interpret and complete candidate field mappings.
        view: Immutable status-tagged extraction DTO with every schema field
            represented.
    """

    __slots__ = ("contract_schema", "_handle", "view", "_sealed")

    def __init__(
        self,
        contract_schema: ContractSchema,
        handle: _native.Extracted,
    ) -> None:
        """Parse a native extraction result and seal the Python view.

        Args:
            contract_schema: Schema that supplies missing candidate field entries.
            handle: Rust extraction result retained for subsequent operations.

        Raises:
            ValueError: Native JSON does not match the expected outcome structure.
        """
        wire = json.loads(handle.to_json())
        if wire["status"] == "candidates":
            wire["candidates"] = [
                _complete_candidate_fields(candidate, contract_schema)
                for candidate in wire["candidates"]
            ]
        view = _runtime_extracted_adapter.validate_python(
            wire, context=RUST_DOMAIN_VALIDATED
        )
        self.contract_schema = contract_schema
        self._handle = handle
        self.view: RuntimeExtractedData = view
        self._sealed = True

    def __setattr__(self, name: str, value: Any) -> None:
        """Reject attribute replacement once this outcome has been initialized."""
        if getattr(self, "_sealed", False):
            raise AttributeError("RuntimeExtracted is read-only")
        object.__setattr__(self, name, value)

    @property
    def status(self) -> str:
        """Return the wire status; it does not alone prove business success."""
        return self.view.status

    @property
    def candidates(self) -> tuple[RuntimeCandidate, ...]:
        """Return unvalidated candidates, or an empty tuple for other statuses."""
        return self.view.candidates if isinstance(self.view, _RuntimeCandidates) else ()

    @property
    def diagnostics(self) -> tuple[ExtractionDiagnostic, ...]:
        """Return candidate diagnostics, or an empty tuple for other statuses."""
        return (
            self.view.diagnostics if isinstance(self.view, _RuntimeCandidates) else ()
        )

    @property
    def document_id(self) -> str | None:
        """Return the source document identity when this status carries one."""
        return getattr(self.view, "document_id", None)

    @property
    def completeness(self) -> IncompleteEvidence | None:
        """Return incomplete-evidence details for an indeterminate result, else None."""
        return getattr(self.view, "completeness", None)

    @property
    def reason_code(self) -> str | None:
        """Return the indeterminate reason code, or None for other statuses."""
        return getattr(self.view, "reason_code", None)

    @property
    def failure(self) -> Failure | RuntimeExtractionFailure | None:
        """Return the typed phase failure, or None when this status has no failure."""
        return getattr(self.view, "failure", None)

    def validate(
        self, *, limits: ValidationLimits | None = None
    ) -> RuntimeContractOutcome:
        """Validate extracted candidates in Rust without discarding this view.

        Args:
            limits: Optional validation budgets; None uses Rust defaults.

        Returns:
            Status-tagged outcome retaining accepted records and rejected candidates.
            Incomplete evidence and phase rejection remain explicit outcome variants.
        """
        handle = self._handle.validate(
            None if limits is None else limits.model_dump_json()
        )
        return RuntimeContractOutcome(self.contract_schema, handle)

    def to_json(self) -> str:
        """Return the original Rust wire JSON without serializing the enriched view."""
        return self._handle.to_json()

    def model_dump(self) -> dict[str, Any]:
        """Decode the original wire into a new dictionary."""
        return json.loads(self.to_json())

    def model_dump_json(self) -> str:
        """Return the original Rust wire JSON without serializing the enriched view."""
        return self.to_json()


class RuntimeContractOutcome:
    """Inspect runtime validation results while retaining the Rust handle.

    The Python view includes empty tuples for missing candidate fields. JSON
    serialization preserves the original Rust wire, which may omit those entries.

    Attributes:
        contract_schema: Schema used to interpret and complete candidate field mappings.
        view: Immutable status-tagged validation DTO with every schema field
            represented.
    """

    __slots__ = ("contract_schema", "_handle", "view", "_sealed")

    def __init__(
        self,
        contract_schema: ContractSchema,
        handle: _native.ContractOutcome,
    ) -> None:
        """Parse a native validation result and seal the Python view.

        Args:
            contract_schema: Schema that supplies missing candidate field entries.
            handle: Rust validation result retained for subsequent operations.

        Raises:
            ValueError: Native JSON does not match the expected outcome structure.
        """
        wire = _complete_outcome_candidates(
            json.loads(handle.to_json()), contract_schema
        )
        view = _runtime_outcome_adapter.validate_python(
            wire, context=RUST_DOMAIN_VALIDATED
        )
        self.contract_schema = contract_schema
        self._handle = handle
        self.view: RuntimeContractOutcomeData = view
        self._sealed = True

    def __setattr__(self, name: str, value: Any) -> None:
        """Reject attribute replacement once this outcome has been initialized."""
        if getattr(self, "_sealed", False):
            raise AttributeError("RuntimeContractOutcome is read-only")
        object.__setattr__(self, name, value)

    @property
    def status(self) -> str:
        """Return the wire status; it does not alone prove business success."""
        return self.view.status

    @property
    def document_id(self) -> str | None:
        """Return the source document identity when this status carries one."""
        return getattr(self.view, "document_id", None)

    @property
    def completeness(self) -> IncompleteEvidence | None:
        """Return incomplete-evidence details for an indeterminate result, else None."""
        return getattr(self.view, "completeness", None)

    @property
    def reason_code(self) -> str | None:
        """Return the indeterminate reason code, or None for other statuses."""
        return getattr(self.view, "reason_code", None)

    @property
    def failure(
        self,
    ) -> Failure | RuntimeExtractionFailure | RuntimeValidationFailure | None:
        """Return the typed phase failure, or None when this status has no failure."""
        return getattr(self.view, "failure", None)

    @property
    def records(self) -> tuple[RuntimeValidatedRecord, ...]:
        """Return accepted records for evaluated results, otherwise an empty tuple."""
        return self.view.records if isinstance(self.view, _RuntimeEvaluated) else ()

    @property
    def issues(self) -> tuple[RuntimeRecordIssue, ...]:
        """Return evaluated candidate issues, or an empty tuple otherwise."""
        return self.view.issues if isinstance(self.view, _RuntimeEvaluated) else ()

    @property
    def extraction_diagnostics(self) -> tuple[ExtractionDiagnostic, ...]:
        """Return evaluated extraction diagnostics, otherwise an empty tuple."""
        return (
            self.view.extraction_diagnostics
            if isinstance(self.view, _RuntimeEvaluated)
            else ()
        )

    def require_all(self) -> list[RuntimeValidatedRecord]:
        """Return records only when every candidate and extraction check passed.

        Complete no-match returns an empty list. This method preserves the outcome
        and never silently returns only the successful subset.

        Returns:
            All accepted records as typed values with candidate evidence.

        Raises:
            ContractIssues: Evidence is indeterminate, a phase failed or was rejected,
                or evaluated results contain field issues or extraction diagnostics.
        """
        result = json.loads(self._handle.require_all())
        if "error" in result:
            raise ContractIssues(result["error"])
        records = result.get("records", [])
        for record in records:
            _complete_candidate_fields(record["candidate"], self.contract_schema)
        return [
            RuntimeValidatedRecord.model_validate(item, context=RUST_DOMAIN_VALIDATED)
            for item in records
        ]

    def to_archived(
        self, schema: ContractSchema | None = None
    ) -> ArchivedContractOutcome:
        """Convert this result to Rust's code-independent portable archive.

        Args:
            schema: Archive schema; None uses this outcome's original Contract schema.

        Returns:
            Typed archive with portable values and retained evidence.

        Raises:
            ContractError: Rust rejects the schema or cannot archive the result.
        """
        return _archived_outcome(
            self._handle, self.contract_schema if schema is None else schema
        )

    def to_json(self) -> str:
        """Return the original Rust wire JSON without serializing the enriched view."""
        return self._handle.to_json()

    def model_dump(self) -> dict[str, Any]:
        """Decode the original wire into a new dictionary."""
        return json.loads(self.to_json())

    def model_dump_json(self) -> str:
        """Return the original Rust wire JSON without serializing the enriched view."""
        return self.to_json()


class RuntimeContract(NativeAuthoringModel):
    """Author a Contract schema for extraction and validation in Rust.

    The schema defines grouping, fields, cardinalities, and value types. Unsupported
    conversions remain explicit validation issues rather than inferred Python
    conversions.

    Attributes:
        contract_schema: Public schema validated when the native Contract is
            constructed.
    """

    contract_schema: ContractSchema
    _handle: _native.Contract = PrivateAttr()

    def model_post_init(self, context: object) -> None:
        """Construct the native Contract from the validated Pydantic schema.

        Args:
            context: Pydantic initialization context; unused by this bridge.

        Raises:
            ContractError: Rust rejects the authored schema.
        """
        self._handle = _native.Contract(self.contract_schema.model_dump_json())

    @classmethod
    def new(cls, schema: ContractSchema) -> RuntimeContract:
        """Construct a runtime Contract using the supplied public schema.

        Args:
            schema: Contract identity, grouping, fields, and validation declarations.

        Returns:
            Contract whose native handle has accepted the schema.

        Raises:
            ContractError: Rust rejects the authored schema.
        """
        return cls(contract_schema=schema)

    def identity(self) -> ContractIdentity:
        """Return the Rust-generated identity of this authored Contract schema."""
        return ContractIdentity(self._handle.identity())

    def extract(
        self,
        located: LocateOutcome,
        *,
        limits: ExtractionLimits | None = None,
    ) -> RuntimeExtracted:
        """Group located findings into unvalidated runtime candidates.

        Args:
            located: Locator result carrying findings, provenance, and completeness.
            limits: Optional extraction budgets; None uses Rust defaults.

        Returns:
            Candidates, no-match, indeterminate evidence, locator failure, or a typed
            extraction rejection. Call validate() to obtain accepted field values.
        """
        handle = self._handle.extract(
            located.model_dump_json(exclude_none=True),
            None if limits is None else limits.model_dump_json(),
        )
        return RuntimeExtracted(self.contract_schema, handle)

    def locate(
        self,
        document: Document | BoundDocument | ParsedDocument,
        plan: Plan,
    ) -> RuntimeExtracted:
        """Locate document evidence and extract candidates using this Contract.

        Args:
            document: Offline, parsed, or bound document providing locator evaluation.
            plan: Discovery plan used to locate findings before extraction.

        Returns:
            Unvalidated extraction result retaining locator completeness or failure.
            Validation is a separate operation on the returned result.
        """
        return self.extract(document.locate(plan))
