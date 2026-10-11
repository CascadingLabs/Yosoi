"""Declarative Contracts over Rust's extraction and validation pipeline."""

from __future__ import annotations

import json
import types
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from threading import RLock
from typing import (
    Annotated,
    Any,
    ClassVar,
    Literal,
    NoReturn,
    Protocol,
    Self,
    SupportsIndex,
    TypeVar,
    Union,
    get_args,
    get_origin,
)

from pydantic import Field as PydanticField
from pydantic import SerializeAsAny, TypeAdapter, create_model, model_validator
from pydantic_core import PydanticUndefined
from typing_extensions import Doc

from . import _native
from ._models import ImmutableModel, NativeAuthoringModel
from .documents import BoundDocument, Document, ParsedDocument
from .identities import ContractIdentity
from .locators import Locator, Plan, Query, output
from .outcomes import (
    Completeness,
    Finding,
    LocateOutcome,
    ProjectedValue,
    RegionLineage,
)
from .scalars import RUST_DOMAIN_VALIDATED, ContractId, FieldId

T = TypeVar("T", bound="Contract")
Cardinality = Literal["exactly_one", "zero_or_one", "many"]
"""Required accepted field count: exactly one, zero or one, or an ordered collection
including empty. Rust validation enforces these distinctions after extraction.
"""


class ContractValue(Protocol):
    """Identity-only protocol for the Rust Contract scalar vocabulary.

    Attributes:
        TYPE_ID: Stable scalar identifier included in schema identity. This protocol
            alone does not register a runtime converter.
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

    minor_units: Annotated[int, PydanticField(strict=True, repr=False)]
    currency: Literal["usd"] = "usd"

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
    description: str,
    *,
    id: str | FieldId | None = None,
    locator: Locator | Query | None = None,
    default: Any = PydanticUndefined,
    **kwargs: Any,
) -> Any:
    """Describe a Contract field using a genuine Pydantic FieldInfo.

    A bare query uses text projection. Defaults affect model authoring, while
    extraction cardinality and missing-value behavior follow the Rust schema.
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
    """Rust-validated field meaning, cardinality, and type metadata.

    Attributes:
        id: Authored identifier matching locator output evidence.
        description: Nonblank business meaning; it does not discover a locator.
        cardinality: exactly_one, zero_or_one, or many constrains validation, not
            extraction.
        value_type: Nonblank conversion identifier; runtime Contracts support string and
            money.usd.
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
    """Portable record meaning, scope, and ordered field declarations.

    Attributes:
        version: Supported portable format version, currently 1.
        id: Authored record identity, distinct from a document or execution ID.
        description: Nonblank record meaning, excluded from semantic hashing.
        scope: page groups compatible findings into one record; repeated groups by
            parent-region lineage.
        fields: Nonempty ordered fields with unique IDs. Order, IDs, cardinalities, and
            type IDs contribute to identity; descriptions do not.
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
    """Rust-owned default budgets for conversion and validation accounting.

    Attributes:
        max_fields: Maximum schema fields requiring validation.
        max_records: Maximum candidate records requiring validation.
        max_conversions: Maximum charged field conversions.
        max_issues: Maximum retained field rejection issues.
        max_retained_provenance: Maximum retained finding evidence references.
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
    """Accepted typed value with original candidate evidence retained.

    Attributes:
        value: Record accepted by Rust cardinality, conversion, and semantics.
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
        detail: Copied top-level Rust rejection mapping. Nested values are not
            recursively frozen; the original outcome remains available.
    """

    def __init__(self, detail: Mapping[str, Any]) -> None:
        """Copy top-level Rust rejection details and encode an exception message.

        Args:
            detail: Rejection counts or terminal classification supplied by Rust.

        Nested values are not frozen; the original outcome retains its evidence.
        """
        self.detail = dict(detail)
        super().__init__(json.dumps(self.detail))


class Contract(ImmutableModel):
    """Typed record definition with Rust-owned cardinality and validation.

    Attributes:
        root: Optional repeated-region query; None selects page grouping.
        contract_id: Optional schema ID; the class name is used when omitted.
        contract_description: Optional meaning; class docstring or name supplies the
            default. Fields require Field and nonblank descriptions.
    """

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
        """Return this class's validated schema without document I/O.

        Raises:
            ContractError: Fields, scalar annotations, aliases, or processing hooks
                cannot be represented by the supported Rust vocabulary.
        """
        return cls._definition().schema

    @classmethod
    def identity(cls) -> ContractIdentity:
        """Return Rust's semantic identity for this typed schema.

        Descriptions do not affect identity. Version, Contract ID, scope, and ordered
        field IDs, cardinalities, and scalar type IDs do.

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
    def extract(
        cls: type[T], located: LocateOutcome, *, limits: ExtractionLimits | None = None
    ) -> Extracted[T]:
        """Group located evidence without converting or validating values.

        Args:
            located: Locator outcome retaining completeness and failure distinctions.
            limits: Explicit assembly budgets, or None for Rust defaults.

        Returns:
            Read-only candidates, diagnostics, or a terminal state. Call validate
            explicitly before treating candidate evidence as accepted records.

        Raises:
            ContractError: Declaration or native input setup cannot be represented.
        """
        handle = cls._definition().handle.extract(
            located.model_dump_json(exclude_none=True),
            None if limits is None else limits.model_dump_json(),
        )
        return Extracted(cls, handle)


