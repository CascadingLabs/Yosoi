"""Mutable Pydantic Contracts over Rust's bounded raw evidence extraction."""

from __future__ import annotations

import json
import re
import types
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from threading import RLock
from typing import (
    Annotated,
    Any,
    ClassVar,
    Literal,
    Protocol,
    Self,
    TypeVar,
    Union,
    get_args,
    get_origin,
)

from pydantic import (
    ConfigDict,
    SerializeAsAny,
    TypeAdapter,
    ValidationError,
    create_model,
    model_validator,
)
from pydantic import Field as PydanticField
from pydantic_core import InitErrorDetails, PydanticCustomError, PydanticUndefined

from . import _native
from ._models import ImmutableModel, Model, NativeAuthoringModel
from .documents import BoundDocument, Document, ParsedDocument
from .identities import ContractIdentity
from .locators import Locator, Plan, Query, output
from .outcomes import (
    Complete,
    Completeness,
    Finding,
    LocateOutcome,
    Partial,
    ProjectedValue,
    RegionLineage,
)
from .scalars import RUST_DOMAIN_VALIDATED, ContractId, FieldId

T = TypeVar("T", bound="Contract")
Cardinality = Literal["exactly_one", "zero_or_one", "many"]
"""Required accepted field count: exactly one, zero or one, or an ordered collection
including empty. Python applies these distinctions to complete raw evidence.
"""


class ContractValue(Protocol):
    """Identity-only protocol for native Rust Contract scalar types.

    Attributes:
        TYPE_ID: Stable scalar identifier included in native transport identity. This
            protocol does not register a Pydantic validator or runtime converter.
    """

    TYPE_ID: ClassVar[str]


class Money(NativeAuthoringModel):
    """USD monetary scalar represented by integer minor units.

    Attributes:
        TYPE_ID: Rust scalar identifier money.usd.
        minor_units: Nonnegative cents within Rust's signed 64-bit representation.
            Python construction rejects negative values; text conversion can report a
            semantic negative-money issue before a record is accepted.
        currency: Discriminator fixed to usd; no exchange-rate conversion occurs.
    """

    TYPE_ID: ClassVar[str] = _native.contract_value_type_id(True)

    minor_units: Annotated[
        int, PydanticField(strict=True, ge=0, le=2**63 - 1, repr=False)
    ]
    currency: Literal["usd"] = "usd"

    @model_validator(mode="before")
    @classmethod
    def _parse_text(cls, value: Any) -> Any:
        """Accept the Rust Contract USD text spelling during normal Pydantic use."""
        if not isinstance(value, str):
            return value
        match = re.fullmatch(r"\$([0-9]+)\.([0-9]{2})", value)
        if match is None:
            raise ValueError("invalid USD amount")
        minor_units = int(match.group(1)) * 100 + int(match.group(2))
        if minor_units > 2**63 - 1:
            raise ValueError("USD amount exceeds the supported range")
        return {"minor_units": minor_units, "currency": "usd"}

    @model_validator(mode="after")
    def _rust_validate(self) -> Self:
        _native.validate_money(self.model_dump_json())
        return self

    def __str__(self) -> str:
        """Return the Rust USD amount representation without currency conversion."""
        return _native.validate_money(self.model_dump_json())


def value_type_id(
    annotation: type[str] | type[Money] | type[ContractValue],
) -> str:
    """Return the Rust ContractValue identity declared by a scalar type."""
    if annotation is str:
        return _native.contract_value_type_id(False)
    if annotation is Money:
        return Money.TYPE_ID
    if not isinstance(annotation, type):
        raise TypeError("ContractValue must be a scalar type")
    type_id = getattr(annotation, "TYPE_ID", None)
    if isinstance(type_id, str):
        return type_id
    raise TypeError("ContractValue types require a string TYPE_ID")


@dataclass(frozen=True)
class _LocatorMetadata:
    locator: Locator | None
    field_id: FieldId | None


def Field(
    description: str | None = None,
    *,
    id: str | FieldId | None = None,
    locator: Locator | Query | None = None,
    default: Any = PydanticUndefined,
    **kwargs: Any,
) -> Any:
    """Describe a Contract field using a genuine Pydantic FieldInfo.

    A bare query uses text projection. Pydantic constraints, aliases, defaults, and
    other FieldInfo options are forwarded. Only the locator and field ID participate in
    native candidate extraction; Pydantic validates each raw projected value.
    """
    if isinstance(locator, Query):
        locator = locator.text()
    if locator is not None and not isinstance(locator, Locator):
        raise TypeError("locator must be a Yosoi query or projected locator")
    if id is not None and not isinstance(id, str):
        raise TypeError("id must be a string")
    field_id = None if id is None else FieldId(id)
    info = PydanticField(default=default, description=description, **kwargs)
    info.metadata.append(_LocatorMetadata(locator, field_id))
    return info


class FieldSchema(ImmutableModel):
    """Native transport field meaning, cardinality, and scalar type metadata.

    Attributes:
        id: Authored identifier matching locator output evidence.
        description: Nonblank business meaning; it does not discover a locator.
        cardinality: exactly_one, zero_or_one, or many describes candidate field shape.
        value_type: Native transport type, string or money.usd. Python Contracts map
            other annotations to string and validate raw findings in Pydantic.
    """

    id: FieldId
    description: str
    cardinality: Cardinality
    value_type: str

    @model_validator(mode="after")
    def _rust_validate(self) -> Self:
        _native.field_schema_validate(self.model_dump_json())
        return self


class ContractSchema(ImmutableModel):
    """Native transport meaning, scope, and ordered field declarations.

    Attributes:
        version: Supported portable format version, currently 1.
        id: Authored record identity, distinct from a document or execution ID.
        description: Nonblank record meaning, excluded from semantic hashing.
        scope: page groups compatible findings into one record; repeated groups by
            parent-region lineage.
        fields: Nonempty ordered fields with unique IDs. Order, IDs, cardinalities, and
            native type IDs contribute to transport identity; Python annotations and
            validators are not represented.
    """

    version: Literal[1] = 1
    id: ContractId
    description: str
    scope: Literal["page", "repeated"]
    fields: tuple[FieldSchema, ...]

    @model_validator(mode="after")
    def _rust_validate(self) -> Self:
        _native.contract_schema_identity(self.model_dump_json())
        return self

    def identity(self) -> ContractIdentity:
        """Return the Rust-computed semantic schema identity.

        Includes version, Contract ID, scope, and ordered field IDs, cardinalities,
        and type IDs. Record and field descriptions are excluded from hashing.

        Raises:
            ContractError: Schema validation or portable hash accounting fails.
        """
        return ContractIdentity(
            _native.contract_schema_identity(self.model_dump_json())
        )


