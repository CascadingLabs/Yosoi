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
    """One runtime candidate with every schema field, including empty evidence."""

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
    type: Literal["string"]
    value: str


class RuntimeMoneyUsd(ImmutableModel):
    type: Literal["money_usd"]
    value: Money


type RuntimeValue = Annotated[
    RuntimeString | RuntimeMoneyUsd, Field(discriminator="type")
]


class RuntimeExactlyOne(ImmutableModel):
    cardinality: Literal["exactly_one"]
    value: RuntimeValue


class RuntimeZeroOrOne(ImmutableModel):
    cardinality: Literal["zero_or_one"]
    value: RuntimeValue | None


class RuntimeMany(ImmutableModel):
    cardinality: Literal["many"]
    values: tuple[RuntimeValue, ...]


type RuntimeFieldValue = Annotated[
    RuntimeExactlyOne | RuntimeZeroOrOne | RuntimeMany,
    Field(discriminator="cardinality"),
]


class RuntimeValidatedRecord(ImmutableModel):
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
    candidate: RuntimeCandidate
    fields: tuple[FieldIssue, ...]


class ArchivedContractCandidateField(ImmutableModel):
    id: FieldId
    evidence: tuple[Finding, ...] = Field(repr=False)


class ArchivedContractString(ImmutableModel):
    type: Literal["string"]
    value: str = Field(repr=False)


class ArchivedContractMoneyUsd(ImmutableModel):
    type: Literal["money_usd"]
    minor_units: Annotated[
        int, Field(strict=True, ge=-(2**63), le=2**63 - 1, repr=False)
    ]


type ArchivedContractValue = Annotated[
    ArchivedContractString | ArchivedContractMoneyUsd, Field(discriminator="type")
]


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


class ArchivedContractField(ImmutableModel):
    id: FieldId
    value: ArchivedContractFieldValue = Field(repr=False)


class ArchivedValidatedContractRecord(ImmutableModel):
    document_id: str
    region: RegionLineage | None = None
    fields: tuple[ArchivedContractField, ...] = Field(repr=False)
    evidence: tuple[ArchivedContractCandidateField, ...] = Field(repr=False)


class ArchivedContractRecordIssue(ImmutableModel):
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
_archived_outcome_adapter: TypeAdapter[ArchivedContractOutcomeData] = TypeAdapter(
    ArchivedContractOutcomeData
)


class ArchivedContractOutcome:
    """Immutable typed view of Rust's portable Contract archive outcome."""

    __slots__ = ("view", "_json", "_sealed")

    def __init__(self, value: str) -> None:
        wire = json.loads(value)
        self.view: ArchivedContractOutcomeData = (
            _archived_outcome_adapter.validate_python(
                wire, context=RUST_DOMAIN_VALIDATED
            )
        )
        self._json = value
        self._sealed = True

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("ArchivedContractOutcome is read-only")
        object.__setattr__(self, name, value)

    @property
    def status(self) -> str:
        return self.view.status

    @property
    def document_id(self) -> str | None:
        return getattr(self.view, "document_id", None)

    @property
    def completeness(self) -> IncompleteEvidence | None:
        return getattr(self.view, "completeness", None)

    @property
    def reason_code(self) -> str | None:
        return getattr(self.view, "reason_code", None)

    @property
    def failure(
        self,
    ) -> Failure | ArchivedExtractionFailure | ArchivedValidationFailure | None:
        return getattr(self.view, "failure", None)

    @property
    def records(self) -> tuple[ArchivedValidatedContractRecord, ...]:
        return self.view.records if isinstance(self.view, _ArchivedEvaluated) else ()

    @property
    def issues(self) -> tuple[ArchivedContractRecordIssue, ...]:
        return self.view.issues if isinstance(self.view, _ArchivedEvaluated) else ()

    @property
    def extraction_diagnostics(self) -> tuple[ExtractionDiagnostic, ...]:
        return (
            self.view.extraction_diagnostics
            if isinstance(self.view, _ArchivedEvaluated)
            else ()
        )

    def to_json(self) -> str:
        return self._json

    def model_dump(self) -> dict[str, Any]:
        return json.loads(self._json)

    def model_dump_json(self) -> str:
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
    """Typed runtime extraction view retaining the original Rust wire."""

    __slots__ = ("contract_schema", "_handle", "view", "_sealed")

    def __init__(
        self,
        contract_schema: ContractSchema,
        handle: _native.Extracted,
    ) -> None:
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
        if getattr(self, "_sealed", False):
            raise AttributeError("RuntimeExtracted is read-only")
        object.__setattr__(self, name, value)

    @property
    def status(self) -> str:
        return self.view.status

    @property
    def candidates(self) -> tuple[RuntimeCandidate, ...]:
        return self.view.candidates if isinstance(self.view, _RuntimeCandidates) else ()

    @property
    def diagnostics(self) -> tuple[ExtractionDiagnostic, ...]:
        return (
            self.view.diagnostics if isinstance(self.view, _RuntimeCandidates) else ()
        )

    @property
    def document_id(self) -> str | None:
        return getattr(self.view, "document_id", None)

    @property
    def completeness(self) -> IncompleteEvidence | None:
        return getattr(self.view, "completeness", None)

    @property
    def reason_code(self) -> str | None:
        return getattr(self.view, "reason_code", None)

    @property
    def failure(self) -> Failure | RuntimeExtractionFailure | None:
        return getattr(self.view, "failure", None)

    def validate(
        self, *, limits: ValidationLimits | None = None
    ) -> RuntimeContractOutcome:
        handle = self._handle.validate(
            None if limits is None else limits.model_dump_json()
        )
        return RuntimeContractOutcome(self.contract_schema, handle)

    def to_json(self) -> str:
        return self._handle.to_json()

    def model_dump(self) -> dict[str, Any]:
        return json.loads(self.to_json())

    def model_dump_json(self) -> str:
        return self.to_json()