class _Definition:
    def __init__(self, contract: type[Contract]) -> None:
        _reject_python_processing_hooks(contract)
        contract.model_rebuild()
        fields: list[FieldSchema] = []
        pins: list[tuple[str, str, Locator | None]] = []
        self.field_map: list[tuple[str, str]] = []
        for name, info in contract.model_fields.items():
            unsupported_metadata = [
                item
                for item in info.metadata
                if not isinstance(item, (_LocatorMetadata, Doc))
            ]
            if unsupported_metadata:
                raise _native.ContractError(
                    f"field {name!r} has Python processing metadata that Rust "
                    "Contracts do not support"
                )
            value_type, cardinality = _field_type(info.annotation)
            description = info.description
            if not description:
                raise _native.ContractError(f"field {name!r} requires a description")
            metadata = [
                item for item in info.metadata if isinstance(item, _LocatorMetadata)
            ]
            if len(metadata) != 1:
                raise _native.ContractError(f"field {name!r} must use ys.Field")
            field_id = metadata[0].field_id or name
            if (
                info.alias is not None
                or info.validation_alias is not None
                or info.serialization_alias is not None
            ):
                raise _native.ContractError(
                    "Contract field aliases are not supported by Rust"
                )
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
        reserved = set(Candidate.model_fields)
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


def _reject_python_processing_hooks(contract: type[Contract]) -> None:
    decorators = contract.__pydantic_decorators__
    unsupported = [
        name
        for name in (
            "field_validators",
            "root_validators",
            "model_validators",
            "field_serializers",
            "model_serializers",
            "computed_fields",
        )
        if getattr(decorators, name)
    ]
    if contract.__dict__.get("__init__") is not None:
        unsupported.append("custom initializer")
    if contract.__dict__.get("model_post_init") is not None:
        unsupported.append("model_post_init")
    if unsupported:
        raise _native.ContractError(
            "Python Contract processing hooks are not supported: "
            + ", ".join(unsupported)
            + "; conversion and validation are Rust-owned"
        )


def _field_type(annotation: Any) -> tuple[Literal["string", "money.usd"], Cardinality]:
    cardinality: Cardinality = "exactly_one"
    origin = get_origin(annotation)
    if origin in (Union, types.UnionType):
        args = get_args(annotation)
        non_none = tuple(arg for arg in args if arg is not type(None))
        if len(args) != 2 or len(non_none) != 1:
            raise _native.ContractError("only scalar T | None is supported")
        annotation = non_none[0]
        cardinality = "zero_or_one"
    elif annotation is list:
        raise _native.ContractError(
            "Contract list fields require one scalar element type"
        )
    elif origin is list:
        args = get_args(annotation)
        if len(args) != 1:
            raise _native.ContractError(
                "Contract list fields require one scalar element type"
            )
        (annotation,) = args
        cardinality = "many"
    if annotation is str:
        return "string", cardinality
    if annotation is Money:
        return "money.usd", cardinality
    raise _native.ContractError(
        "Rust Contracts support str and Money, optionally None or list[T]"
    )


class _FrozenList(list[Any]):
    """A list-shaped immutable value for Rust-validated `Many` fields."""

    @staticmethod
    def _readonly(*args: Any, **kwargs: Any) -> NoReturn:
        del args, kwargs
        raise TypeError("Contract record values are read-only")

    __setitem__ = _readonly
    __delitem__ = _readonly

    def __iadd__(self, value: Iterable[Any]) -> Self:
        del value
        self._readonly()

    def __imul__(self, value: SupportsIndex) -> Self:
        del value
        self._readonly()

    append = _readonly
    clear = _readonly
    extend = _readonly
    insert = _readonly
    pop = _readonly
    remove = _readonly
    reverse = _readonly
    sort = _readonly


def _record[T: "Contract"](contract: type[T], data: Mapping[str, Any]) -> T:
    values: dict[str, Any] = {}
    for python_name, field_id in contract._definition().field_map:
        field = data[field_id]
        if field["cardinality"] == "many":
            values[python_name] = _FrozenList(
                _scalar(value) for value in field["values"]
            )
        else:
            value = field["value"]
            values[python_name] = None if value is None else _scalar(value)
    # Rust has already converted and validated every field. Pydantic validators
    # and defaults must not change the equivalent Rust record.
    return contract.model_construct(**values)