Limit = Annotated[int, PydanticField(ge=0, le=2**64 - 1, strict=True)]
"""Strict nonnegative u64 extraction or validation counter. Zero is a finite budget,
not an implicit unlimited setting.
"""


class ExtractionLimits(ImmutableModel):
    """Nonnegative u64 budgets for candidate assembly.

    Attributes:
        max_scanned_regions: Maximum repeated-region lineage entries examined.
        max_scanned_findings: Maximum locator findings examined for field matching.
        max_matching_findings: Maximum findings matching authored Contract fields.
        max_candidates: Maximum candidate records assembled.
        max_values_per_field: Maximum findings retained per field within a candidate.
        max_retained_evidence: Maximum finding evidence references retained across
            candidates.
        max_diagnostics: Maximum nonfatal grouping diagnostics retained.
    """

    max_scanned_regions: Limit
    max_scanned_findings: Limit
    max_matching_findings: Limit
    max_candidates: Limit
    max_values_per_field: Limit
    max_retained_evidence: Limit
    max_diagnostics: Limit

    @classmethod
    def uniform(cls, maximum: int) -> Self:
        """Assign the same unsigned limit to every extraction resource.

        Args:
            maximum: Strict nonnegative integer fitting u64.

        Returns:
            Independent resource fields with the supplied maximum.

        Raises:
            pydantic.ValidationError: The maximum is not a strict u64 value.
        """
        return cls.model_validate({name: maximum for name in cls.model_fields})


class ValidationLimits(ImmutableModel):
    """Native-shaped work budgets applied before Python validation.

    Attributes:
        max_fields: Maximum schema fields in one validation pass.
        max_records: Maximum candidate records requiring validation.
        max_conversions: Maximum field inputs, default slots and alias-container
            expansion passed to Pydantic.
        max_issues: Maximum field-level candidate issues retained.
        max_retained_provenance: Maximum candidate and issue evidence references.
    """

    max_fields: Limit = PydanticField(
        default_factory=lambda: _validation_default("max_fields")
    )
    max_records: Limit = PydanticField(
        default_factory=lambda: _validation_default("max_records")
    )
    max_conversions: Limit = PydanticField(
        default_factory=lambda: _validation_default("max_conversions")
    )
    max_issues: Limit = PydanticField(
        default_factory=lambda: _validation_default("max_issues")
    )
    max_retained_provenance: Limit = PydanticField(
        default_factory=lambda: _validation_default("max_retained_provenance")
    )


def _validation_default(name: str) -> int:
    return json.loads(_native.validation_limits_defaults())[name]


class ExtractionPolicy(ImmutableModel):
    """Immutable acceptance and native-work limits for Python Contract extraction.

    Attributes:
        on_rejected_record: Raise when any candidate fails by default, or collect only
            the accepted models while retaining rejected evidence in an extraction
            report.
        minimum_records: Minimum number of accepted records required by convenience
            extraction. Reports retain results even when this threshold is unmet.
        extraction_limits: Optional Rust limits for raw candidate assembly.
        validation_limits: Optional native-shaped work limits applied before Python
            validators run.
    """

    on_rejected_record: Literal["raise", "collect"] = "raise"
    minimum_records: Annotated[int, PydanticField(strict=True, ge=0)] = 0
    extraction_limits: ExtractionLimits | None = None
    validation_limits: ValidationLimits | None = None


class TerminalFailure(ImmutableModel):
    """Structured phase rejection facts, distinct from field issues.

    Attributes:
        kind: Classification selecting the applicable rejection details.
        code: Structural plan or parser identifier when present.
        document: Affected class for an unsupported document combination.
        limit: Extraction or validation resource boundary when present.
        maximum: Configured maximum in units of the named resource.
        observed: Recorded or attempted consumption in the same units.
        message: Failure explanation supplied by the native binding, when present.
    """

    kind: str
    code: str | None = None
    document: str | None = None
    limit: str | None = None
    maximum: int | None = None
    observed: int | None = None
    message: str | None = None


class CandidateField(ImmutableModel):
    """Ordered projection values and original findings before conversion.

    Attributes:
        field_id: Authored identity of this candidate field.
        evidence: Retained findings, coordinates, and completeness. Empty evidence alone
            does not establish complete absence.
    """

    field_id: FieldId
    evidence: tuple[Finding, ...] = PydanticField(default=(), repr=False)

    @property
    def values(self) -> tuple[ProjectedValue, ...]:
        """Return projection wrappers in evidence order without typed conversion."""
        return tuple(item.projected for item in self.evidence)

    @property
    def is_absent(self) -> bool:
        """Return whether no findings are retained, without an absence claim."""
        return not self.evidence

    @property
    def is_empty(self) -> bool:
        """Return whether evidence is empty, independently of completeness."""
        return not self.evidence

    def __len__(self) -> int:
        """Return finding count, not accepted or converted value count."""
        return len(self.evidence)


class Candidate(ImmutableModel):
    """Grouping metadata for generated typed candidate records.

    Attributes:
        document_id: Document supplying candidate findings.
        region: Repeated-region lineage, or None for page grouping. Generated subclasses
            add named CandidateField members.
    """

    document_id: str
    region: RegionLineage | None = None

    @property
    def fields(self) -> dict[str, CandidateField]:
        """Return field evidence keyed by authored native field ID.

        The mapping is a fresh dictionary; its frozen CandidateField values retain
        ordered findings without copying projected source content.
        """
        return {
            str(value.field_id): value
            for value in self.__dict__.values()
            if isinstance(value, CandidateField)
        }

    def field(self, field_id: str | FieldId) -> CandidateField:
        """Return one candidate field by its authored native field ID."""
        try:
            return self.fields[str(field_id)]
        except KeyError as error:
            raise KeyError(f"candidate has no field {field_id!s}") from error


class FieldIssueKind(ImmutableModel):
    """Cardinality, completeness, conversion, or semantic field rejection.

    Attributes:
        kind: Selects missing_required, excess_candidates, incomplete_evidence,
            unsupported_projected_value, conversion_failed, or
            semantic_validation_failed.
        observed: Finding count for excess_candidates, when applicable.
        code: negative_money when converted money violates supported nonnegative
            semantics.
    """

    kind: Literal[
        "missing_required",
        "excess_candidates",
        "incomplete_evidence",
        "unsupported_projected_value",
        "conversion_failed",
        "semantic_validation_failed",
    ]
    observed: int | None = None
    code: Literal["negative_money"] | None = None


