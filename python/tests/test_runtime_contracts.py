from typing import Any, cast

import pytest

import yosoi as ys
from yosoi.contracts import (
    ContractSchema,
    ExtractionLimits,
    FieldSchema,
    RuntimeExactlyOne,
    RuntimeMany,
    RuntimeString,
    RuntimeZeroOrOne,
    ValidationLimits,
)


def runtime_schema(value_type: str = "string") -> ContractSchema:
    return ContractSchema(
        id="runtime-book",
        description="Runtime-authored book",
        scope="repeated",
        fields=(
            FieldSchema(
                id="title_id",
                description="Title",
                cardinality="exactly_one",
                value_type=value_type,
            ),
            FieldSchema(
                id="optional_id",
                description="Optional value",
                cardinality="zero_or_one",
                value_type="string",
            ),
            FieldSchema(
                id="tags_id",
                description="Tags",
                cardinality="many",
                value_type="string",
            ),
        ),
    )


def repeated_plan() -> ys.Plan:
    rows = ys.css("article").each_as_region("runtime-book")
    return ys.Plan(
        outputs=(
            ys.output("title_id", rows.find(ys.css("h2")).text()),
            ys.output("optional_id", rows.find(ys.css(".optional")).text()),
            ys.output("tags_id", rows.find(ys.css(".tag")).text()),
        )
    )


def test_runtime_contract_preserves_schema_ids_grouping_and_typed_values() -> None:
    schema = runtime_schema()
    contract = ys.contracts.RuntimeContract.new(schema)
    assert contract.contract_schema == schema
    assert contract.identity() == schema.identity()

    document = ys.Document.html(
        "runtime",
        "<article><h2>A</h2><i class='optional'>one</i>"
        "<i class='tag'>red</i><i class='tag'>blue</i></article>"
        "<article><h2>B</h2></article>",
    )
    extracted = contract.extract(document.locate(repeated_plan()))
    assert extracted.status == "candidates"
    assert len(extracted.candidates) == 2
    first, second = extracted.candidates
    assert set(first.fields) == {"title_id", "optional_id", "tags_id"}
    assert first.fields["title_id"][0].value == "A"
    assert first.fields["tags_id"][1].value == "blue"
    assert second.fields["optional_id"] == ()
    assert second.fields["tags_id"] == ()
    assert second.model_dump(mode="json")["fields"]["optional_id"] == []
    assert '"optional_id":[]' in second.model_dump_json()
    # The typed view fills absent schema fields; its Rust wire stays unchanged.
    assert "optional_id" not in extracted.model_dump()["candidates"][1]["fields"]
    with pytest.raises(TypeError):
        cast(Any, first.fields)["optional_id"] = ()
    with pytest.raises(AttributeError, match="read-only"):
        cast(Any, extracted).status = "no_match"

    outcome = extracted.validate()
    assert outcome.status == "evaluated"
    exactly_one = outcome.records[0].value["title_id"]
    optional = outcome.records[0].value["optional_id"]
    many = outcome.records[0].value["tags_id"]
    assert isinstance(exactly_one, RuntimeExactlyOne)
    assert isinstance(exactly_one.value, RuntimeString)
    assert exactly_one.value.value == "A"
    assert isinstance(optional, RuntimeZeroOrOne)
    assert isinstance(optional.value, RuntimeString)
    assert optional.value.value == "one"
    assert isinstance(many, RuntimeMany)
    assert [item.value for item in many.values if isinstance(item, RuntimeString)] == [
        "red",
        "blue",
    ]
    required = outcome.require_all()
    assert len(required) == 2
    assert required[1].value["tags_id"] == RuntimeMany(cardinality="many", values=())
    serialized_record = required[0].model_dump(mode="json")
    assert serialized_record["value"]["title_id"]["cardinality"] == "exactly_one"


def test_runtime_outcome_to_archived_uses_portable_schema() -> None:
    schema = runtime_schema("money.usd")
    contract = ys.contracts.RuntimeContract.new(schema)
    document = ys.Document.html(
        "runtime-archive",
        "<article><h2>$4.50</h2></article><article><h2>$0.00</h2></article>",
    )
    outcome = contract.extract(document.locate(repeated_plan())).validate()
    archived = outcome.to_archived()
    assert (
        outcome.to_archived(outcome.contract_schema).model_dump()
        == archived.model_dump()
    )
    assert archived.status == "evaluated"
    assert len(archived.records) == 2
    wire = archived.model_dump()
    second = wire["records"][1]
    assert second["fields"] == [
        {
            "id": "title_id",
            "value": {
                "cardinality": "exactly_one",
                "value": {"type": "money_usd", "minor_units": 0},
            },
        },
        {
            "id": "optional_id",
            "value": {"cardinality": "zero_or_one", "value": None},
        },
        {"id": "tags_id", "value": {"cardinality": "many", "values": []}},
    ]
    assert [item["id"] for item in second["evidence"]] == [
        "title_id",
        "optional_id",
        "tags_id",
    ]
    assert len(second["evidence"][0]["evidence"]) == 1
    assert second["evidence"][1]["evidence"] == []
    assert second["evidence"][2]["evidence"] == []
    assert "$0.00" not in repr(archived.view)
    assert "$0.00" in archived.model_dump_json()


def test_runtime_contract_keeps_no_match_and_limit_outcomes_typed() -> None:
    contract = ys.contracts.RuntimeContract.new(runtime_schema())
    document = ys.Document.html("none", "<p>none</p>")
    no_match = contract.extract(document.locate(repeated_plan()))
    assert no_match.status == "no_match"
    no_match_outcome = no_match.validate()
    assert no_match_outcome.status == "no_match"
    assert no_match_outcome.to_archived().status == "no_match"
    assert no_match.validate().require_all() == []

    located = ys.Document.html("limited", "<article><h2>A</h2></article>").locate(
        repeated_plan()
    )
    rejected = contract.extract(located, limits=ExtractionLimits.uniform(0))
    assert rejected.status == "rejected"
    assert rejected.failure is not None
    assert rejected.failure.kind == "limit_exceeded"
    assert rejected.validate().status == "extraction_rejected"
    archived_extraction_rejection = rejected.validate().to_archived()
    assert archived_extraction_rejection.failure is not None
    assert archived_extraction_rejection.failure.kind == "limit_exceeded"

    validation_rejected = contract.extract(located).validate(
        limits=ValidationLimits(max_records=0)
    )
    assert validation_rejected.status == "validation_rejected"
    archived_validation_rejection = validation_rejected.to_archived()
    assert archived_validation_rejection.failure is not None
    assert archived_validation_rejection.failure.kind == "record_limit_exceeded"
    with pytest.raises(ys.contracts.ContractIssues):
        validation_rejected.require_all()


def test_runtime_contract_rejects_schema_value_types_outside_rust_vocabulary() -> None:
    with pytest.raises(ys._native.ContractError):
        ys.contracts.RuntimeContract.new(runtime_schema("integer"))
