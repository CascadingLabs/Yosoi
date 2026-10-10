"""Native exceptions preserve exact Rust discriminants without changing categories."""

import pytest
from pydantic import ValidationError

import yosoi as ys
import yosoi._native as native
from yosoi.errors import (
    ContractError,
    LocatorError,
    PolicyError,
    RustErrorDetails,
    rust_error_details,
)
from yosoi.locators import ByteRange


def test_policy_error_keeps_rust_variant_payload_and_exception_category() -> None:
    search = ys.policy.Search(
        providers=[ys.policy.ProviderSelection.current(ys.policy.Provider.bing)]
    )
    with pytest.raises(PolicyError) as caught:
        search.with_result_limits(10, 5)

    detail = rust_error_details(caught.value)
    assert isinstance(detail, RustErrorDetails)
    assert detail.rust_type == "yosoi_policy::PolicyError"
    assert detail.variant == "SearchPlanExceedsTotalResults"
    assert detail.details == {"required": 10, "limit": 5}
    assert str(caught.value) == (
        "Search total-hit limit 5 is below the planned maximum 10"
    )


def test_locator_errors_expose_query_plan_and_coordinate_variants() -> None:
    with pytest.raises(LocatorError) as query_error:
        ys.css("")
    query_detail = rust_error_details(query_error.value)
    assert query_detail is not None
    assert query_detail.rust_type == "yosoi_documents::QueryError"
    assert query_detail.variant == "EmptyExpression"
    assert query_detail.details == {}

    with pytest.raises(LocatorError) as nested_query_error:
        ys.json_pointer("relative")
    nested_detail = rust_error_details(nested_query_error.value)
    assert nested_detail is not None
    assert nested_detail.variant == "InvalidJsonQuery"
    assert nested_detail.details["source"]["variant"] == "InvalidPointerSyntax"
    assert nested_detail.source_chain == ()

    with pytest.raises(LocatorError) as plan_error:
        ys.Plan(outputs=())
    plan_detail = rust_error_details(plan_error.value)
    assert plan_detail is not None
    assert plan_detail.rust_type == "yosoi_documents::PlanError"
    assert plan_detail.variant == "NoOutputs"

    query = ys.css("h1").text()
    with pytest.raises(LocatorError) as duplicate_output:
        ys.Plan(
            outputs=(
                ys.output("title", query),
                ys.output("title", query),
            )
        )
    duplicate_detail = rust_error_details(duplicate_output.value)
    assert duplicate_detail is not None
    assert duplicate_detail.variant == "DuplicateOutput"
    assert duplicate_detail.details == {"id": "title"}

    with pytest.raises(LocatorError) as coordinate_error:
        ByteRange.try_new(4, 3)
    coordinate_detail = rust_error_details(coordinate_error.value)
    assert coordinate_detail is not None
    assert coordinate_detail.rust_type == "yosoi_documents::CoordinateError"
    assert coordinate_detail.variant == "ReversedRange"

    with pytest.raises(LocatorError) as decode_error:
        native.validate_domain_model("byte_range", "{")
    decode_detail = rust_error_details(decode_error.value)
    assert decode_detail is not None
    assert decode_detail.rust_type == "serde_json::Error"
    assert decode_detail.variant == "Eof"
    assert decode_detail.details["category"] == "eof"


def test_contract_errors_expose_schema_runtime_and_archive_variants() -> None:
    with pytest.raises(ValidationError) as schema_error:
        ys.contracts.FieldSchema(
            id="",
            description="Title",
            cardinality="exactly_one",
            value_type="string",
        )
    schema_detail = rust_error_details(schema_error.value)
    assert schema_detail is not None
    assert schema_detail.rust_type == "yosoi_contracts::ContractSchemaError"
    assert schema_detail.variant == "EmptyFieldId"

    with pytest.raises(ContractError) as schema_payload_error:
        ys.contracts.FieldSchema(
            id="title",
            description="",
            cardinality="exactly_one",
            value_type="string",
        )
    schema_payload = rust_error_details(schema_payload_error.value)
    assert schema_payload is not None
    assert schema_payload.variant == "EmptyFieldDescription"
    assert schema_payload.details == {"field": "title"}

    schema = ys.contracts.ContractSchema(
        id="archive-errors",
        description="Error metadata test",
        scope="page",
        fields=(
            ys.contracts.FieldSchema(
                id="title",
                description="Title",
                cardinality="exactly_one",
                value_type="string",
            ),
        ),
    )
    with pytest.raises(ContractError) as runtime_error:
        ys.contracts.RuntimeContract.new(
            schema.model_copy(
                update={
                    "fields": (
                        ys.contracts.FieldSchema(
                            id="title",
                            description="Title",
                            cardinality="exactly_one",
                            value_type="integer",
                        ),
                    )
                }
            )
        )
    runtime_detail = rust_error_details(runtime_error.value)
    assert runtime_detail is not None
    assert runtime_detail.rust_type == "yosoi_contract_validation::RuntimeContractError"
    assert runtime_detail.variant == "UnsupportedValueType"
    assert runtime_detail.details == {"field": "title", "value_type": "integer"}

    outcome = (
        ys.contracts.RuntimeContract.new(schema)
        .extract(
            ys.Document.html("empty", "<p>no title</p>").locate(
                ys.Plan(outputs=(ys.output("title", ys.css("h1").text()),))
            )
        )
        .validate()
    )
    unsupported_schema = ys.contracts.ContractSchema(
        id="archive-errors",
        description="Error metadata test",
        scope="page",
        fields=(
            ys.contracts.FieldSchema(
                id="title",
                description="Title",
                cardinality="exactly_one",
                value_type="integer",
            ),
        ),
    )
    with pytest.raises(ContractError) as archive_error:
        outcome._handle.to_archived(unsupported_schema.model_dump_json())
    archive_detail = rust_error_details(archive_error.value)
    assert archive_detail is not None
    assert archive_detail.rust_type == (
        "yosoi_contract_validation::RuntimeContractArchiveError"
    )
    assert archive_detail.variant == "UnsupportedValueType"
    assert archive_detail.details == {"field": "title", "value_type": "integer"}