class FieldIssue(ImmutableModel):
    """Rejected Contract field with supporting source-derived evidence.

    Attributes:
        field: Authored identifier of the rejected field.
        kind: Typed field rejection explanation, separate from operation budgets.
        evidence: Findings supporting the issue; they can contain user or source
            content.
    """

    field: FieldId
    kind: FieldIssueKind
    evidence: tuple[Finding, ...] = PydanticField(repr=False)


class ExtractionDiagnostic(ImmutableModel):
    """Nonfatal finding-lineage mismatch during candidate grouping.

    Attributes:
        kind: Discriminator fixed to incompatible_lineage.
        output: Locator output whose evidence could not join a compatible group.
    """

    kind: Literal["incompatible_lineage"]
    output: str


class ValidatedRecord[T: "Contract"](ImmutableModel):
    """Pydantic-accepted typed value with original candidate evidence retained.

    Attributes:
        value: Record accepted by the Contract's Pydantic model validators.
        candidate: Original grouped findings and provenance.
    """

    value: SerializeAsAny[T] = PydanticField(repr=False)
    candidate: SerializeAsAny[Candidate] = PydanticField(repr=False)


class RecordIssue(ImmutableModel):
    """Rejected candidate record with retained field issues.

    Attributes:
        candidate: Original grouped evidence for the rejected record.
        fields: Field rejection reasons and supporting findings.
    """

    candidate: SerializeAsAny[Candidate]
    fields: tuple[FieldIssue, ...]


class ContractIssues(_native.ContractError):
    """Structured rejection of a request for all accepted record values.

    Attributes:
        detail: Copied terminal, cardinality, or report-level rejection facts. Nested
            values are not recursively frozen; the extraction report remains available.
    """

    def __init__(self, detail: Mapping[str, Any]) -> None:
        """Copy top-level Rust rejection details and encode an exception message.

        Args:
            detail: Safe rejection counts, validation details, or terminal facts.

        Nested values are not frozen; the original outcome retains its evidence.
        """
        self.detail = dict(detail)
        super().__init__(json.dumps(self.detail))


class Contract(Model):
    """Mutable Pydantic record model with native candidate extraction.

    Attributes:
        root: Optional repeated-region query; None selects page grouping.
        contract_id: Optional schema ID; the class name is used when omitted.
        contract_description: Optional meaning; class docstring or name supplies the
            default. Field descriptions are optional and do not affect Python
            validation.
    """

    model_config = ConfigDict(hide_input_in_errors=True)

    root: ClassVar[Query | None] = None
    contract_id: ClassVar[str | None] = None
    contract_description: ClassVar[str | None] = None
    _definition_lock: ClassVar[Any] = RLock()

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        """Initialize independent synchronization for each Contract subclass."""
        super().__pydantic_init_subclass__(**kwargs)
        cls._definition_lock = RLock()

    @classmethod
    def _definition(cls) -> _Definition:
        # No global registry: the immutable Rust schema belongs to this class.
        with cls._definition_lock:
            cached = cls.__dict__.get("_contract_definition")
            if isinstance(cached, _Definition):
                return cached
            definition = _Definition(cls)
            cls._contract_definition = definition
            return definition

    @classmethod
    def contract_schema(cls) -> ContractSchema:
        """Return the native transport schema without document I/O.

        Raises:
            ContractError: The class's field identifiers or descriptions cannot be
                represented by the native transport schema.

        Python annotations, aliases, defaults, Pydantic configuration, validators,
        serializers, and computed fields are not represented here.
        """
        return cls._definition().schema

    @classmethod
    def identity(cls) -> ContractIdentity:
        """Return the Rust identity for this class's native transport shape.

        This identity covers version, Contract ID, scope, ordered field IDs,
        cardinalities, and native scalar transport types. It does not identify Python
        annotations, aliases, defaults, model configuration, or Python validators.

        Raises:
            ContractError: The class cannot form a supported portable schema.
        """
        return ContractIdentity(cls._definition().handle.identity())

    @classmethod
    def plan(cls) -> Plan:
        """Return the explicit locator plan pinned by all fields.

        Natural-language descriptions do not discover selectors automatically.

        Raises:
            ContractError: Fields lack pinned locators or the declaration is invalid.
        """
        definition = cls._definition()
        if definition.plan is None:
            raise _native.ContractError("contract fields have no pinned locators")
        return definition.plan

    @classmethod
    def assemble(
        cls: type[T], located: LocateOutcome, *, limits: ExtractionLimits | None = None
    ) -> Extracted[T]:
        """Assemble raw native findings for explicit Pydantic validation.

        Args:
            located: Locator outcome retaining completeness and failure distinctions.
            limits: Native candidate assembly budgets, or None for Rust defaults.

        Returns:
            Raw candidates, diagnostics, or a terminal state. Call ``validate`` to
            produce a report of Pydantic-accepted models and rejected candidates.

        Raises:
            ContractError: Declaration or native input setup cannot be represented.
        """
        handle = cls._definition().handle.extract(
            located.model_dump_json(exclude_none=True),
            None if limits is None else limits.model_dump_json(),
        )
        return Extracted(cls, handle)

    @classmethod
    def extract_report(
        cls: type[T],
        document: Document | BoundDocument | ParsedDocument,
        *,
        policy: ExtractionPolicy | None = None,
    ) -> ContractOutcome[T]:
        """Return accepted Pydantic records and every rejected candidate.

        The report retains source evidence and terminal outcomes. Convenience
        extraction raises according to ``policy``; this method does not raise merely
        because a candidate failed Pydantic validation or minimum-record acceptance.
        """
        effective = _extraction_policy(policy)
        located = document.locate(cls.plan())
        return cls.assemble(located, limits=effective.extraction_limits).validate(
            limits=effective.validation_limits, policy=effective
        )

    @classmethod
    def extract(
        cls: type[T],
        document: Document | BoundDocument | ParsedDocument,
        *,
        policy: ExtractionPolicy | None = None,
    ) -> list[T]:
        """Locate, validate, and return accepted model instances.

        Use ``extract_report`` to inspect rejected candidates, status, and evidence.
        Incomplete or terminal native outcomes always raise. A single candidate's
        Pydantic error raises as ``ValidationError`` by default; combined rejections
        raise ``ContractIssues`` with sanitized details. With
        ``on_rejected_record='collect'``, only accepted models are returned.
        """
        effective = _extraction_policy(policy)
        report = cls.extract_report(document, policy=effective)
        return _accepted_records(report, effective)