class RuntimeContractOutcome:
    """Typed runtime validation view retaining the original Rust wire."""

    __slots__ = ("contract_schema", "_handle", "view", "_sealed")

    def __init__(
        self,
        contract_schema: ContractSchema,
        handle: _native.ContractOutcome,
    ) -> None:
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
        if getattr(self, "_sealed", False):
            raise AttributeError("RuntimeContractOutcome is read-only")
        object.__setattr__(self, name, value)

    @property
    def status(self) -> str:
        return self.view.status

    @property
    def document_id(self) -> str | None:
        return getattr(self.view, "document_id", None)

    @property
    def completeness(self) -> IncompleteEvidence | None:
        return getattr(self.view, "completeness", None)

    @property
    def reason_code(self) -> str | None:
        return getattr(self.view, "reason_code", None)

    @property
    def failure(
        self,
    ) -> Failure | RuntimeExtractionFailure | RuntimeValidationFailure | None:
        return getattr(self.view, "failure", None)

    @property
    def records(self) -> tuple[RuntimeValidatedRecord, ...]:
        return self.view.records if isinstance(self.view, _RuntimeEvaluated) else ()

    @property
    def issues(self) -> tuple[RuntimeRecordIssue, ...]:
        return self.view.issues if isinstance(self.view, _RuntimeEvaluated) else ()

    @property
    def extraction_diagnostics(self) -> tuple[ExtractionDiagnostic, ...]:
        return (
            self.view.extraction_diagnostics
            if isinstance(self.view, _RuntimeEvaluated)
            else ()
        )

    def require_all(self) -> list[RuntimeValidatedRecord]:
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
        """Return Rust's code-independent portable archive representation."""
        return _archived_outcome(
            self._handle, self.contract_schema if schema is None else schema
        )

    def to_json(self) -> str:
        return self._handle.to_json()

    def model_dump(self) -> dict[str, Any]:
        return json.loads(self.to_json())

    def model_dump_json(self) -> str:
        return self.to_json()


class RuntimeContract(NativeAuthoringModel):
    """Runtime-authored Contract using Rust's public schema pipeline."""

    contract_schema: ContractSchema
    _handle: _native.Contract = PrivateAttr()

    def model_post_init(self, context: object) -> None:
        self._handle = _native.Contract(self.contract_schema.model_dump_json())

    @classmethod
    def new(cls, schema: ContractSchema) -> RuntimeContract:
        return cls(contract_schema=schema)

    def identity(self) -> ContractIdentity:
        return ContractIdentity(self._handle.identity())

    def extract(
        self,
        located: LocateOutcome,
        *,
        limits: ExtractionLimits | None = None,
    ) -> RuntimeExtracted:
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
        return self.extract(document.locate(plan))