def _scalar(value: Mapping[str, Any]) -> str | Money:
    if value["type"] == "string":
        return value["value"]
    return Money.model_validate(value["value"])


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

    def validate(self, *, limits: ValidationLimits | None = None) -> ContractOutcome[T]:
        """Convert and validate evidence with explicit or default budgets.

        Args:
            limits: Validation budgets, or None for Rust defaults.

        Returns:
            Accepted records, rejected candidates, or terminal states. Incomplete
            evidence is never converted into an empty successful result.
        """
        return ContractOutcome(
            self.contract,
            self._handle.validate(None if limits is None else limits.model_dump_json()),
        )

    def model_dump(self) -> dict[str, Any]:
        """Return a new native wire-data dictionary without validating again."""
        return json.loads(self._handle.to_json())

    def model_dump_json(self) -> str:
        """Return native wire JSON with evidence and terminal states preserved."""
        return self._handle.to_json()


class ContractOutcome[T: "Contract"](_ReadOnlyView):
    """Read-only evaluation retaining accepted and rejected candidates.

    Attributes:
        contract: Typed record definition used for validation.
        status: evaluated, no_match, indeterminate, locate_failed, extraction_rejected,
            or validation_rejected retains the phase distinction.
        document_id: Evidence document identity when available.
        failure: Typed phase or operation-budget rejection when present.
        completeness: Partial or unknown coverage for indeterminate outcomes.
        reason_code: Structural explanation of indeterminate coverage.
        records: Accepted typed values and original candidate evidence.
        issues: Rejected candidates with field-specific reasons and findings.
        extraction_diagnostics: Nonfatal grouping issues preventing an all-accepted
            claim.
    """

    __slots__ = (
        "contract",
        "_handle",
        "status",
        "document_id",
        "failure",
        "completeness",
        "reason_code",
        "records",
        "issues",
        "extraction_diagnostics",
    )

    def __init__(self, contract: type[T], handle: _native.ContractOutcome) -> None:
        """Retain a native evaluation handle and read-only typed results.

        Args:
            contract: Definition used to interpret converted values.
            handle: Native validation outcome from the Rust pipeline.

        Rust results are reconstructed without Python validators or defaults changing
        accepted records. Construction does not acquire documents.
        """
        self.contract = contract
        self._handle = handle
        wire = json.loads(handle.to_json())
        self.status: str = wire["status"]
        self.document_id: str | None = wire.get("document_id")
        failure_data = (
            TypeAdapter(_runtime_contracts.RuntimeContractOutcomeData).validate_python(
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
                    _runtime_contracts._RuntimeOutcomeLocateFailed,
                    _runtime_contracts._RuntimeExtractionRejected,
                    _runtime_contracts._RuntimeValidationRejected,
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
        self.records: tuple[ValidatedRecord[T], ...] = tuple(
            ValidatedRecord(
                value=_record(contract, item["value"]),
                candidate=contract._definition().candidate(item["candidate"]),
            )
            for item in wire.get("records", [])
        )
        self.issues = tuple(
            RecordIssue(
                candidate=contract._definition().candidate(item["candidate"]),
                fields=tuple(
                    FieldIssue.model_validate(field) for field in item["fields"]
                ),
            )
            for item in wire.get("issues", [])
        )
        self.extraction_diagnostics = tuple(
            ExtractionDiagnostic.model_validate(item)
            for item in wire.get("extraction_diagnostics", [])
        )
        self._seal()

    def require_all(self) -> list[T]:
        """Return values only when no record or extraction issue remains.

        Returns:
            A new typed list, empty for complete no-match. The original outcome
            remains available for inspection of evidence and rejected records.

        Raises:
            ContractIssues: Issues, indeterminate evidence, or failed phases prevent
                an all-accepted result.
        """
        result = json.loads(self._handle.require_all())
        if "error" in result:
            raise ContractIssues(result["error"])
        return [_record(self.contract, item["value"]) for item in result["records"]]

    def to_archived(self) -> ArchivedContractOutcome:
        """Return Rust's code-independent portable archive representation."""
        return _runtime_contracts._archived_outcome(
            self._handle, self.contract.contract_schema()
        )

    def model_dump(self) -> dict[str, Any]:
        """Return a new native wire-data dictionary without validating again."""
        return json.loads(self._handle.to_json())

    def model_dump_json(self) -> str:
        """Return native wire JSON with evidence and terminal states preserved."""
        return self._handle.to_json()


def extract[T: "Contract"](
    document: Document | BoundDocument | ParsedDocument, contract: type[T]
) -> Extracted[T]:
    """Locate pinned fields and return Rust's extraction outcome."""
    return contract.extract(document.locate(contract.plan()))


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