class _Definition:
    def __init__(self, contract: type[Contract]) -> None:
        self.contract = contract
        contract.model_rebuild()
        fields: list[FieldSchema] = []
        pins: list[tuple[str, str, Locator | None]] = []
        self.field_map: list[tuple[str, str]] = []
        for name, info in contract.model_fields.items():
            value_type, cardinality = _field_type(info.annotation)
            description = info.description or name
            metadata = [
                item for item in info.metadata if isinstance(item, _LocatorMetadata)
            ]
            if len(metadata) != 1:
                raise _native.ContractError(f"field {name!r} must use ys.Field")
            field_id = metadata[0].field_id or name
            fields.append(
                FieldSchema(
                    id=field_id,
                    description=description,
                    cardinality=cardinality,
                    value_type=value_type,
                )
            )
            pins.append((name, field_id, metadata[0].locator))
            self.field_map.append((name, field_id))
        id = contract.contract_id or contract.__name__
        description = (
            contract.contract_description or contract.__doc__ or contract.__name__
        )
        self.schema = ContractSchema(
            id=id,
            description=description.strip(),
            scope="repeated" if contract.root is not None else "page",
            fields=tuple(fields),
        )
        self.handle = _native.Contract(self.schema.model_dump_json())
        present = sum(locator is not None for _, _, locator in pins)
        if present and present != len(pins):
            raise _native.ContractError("pin all fields or leave all fields unpinned")
        self.plan: Plan | None = None
        if present:
            region = (
                contract.root.each_as_region(id) if contract.root is not None else None
            )
            outputs = []
            for _, field_id, locator in pins:
                if locator is None:
                    continue
                query = locator.query
                if query.within is not None:
                    raise _native.ContractError(
                        "field locator scope is supplied by Contract.root"
                    )
                if region is not None:
                    locator = locator.model_copy(update={"query": region.find(query)})
                outputs.append(output(field_id, locator))
            self.plan = Plan(outputs=tuple(outputs))
        candidate_fields: dict[str, Any] = {
            name: (CandidateField, ...) for name in contract.model_fields
        }
        # Candidate metadata cannot shadow named model fields.
        reserved = set(Candidate.model_fields) | {"fields", "field"}
        if reserved.intersection(contract.model_fields):
            raise _native.ContractError(
                "Contract fields cannot shadow candidate document_id or region"
            )
        self.candidate_type = create_model(
            f"{contract.__name__}Candidate",
            __base__=Candidate,
            __module__=contract.__module__,
            **candidate_fields,
        )

    def candidate(self, data: Mapping[str, Any]) -> Candidate:
        values = {
            python_name: CandidateField(
                field_id=field_id,
                evidence=tuple(
                    Finding.model_validate(item, context=RUST_DOMAIN_VALIDATED)
                    for item in data["fields"].get(field_id, [])
                ),
            )
            for python_name, field_id in self.field_map
        }
        return self.candidate_type.model_validate(
            {"document_id": data["document_id"], "region": data.get("region"), **values}
        )


def _field_type(annotation: Any) -> tuple[Literal["string", "money.usd"], Cardinality]:
    """Return only the coarse native transport type and extraction cardinality."""
    while get_origin(annotation) is Annotated:
        annotation = get_args(annotation)[0]

    cardinality: Cardinality = "exactly_one"
    origin = get_origin(annotation)
    if origin in (Union, types.UnionType):
        alternatives = get_args(annotation)
        non_none = tuple(item for item in alternatives if item is not type(None))
        if len(non_none) == 1:
            annotation = non_none[0]
            origin = get_origin(annotation)
            cardinality = "zero_or_one"
        elif type(None) in alternatives:
            cardinality = "zero_or_one"
    if annotation is list or origin is list:
        cardinality = "many"
        arguments = get_args(annotation)
        if arguments:
            annotation = arguments[0]
        else:
            annotation = Any
        while get_origin(annotation) is Annotated:
            annotation = get_args(annotation)[0]
    value_type: Literal["string", "money.usd"] = (
        "money.usd" if annotation is Money else "string"
    )
    return value_type, cardinality


class _ReadOnlyView:
    __slots__ = ("_sealed",)

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError(f"{type(self).__name__} is read-only")
        object.__setattr__(self, name, value)

    def _seal(self) -> None:
        object.__setattr__(self, "_sealed", True)


class Extracted[T: "Contract"](_ReadOnlyView):
    """Read-only candidate assembly outcome awaiting explicit validation.

    Attributes:
        contract: Typed record definition used for extraction.
        status: candidates, no_match, indeterminate, locate_failed, or rejected retains
            the phase distinction.
        document_id: Examined document identity when available.
        failure: Typed terminal location or extraction rejection when present.
        completeness: Partial or unknown coverage for indeterminate outcomes.
        reason_code: Structural explanation of indeterminate coverage.
        candidates: Grouped raw evidence, not accepted typed records.
        diagnostics: Nonfatal extraction issues such as incompatible lineage.
    """

    __slots__ = (
        "contract",
        "_handle",
        "status",
        "document_id",
        "failure",
        "completeness",
        "reason_code",
        "candidates",
        "diagnostics",
    )

    def __init__(self, contract: type[T], handle: _native.Extracted) -> None:
        """Retain a native extraction handle and read-only evidence.

        Args:
            contract: Typed definition used to interpret field identities.
            handle: Native extraction outcome from the Rust pipeline.

        Construction does not validate candidate values or acquire documents.
        """
        self.contract = contract
        self._handle = handle
        wire = json.loads(handle.to_json())
        self.status: str = wire["status"]
        self.document_id: str | None = wire.get("document_id")
        failure_data = (
            TypeAdapter(_runtime_contracts.RuntimeExtractedData).validate_python(
                wire, context=RUST_DOMAIN_VALIDATED
            )
            if "failure" in wire
            else None
        )
        self.failure = (
            failure_data.failure
            if isinstance(
                failure_data,
                (
                    _runtime_contracts._RuntimeLocateFailed,
                    _runtime_contracts._RuntimeRejected,
                ),
            )
            else None
        )
        self.completeness: Completeness | None = (
            TypeAdapter(Completeness).validate_python(wire["completeness"])
            if "completeness" in wire
            else None
        )
        self.reason_code: str | None = wire.get("reason_code")
        self.candidates = tuple(
            contract._definition().candidate(item)
            for item in wire.get("candidates", [])
        )
        self.diagnostics = tuple(
            ExtractionDiagnostic.model_validate(item)
            for item in wire.get("diagnostics", [])
        )
        self._seal()

    def validate(
        self,
        *,
        limits: ValidationLimits | None = None,
        policy: ExtractionPolicy | None = None,
    ) -> ContractOutcome[T]:
        """Run Pydantic validation after checking bounded native-work limits.

        Args:
            limits: Validation-work budgets, or None for Rust defaults.
            policy: Acceptance policy. An explicit ``limits`` value overrides its
                ``validation_limits`` member.

        Returns:
            Pydantic-accepted records, candidate issues, or terminal states. User
            validators are skipped when extraction evidence is incomplete or the
            validation-work budget is exceeded.
        """
        effective = _extraction_policy(policy)
        if limits is not None:
            effective = effective.model_copy(update={"validation_limits": limits})
        return ContractOutcome(self, effective)

    def model_dump(self) -> dict[str, Any]:
        """Return a new native wire-data dictionary without validating again."""
        return json.loads(self._handle.to_json())

    def model_dump_json(self) -> str:
        """Return native wire JSON with evidence and terminal states preserved."""
        return self._handle.to_json()


@dataclass(frozen=True, slots=True)
class ContractRecordIssue:
    """One rejected candidate with Pydantic details and source evidence.

    Attributes:
        candidate: Original candidate with all field findings.
        field_ids: Authored field IDs responsible for rejection.
        kind: missing_required, excess_candidates, incomplete_evidence, or
            validation_error.
        observed: Finding count for excess_candidates when available.
        evidence: Findings for the affected field IDs, without copying source text.
        error: Original Pydantic ValidationError, when model validation ran.
    """

    candidate: Candidate = dataclass_field(repr=False)
    field_ids: tuple[str, ...]
    kind: str
    evidence: tuple[Finding, ...] = dataclass_field(repr=False)
    error: ValidationError | None = dataclass_field(default=None, repr=False)
    observed: int | None = None
    field_kinds: tuple[tuple[str, str], ...] = ()

    @property
    def errors(self) -> tuple[dict[str, Any], ...]:
        """Return Pydantic error details without input values or documentation URLs."""
        if self.error is None:
            return ()
        return tuple(
            {
                key: value
                for key, value in detail.items()
                if key not in {"input", "url", "ctx"}
            }
            for detail in self.error.errors(include_input=False, include_url=False)
        )

    @property
    def fields(self) -> tuple[FieldIssue, ...]:
        """Return Rust-compatible field summaries with exact source evidence."""
        result: list[FieldIssue] = []
        for field_id, kind in self.field_kinds:
            mapped_kind = "conversion_failed" if kind == "validation_error" else kind
            details: dict[str, Any] = {"kind": mapped_kind}
            evidence = self.candidate.field(field_id).evidence
            if kind == "excess_candidates":
                details["observed"] = len(evidence)
            elif kind == "incomplete_evidence":
                evidence = tuple(
                    finding
                    for finding in evidence
                    if finding.completeness.status != "complete"
                )
            result.append(
                FieldIssue(
                    field=FieldId(field_id),
                    kind=FieldIssueKind.model_validate(details),
                    evidence=evidence,
                )
            )
        return tuple(result)


class ContractOutcome[T: "Contract"](_ReadOnlyView):
    """Pydantic validation report retaining accepted and rejected candidates.

    Attributes:
        contract: Typed record definition used for validation.
        status: evaluated, no_match, indeterminate, locate_failed,
            extraction_rejected, or validation_rejected.
        document_id: Evidence document identity when available.
        failure: Typed phase or operation-budget rejection when present.
        completeness: Partial or unknown coverage for indeterminate outcomes.
        reason_code: Structural explanation of indeterminate coverage.
        candidates: All complete-candidate evidence retained by native extraction.
        records: Accepted Pydantic values paired with original candidates.
        issues: Rejected candidates with Pydantic error details and findings.
        extraction_diagnostics: Nonfatal grouping issues retained alongside accepted
            values; strict all-record access treats them as rejection facts.
    """

    __slots__ = (
        "contract",
        "policy",
        "extraction_status",
        "status",
        "document_id",
        "failure",
        "completeness",
        "reason_code",
        "candidates",
        "records",
        "issues",
        "extraction_diagnostics",
    )

    def __init__(self, extracted: Extracted[T], policy: ExtractionPolicy) -> None:
        """Validate each complete candidate under the supplied resource limits.

        Args:
            extracted: Raw candidates from Rust's bounded extraction stage.
            policy: Minimum acceptance and validation-work limits.
        """
        self.contract = extracted.contract
        self.policy = policy
        self.extraction_status = extracted.status
        self.document_id = extracted.document_id
        self.failure = extracted.failure
        self.completeness = extracted.completeness
        self.reason_code = extracted.reason_code
        self.candidates = extracted.candidates
        self.records: tuple[ValidatedRecord[T], ...] = ()
        self.issues: tuple[ContractRecordIssue, ...] = ()
        self.extraction_diagnostics = extracted.diagnostics
        self.status = _report_status(extracted.status)

        if self.completeness is None and self.status in {"evaluated", "no_match"}:
            self.completeness = Complete(status="complete")

        if self.status not in {"evaluated", "no_match"}:
            self._seal()
            return

        limits = policy.validation_limits or ValidationLimits()
        limit_failure = _validation_limit_failure(
            self.candidates, self.contract, limits
        )
        if limit_failure is not None:
            self.status = "validation_rejected"
            self.failure = limit_failure
            self._seal()
            return

        accepted: list[ValidatedRecord[T]] = []
        issues: list[ContractRecordIssue] = []
        issue_count = 0
        retained_issue_evidence = 0
        total_evidence = sum(
            len(field.evidence)
            for candidate in self.candidates
            for field in candidate.fields.values()
        )
        definition = self.contract._definition()
        for candidate in self.candidates:
            incomplete = _candidate_incomplete_fields(definition, candidate)
            if incomplete:
                issue = _manual_issue(candidate, incomplete, "incomplete_evidence")
                issue_count += len(issue.field_ids)
                retained_issue_evidence += len(issue.evidence)
                issues.append(issue)
                self.completeness = _partial_completeness(
                    issue.evidence, self.completeness
                )
                self.status = "indeterminate"
                if issue_count > limits.max_issues:
                    self.status = "validation_rejected"
                    self.failure = _issue_limit_failure(limits, issue_count)
                    break
                provenance_failure = _issue_provenance_failure(
                    limits, total_evidence, retained_issue_evidence
                )
                if provenance_failure is not None:
                    self.status = "validation_rejected"
                    self.failure = provenance_failure
                    break
                continue

            excess = _candidate_excess_fields(definition, candidate)
            if excess:
                issue = _excess_issue(definition, candidate, excess)
                issue_count += len(issue.field_ids)
                retained_issue_evidence += len(issue.evidence)
                issues.append(issue)
                if issue_count > limits.max_issues:
                    self.status = "validation_rejected"
                    self.failure = _issue_limit_failure(limits, issue_count)
                    break
                provenance_failure = _issue_provenance_failure(
                    limits, total_evidence, retained_issue_evidence
                )
                if provenance_failure is not None:
                    self.status = "validation_rejected"
                    self.failure = provenance_failure
                    break
                continue

            inputs = _candidate_validation_inputs(definition, candidate)
            try:
                value = self.contract.model_validate(inputs)
            except ValidationError as error:
                issue = _validation_issue(self.contract, definition, candidate, error)
                issue_count += max(1, len(issue.field_ids))
                retained_issue_evidence += len(issue.evidence)
                issues.append(issue)
                if issue_count > limits.max_issues:
                    self.status = "validation_rejected"
                    self.failure = _issue_limit_failure(limits, issue_count)
                    break
                provenance_failure = _issue_provenance_failure(
                    limits, total_evidence, retained_issue_evidence
                )
                if provenance_failure is not None:
                    self.status = "validation_rejected"
                    self.failure = provenance_failure
                    break
            else:
                accepted.append(ValidatedRecord(value=value, candidate=candidate))

        # An operation budget failure withholds a partially processed prefix.
        # Raw candidates and rejection details remain available for diagnosis.
        self.records = () if self.status == "validation_rejected" else tuple(accepted)
        self.issues = () if self.status == "validation_rejected" else tuple(issues)
        self._seal()

    @property
    def accepted_records(self) -> tuple[T, ...]:
        """Return the accepted model values without their evidence wrappers."""
        return tuple(record.value for record in self.records)

    @property
    def meets_minimum_records(self) -> bool:
        """Return whether accepted values meet this report's requested minimum."""
        return len(self.records) >= self.policy.minimum_records

    def require_all(self) -> list[T]:
        """Return bare values only when the report is fully acceptable.

        Returns:
            A mutable list of accepted Pydantic models. The report keeps its evidence.

        Raises:
            ContractIssues: Rejected candidates, terminal states, or an unmet minimum
                prevent an all-accepted result.
        """
        if (
            self.status not in {"evaluated", "no_match"}
            or self.issues
            or self.extraction_diagnostics
        ):
            raise ContractIssues(_report_rejection(self))
        if not self.meets_minimum_records:
            raise ContractIssues(
                {
                    "kind": "minimum_records",
                    "minimum": self.policy.minimum_records,
                    "observed": len(self.records),
                }
            )
        return list(self.accepted_records)

    def to_archived(self) -> ArchivedContractOutcome:
        """Reject Python-to-Rust archive conversion and name the portable API."""
        raise TypeError(
            "Pydantic Contract values are Python-specific; use RuntimeContract "
            "for portable Rust Contract archives"
        )

    def model_dump(self) -> dict[str, Any]:
        """Return report metadata and safe Pydantic validation details."""
        return {
            "status": self.status,
            "extraction_status": self.extraction_status,
            "document_id": self.document_id,
            "completeness": (
                None
                if self.completeness is None
                else self.completeness.model_dump(mode="json")
            ),
            "reason_code": self.reason_code,
            "failure": (
                None
                if self.failure is None
                else self.failure.model_dump(mode="json", exclude_none=True)
            ),
            "candidates": [
                candidate.model_dump(mode="json") for candidate in self.candidates
            ],
            "records": [
                {
                    "value": record.value.model_dump(mode="json"),
                    "candidate": record.candidate.model_dump(mode="json"),
                }
                for record in self.records
            ],
            "issues": [
                {
                    "kind": issue.kind,
                    "field_ids": list(issue.field_ids),
                    "field_kinds": dict(issue.field_kinds),
                    "observed": issue.observed,
                    "errors": list(issue.errors),
                    "candidate": issue.candidate.model_dump(mode="json"),
                }
                for issue in self.issues
            ],
            "extraction_diagnostics": [
                item.model_dump(mode="json") for item in self.extraction_diagnostics
            ],
        }

    def model_dump_json(self) -> str:
        """Return JSON report details without Pydantic error inputs."""
        return json.dumps(self.model_dump(), default=str)


ContractValidationReport = ContractOutcome
"""Readable alias for the Python Pydantic Contract validation report."""


def _extraction_policy(
    policy: ExtractionPolicy | Mapping[str, Any] | None,
) -> ExtractionPolicy:
    if policy is None:
        return ExtractionPolicy()
    if isinstance(policy, ExtractionPolicy):
        return policy
    return ExtractionPolicy.model_validate(policy)


def _report_status(extraction_status: str) -> str:
    if extraction_status == "candidates":
        return "evaluated"
    if extraction_status == "rejected":
        return "extraction_rejected"
    if extraction_status == "failed":
        return "locate_failed"
    return extraction_status


def _validation_limit_failure(
    candidates: tuple[Candidate, ...],
    contract: type[Contract],
    limits: ValidationLimits,
) -> TerminalFailure | None:
    definition = contract._definition()
    field_count = len(definition.field_map)
    conversion_work = sum(
        max(1, len(field.evidence))
        for candidate in candidates
        for field in candidate.fields.values()
    )
    evidence_count = sum(
        len(field.evidence)
        for candidate in candidates
        for field in candidate.fields.values()
    )
    if contract.model_config.get("validate_by_alias", True):
        for candidate in candidates:
            for name, field_id in definition.field_map:
                info = contract.model_fields[name]
                _, cardinality = _field_type(info.annotation)
                if candidate.field(field_id).evidence or (
                    cardinality == "many" and info.is_required()
                ):
                    conversion_work += sum(
                        abs(part) if part < 0 else part + 1
                        for part in _validation_alias_path(info)
                        if isinstance(part, int)
                    )
    work = (
        ("max_fields", field_count, "field_limit_exceeded", "fields"),
        ("max_records", len(candidates), "record_limit_exceeded", "records"),
        (
            "max_conversions",
            conversion_work,
            "conversion_limit_exceeded",
            "conversions",
        ),
        (
            "max_retained_provenance",
            evidence_count,
            "provenance_limit_exceeded",
            "retained_provenance",
        ),
    )
    for name, observed, failure_kind, limit_name in work:
        maximum = getattr(limits, name)
        if observed > maximum:
            return TerminalFailure(
                kind=failure_kind,
                limit=limit_name,
                maximum=maximum,
                observed=observed,
            )
    return None


def _issue_limit_failure(limits: ValidationLimits, observed: int) -> TerminalFailure:
    return TerminalFailure(
        kind="issue_limit_exceeded",
        limit="issues",
        maximum=limits.max_issues,
        observed=observed,
    )


def _issue_provenance_failure(
    limits: ValidationLimits, total_evidence: int, issue_evidence: int
) -> TerminalFailure | None:
    observed = total_evidence + issue_evidence
    if observed <= limits.max_retained_provenance:
        return None
    return TerminalFailure(
        kind="provenance_limit_exceeded",
        limit="retained_provenance",
        maximum=limits.max_retained_provenance,
        observed=observed,
    )


def _candidate_incomplete_fields(
    definition: _Definition, candidate: Candidate
) -> tuple[str, ...]:
    return tuple(
        field_id
        for _, field_id in definition.field_map
        if any(
            finding.completeness.status != "complete"
            for finding in candidate.field(field_id).evidence
        )
    )


def _candidate_excess_fields(
    definition: _Definition, candidate: Candidate
) -> tuple[tuple[str, int], ...]:
    excess: list[tuple[str, int]] = []
    for name, field_id in definition.field_map:
        _, cardinality = _field_type(definition.contract.model_fields[name].annotation)
        count = len(candidate.field(field_id).evidence)
        if cardinality != "many" and count > 1:
            excess.append((field_id, count))
    return tuple(excess)


def _candidate_validation_inputs(
    definition: _Definition, candidate: Candidate
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    by_alias = definition.contract.model_config.get("validate_by_alias", True)
    for name, field_id in definition.field_map:
        info = definition.contract.model_fields[name]
        _, cardinality = _field_type(info.annotation)
        evidence = candidate.field(field_id).evidence
        if evidence:
            value: Any = [finding.value for finding in evidence]
            if cardinality != "many":
                value = value[0]
            _put_validation_input(values, name, info, value, by_alias=by_alias)
        elif cardinality == "many" and info.is_required():
            _put_validation_input(values, name, info, [], by_alias=by_alias)
    return values


def _put_validation_input(
    values: dict[str, Any], name: str, info: Any, value: Any, *, by_alias: bool
) -> None:
    if not by_alias:
        values[name] = value
        return
    alias = info.validation_alias or info.alias or name
    if isinstance(alias, str):
        values[alias] = value
        return
    choices = getattr(alias, "choices", None)
    if choices:
        alias = choices[0]
        if isinstance(alias, str):
            values[alias] = value
            return
    path = getattr(alias, "path", None)
    if path is None:
        convert = getattr(alias, "convert_to_aliases", None)
        path = convert() if callable(convert) else None
    if not path:
        values[name] = value
        return
    cursor: Any = values
    for index, component in enumerate(path):
        final = index == len(path) - 1
        if final:
            if isinstance(cursor, list):
                required = -component if component < 0 else component + 1
                while len(cursor) < required:
                    cursor.append(None)
                cursor[component] = value
            else:
                cursor[component] = value
            return
        next_is_index = isinstance(path[index + 1], int)
        if isinstance(cursor, list):
            required = -component if component < 0 else component + 1
            while len(cursor) < required:
                cursor.append(None)
            child = cursor[component]
        else:
            child = cursor.get(component)
        if child is None:
            child = [] if next_is_index else {}
            if isinstance(cursor, list):
                cursor[component] = child
            else:
                cursor[component] = child
        elif not isinstance(child, list if next_is_index else dict):
            child = [] if next_is_index else {}
            if isinstance(cursor, list):
                cursor[component] = child
            else:
                cursor[component] = child
        cursor = child


def _validation_alias_path(info: Any) -> tuple[str | int, ...]:
    alias = info.validation_alias or info.alias
    choices = getattr(alias, "choices", None)
    if choices:
        alias = choices[0]
    return tuple(getattr(alias, "path", ()))


def _manual_issue(
    candidate: Candidate,
    field_ids: tuple[str, ...],
    kind: str,
    *,
    observed: int | None = None,
) -> ContractRecordIssue:
    evidence = tuple(
        finding
        for field_id in field_ids
        for finding in candidate.field(field_id).evidence
    )
    return ContractRecordIssue(
        candidate=candidate,
        field_ids=field_ids,
        kind=kind,
        evidence=evidence,
        observed=observed,
        field_kinds=tuple((field_id, kind) for field_id in field_ids),
    )


def _excess_issue(
    definition: _Definition,
    candidate: Candidate,
    excess: tuple[tuple[str, int], ...],
) -> ContractRecordIssue:
    names = {field_id: name for name, field_id in definition.field_map}
    line_errors: list[InitErrorDetails] = [
        {
            "type": PydanticCustomError(
                "multiple_candidates", "expected one finding for this field"
            ),
            "loc": (names[field_id],),
            "input": None,
        }
        for field_id, _ in excess
    ]
    error = ValidationError.from_exception_data(
        definition.contract.__name__, line_errors
    )
    issue = _manual_issue(
        candidate,
        tuple(field_id for field_id, _ in excess),
        "excess_candidates",
        observed=max(count for _, count in excess),
    )
    return ContractRecordIssue(
        candidate=issue.candidate,
        field_ids=issue.field_ids,
        kind=issue.kind,
        evidence=issue.evidence,
        error=error,
        observed=issue.observed,
        field_kinds=issue.field_kinds,
    )


def _validation_issue(
    contract: type[Contract],
    definition: _Definition,
    candidate: Candidate,
    error: ValidationError,
) -> ContractRecordIssue:
    field_ids: list[str] = []
    field_kinds: dict[str, str] = {}
    by_key: dict[tuple[str | int, ...], str] = {}

    def bind(field_id: str, key: str | tuple[str | int, ...]) -> None:
        by_key[(key,) if isinstance(key, str) else key] = field_id

    for name, field_id in definition.field_map:
        info = contract.model_fields[name]
        bind(field_id, name)
        for key in (info.alias, info.validation_alias):
            if isinstance(key, str):
                bind(field_id, key)
                continue
            for choice in getattr(key, "choices", ()):
                if isinstance(choice, str):
                    bind(field_id, choice)
                else:
                    path = getattr(choice, "path", None)
                    if path:
                        bind(field_id, tuple(path))
            path = getattr(key, "path", None)
            if path:
                bind(field_id, tuple(path))
    details = error.errors(include_input=False, include_url=False)
    for detail in details:
        location = detail.get("loc", ())
        field_id = next(
            (
                by_key[location[:depth]]
                for depth in range(len(location), 0, -1)
                if location[:depth] in by_key
            ),
            None,
        )
        if field_id is not None:
            if field_id not in field_ids:
                field_ids.append(field_id)
            error_kind = (
                "missing_required"
                if detail.get("type") == "missing"
                else "validation_error"
            )
            field_kinds[field_id] = error_kind
    if not field_ids:
        field_ids = [field_id for _, field_id in definition.field_map]
    ordered = tuple(
        field_id for _, field_id in definition.field_map if field_id in field_ids
    )
    kinds = tuple(
        (field_id, field_kinds.get(field_id, "validation_error"))
        for field_id in ordered
    )
    kind = (
        "missing_required"
        if kinds and all(value == "missing_required" for _, value in kinds)
        else "validation_error"
    )
    return ContractRecordIssue(
        candidate=candidate,
        field_ids=ordered,
        kind=kind,
        evidence=tuple(
            finding
            for field_id in ordered
            for finding in candidate.field(field_id).evidence
        ),
        error=error,
        field_kinds=kinds,
    )


def _partial_completeness(
    evidence: tuple[Finding, ...], prior: Completeness | None
) -> Completeness:
    for finding in evidence:
        completeness = finding.completeness
        if completeness.status != "complete":
            return completeness
    if prior is not None and prior.status != "complete":
        return prior
    return Partial(status="partial", reason_code="incomplete_candidate_evidence")


def _report_rejection(report: ContractOutcome[Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"kind": report.status}
    if report.document_id is not None:
        result["document_id"] = report.document_id
    if report.reason_code is not None:
        result["reason_code"] = report.reason_code
    if report.failure is not None:
        result["failure"] = report.failure.model_dump(mode="json", exclude_none=True)
    if report.completeness is not None:
        result["completeness"] = report.completeness.model_dump(mode="json")
    if report.issues:
        result["issues"] = [
            {
                "kind": issue.kind,
                "field_ids": list(issue.field_ids),
                "field_kinds": dict(issue.field_kinds),
                "observed": issue.observed,
                "errors": list(issue.errors),
            }
            for issue in report.issues
        ]
    if report.extraction_diagnostics:
        result["extraction_diagnostics"] = [
            item.model_dump(mode="json") for item in report.extraction_diagnostics
        ]
    return result


def _accepted_records[T: Contract](
    report: ContractOutcome[T], policy: ExtractionPolicy
) -> list[T]:
    if report.status not in {"evaluated", "no_match"}:
        raise ContractIssues(_report_rejection(report))
    if report.issues and policy.on_rejected_record == "raise":
        if (
            len(report.issues) == 1
            and report.issues[0].error is not None
            and not report.extraction_diagnostics
        ):
            raise report.issues[0].error
        raise ContractIssues(_report_rejection(report))
    if report.extraction_diagnostics and policy.on_rejected_record == "raise":
        raise ContractIssues(_report_rejection(report))
    if len(report.records) < policy.minimum_records:
        raise ContractIssues(
            {
                "kind": "minimum_records",
                "minimum": policy.minimum_records,
                "observed": len(report.records),
            }
        )
    return list(report.accepted_records)


def extract[T: "Contract"](
    document: Document | BoundDocument | ParsedDocument,
    contract: type[T],
    *,
    policy: ExtractionPolicy | None = None,
) -> list[T]:
    """Return validated Pydantic models extracted from a document."""
    effective = _extraction_policy(policy)
    return contract.extract(document, policy=effective)


def extract_report[T: "Contract"](
    document: Document | BoundDocument | ParsedDocument,
    contract: type[T],
    *,
    policy: ExtractionPolicy | None = None,
) -> ContractOutcome[T]:
    """Return a report with accepted models, rejected candidates, and evidence."""
    return contract.extract_report(document, policy=policy)


from . import runtime_contracts as _runtime_contracts  # noqa: E402

ContractSchemaFailure = _runtime_contracts.ContractSchemaFailure
RuntimeCandidate = _runtime_contracts.RuntimeCandidate
ArchivedContractCandidateField = _runtime_contracts.ArchivedContractCandidateField
ArchivedContractField = _runtime_contracts.ArchivedContractField
ArchivedContractMoneyUsd = _runtime_contracts.ArchivedContractMoneyUsd
ArchivedContractOutcome = _runtime_contracts.ArchivedContractOutcome
ArchivedContractRecordIssue = _runtime_contracts.ArchivedContractRecordIssue
ArchivedContractString = _runtime_contracts.ArchivedContractString
ArchivedContractValue = _runtime_contracts.ArchivedContractValue
ArchivedValidatedContractRecord = _runtime_contracts.ArchivedValidatedContractRecord
RuntimeContract = _runtime_contracts.RuntimeContract
RuntimeContractOutcome = _runtime_contracts.RuntimeContractOutcome
RuntimeExactlyOne = _runtime_contracts.RuntimeExactlyOne
RuntimeExtracted = _runtime_contracts.RuntimeExtracted
RuntimeExtractionFailure = _runtime_contracts.RuntimeExtractionFailure
RuntimeFieldValue = _runtime_contracts.RuntimeFieldValue
RuntimeMany = _runtime_contracts.RuntimeMany
RuntimeMoneyUsd = _runtime_contracts.RuntimeMoneyUsd
RuntimeRecordIssue = _runtime_contracts.RuntimeRecordIssue
RuntimeString = _runtime_contracts.RuntimeString
RuntimeValidationFailure = _runtime_contracts.RuntimeValidationFailure
RuntimeValidatedRecord = _runtime_contracts.RuntimeValidatedRecord
RuntimeValue = _runtime_contracts.RuntimeValue
RuntimeZeroOrOne = _runtime_contracts.RuntimeZeroOrOne

# Resolve the generic bound once during module import. Runtime subscripting
# can ask Pydantic to rebuild this shared schema concurrently without the GIL.
ValidatedRecord.model_rebuild()
