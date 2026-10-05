"""Rust-authoritative contract semantics through the public Python SDK."""

import json
import typing
from typing import Any, cast

import pytest
from pydantic import (
    AfterValidator,
    ValidationError,
    computed_field,
    field_serializer,
    field_validator,
)
from typing_extensions import Doc

import yosoi as ys
from yosoi.contracts import ContractIssues
from yosoi.outcomes import _read


class Book(ys.Contract):
    """A book for sale."""

    root = ys.css("article")
    author: str = ys.Field("Author", locator=ys.css(".author"))
    price: ys.Money = ys.Field("Price", locator=ys.css(".price"))
    link: str | None = ys.Field(
        "Link", locator=ys.css("a").attribute("href"), default=None
    )
    tags: list[str] = ys.Field("Tags", locator=ys.css(".tag"))


def test_repeated_records_and_named_candidate_evidence():
    document = ys.Document.html(
        "books",
        """
      <article><b class=author>Ada</b><b class=price>$12.34</b>
        <a href=/ada></a><i class=tag>a</i><i class=tag>b</i></article>
      <article><b class=author>Grace</b><b class=price>$0.00</b></article>
    """,
    )
    extracted = ys.extract(document, Book)
    assert extracted.status == "candidates"
    assert len(extracted.candidates) == 2
    candidate = extracted.candidates[0]
    candidate_author = cast(Any, candidate).author
    assert candidate_author.evidence[0].value == "Ada"
    assert candidate_author.values[0].value == "Ada"
    assert candidate.region is not None
    assert candidate.region.region_id == "Book"
    assert "Ada" not in repr(candidate)
    assert "Ada" not in repr(candidate_author)
    outcome = extracted.validate()
    assert outcome.status == "evaluated"
    assert outcome.records[0].candidate == candidate
    with pytest.raises(AttributeError, match="read-only"):
        extracted.status = "no_match"
    with pytest.raises(AttributeError, match="read-only"):
        outcome.status = "no_match"
    records = outcome.require_all()
    assert [record.author for record in records] == ["Ada", "Grace"]
    assert records[0].price.minor_units == 1234
    assert str(records[0].price) == "$12.34"
    assert "1234" not in repr(records[0].price)
    assert "$12.34" not in repr(outcome.records[0])
    assert records[0].tags == ["a", "b"]
    with pytest.raises(TypeError, match="read-only"):
        outcome.records[0].value.tags.append("changed")
    assert records[1].link is None
    assert records[1].tags == []
    assert records[0].model_dump()["price"]["currency"] == "usd"
    assert Book.model_json_schema()["properties"]["author"]["description"] == "Author"
    assert len(Book.identity()) == 64
    assert isinstance(Book.identity(), ys.contracts.ContractIdentity)
    assert len(Book.identity().as_bytes()) == 32


def test_explicit_stages_and_parse_reuse_match_convenience():
    document = ys.Document.html(
        "books",
        """
        <article><b class=author>Ada</b><b class=price>$12.34</b></article>
    """,
    )
    direct = ys.extract(document, Book)
    staged = Book.extract(document.locate(Book.plan()))
    with document.parse() as parsed:
        reused = ys.extract(parsed, Book)
    assert direct.model_dump() == staged.model_dump() == reused.model_dump()
    assert direct.validate().model_dump() == staged.validate().model_dump()


def test_empty_roots_invalid_money_and_excess_scalar_preserve_issues():
    document = ys.Document.html(
        "books",
        """
      <article></article>
      <article><b class=author>A</b><b class=price>$-1.00</b></article>
      <article><b class=author>A</b><b class=author>B</b>
        <b class=price>$1.00</b></article>
      <article><b class=author>C</b><b class=price>$2.00</b></article>
    """,
    )
    extracted = ys.extract(document, Book)
    assert len(extracted.candidates) == 4
    assert cast(Any, extracted.candidates[0]).author.is_absent
    outcome = extracted.validate()
    assert len(outcome.records) == 1
    assert len(outcome.issues) == 3
    assert outcome.issues[0].fields[0].kind.kind == "missing_required"
    assert outcome.issues[1].fields[0].kind.code == "negative_money"
    assert outcome.issues[2].fields[0].kind.kind == "excess_candidates"
    assert outcome.issues[2].fields[0].kind.observed == 2
    with pytest.raises(ContractIssues) as error:
        outcome.require_all()
    assert error.value.detail["kind"]


def test_no_match_is_empty_but_indeterminate_and_failure_are_errors():
    no_match = ys.extract(ys.Document.html("empty", "<p>none</p>"), Book).validate()
    assert no_match.require_all() == []
    assert no_match.to_archived().status == "no_match"
    outcome = Book.extract(
        _read(
            json.dumps(
                {
                    "status": "indeterminate",
                    "document_id": "book",
                    "completeness": {"status": "unknown", "reason_code": "lost"},
                    "reason_code": "lost",
                }
            )
        )
    ).validate()
    assert outcome.status == "indeterminate"
    assert outcome.to_archived().status == "indeterminate"
    with pytest.raises(ContractIssues):
        outcome.require_all()
    failed = Book.extract(
        _read(
            json.dumps(
                {
                    "status": "failed",
                    "failure": {"kind": "invalid_plan", "code": "bad"},
                }
            )
        )
    ).validate()
    assert failed.status == "locate_failed"
    assert failed.to_archived().status == "locate_failed"
    with pytest.raises(ContractIssues):
        failed.require_all()


def test_contract_outcome_to_archived_preserves_portable_values_and_evidence():
    document = ys.Document.html(
        "books",
        """
        <article><b class=author>Ada</b><b class=price>$12.34</b>
          <a href=/ada></a><i class=tag>rust</i></article>
        <article><b class=author>Grace</b><b class=price>$0.00</b></article>
        """,
    )
    outcome = ys.extract(document, Book).validate()
    archived = outcome.to_archived()
    assert isinstance(archived, ys.contracts.ArchivedContractOutcome)
    assert archived.status == "evaluated"
    assert len(archived.records) == 2
    second = archived.model_dump()["records"][1]
    assert [field["id"] for field in second["fields"]] == [
        "author",
        "price",
        "link",
        "tags",
    ]
    assert second["fields"][1]["value"] == {
        "cardinality": "exactly_one",
        "value": {"type": "money_usd", "minor_units": 0},
    }
    assert second["fields"][2]["value"] == {
        "cardinality": "zero_or_one",
        "value": None,
    }
    assert second["fields"][3]["value"] == {"cardinality": "many", "values": []}
    assert second["evidence"][2] == {"id": "link", "evidence": []}
    assert "Grace" not in repr(archived.view)
    assert "Grace" in archived.model_dump_json()
    with pytest.raises(AttributeError, match="read-only"):
        cast(Any, archived).status = "no_match"


def test_partial_evidence_and_optional_bad_conversion_are_not_defaults():
    document = ys.Document.html(
        "books",
        """
        <article><b class=author>Ada</b><b class=price>$12.34</b></article>
    """,
    )
    wire = document.locate(Book.plan()).model_dump(mode="json", exclude_none=True)
    wire["result"]["findings"][0]["completeness"] = {
        "status": "partial",
        "reason_code": "lost",
        "lost_items": 1,
    }
    outcome = Book.extract(_read(json.dumps(wire))).validate()
    assert outcome.issues[0].fields[0].kind.kind == "incomplete_evidence"
    with pytest.raises(ContractIssues):
        outcome.require_all()

    class Price(ys.Contract):
        price: ys.Money | None = ys.Field("Price", locator=ys.css("b"), default=None)

    outcome = ys.extract(ys.Document.html("bad", "<b>free</b>"), Price).validate()
    assert outcome.issues[0].fields[0].kind.kind == "conversion_failed"
    with pytest.raises(ContractIssues):
        outcome.require_all()


def test_unpinned_contract_and_semantic_identity_exclude_selectors_descriptions():
    class Manual(ys.Contract):
        contract_id = "book"
        author: str = ys.Field("Author")

    class Pinned(ys.Contract):
        contract_id = "book"
        author: str = ys.Field("Changed description", locator=ys.css("b"))

    assert Manual.identity() == Pinned.identity()
    with pytest.raises(ys._native.ContractError, match="no pinned"):
        Manual.plan()
    located = ys.Document.html("manual", "<b>Ada</b>").locate(Pinned.plan())
    assert Manual.extract(located).validate().require_all()[0].author == "Ada"


def test_unsupported_annotation_and_partial_pins_fail_explicitly():
    class Unsupported(ys.Contract):
        count: int = ys.Field("Count", locator=ys.css("b"))

    with pytest.raises(ys._native.ContractError, match="support str and Money"):
        Unsupported.contract_schema()

    class Partial(ys.Contract):
        author: str = ys.Field("Author", locator=ys.css("b"))
        title: str = ys.Field("Title")

    with pytest.raises(ys._native.ContractError, match="pin all"):
        Partial.contract_schema()
    with pytest.raises((ys._native.ContractError, ValidationError)):
        ys.Money(minor_units=-1)
    with pytest.raises((ys._native.ContractError, ValidationError)):
        ys.Money(minor_units=2**63)
    with pytest.raises((ys._native.ContractError, ValidationError)):
        ys.Money(minor_units=1).model_copy(update={"minor_units": -1})


def test_contract_rejects_python_field_processing_metadata_before_compile():
    class AnnotatedValidation(ys.Contract):
        name: typing.Annotated[str, AfterValidator(str.strip)] = ys.Field("Name")

    with pytest.raises(ys._native.ContractError, match="processing metadata"):
        AnnotatedValidation.contract_schema()

    class FieldConstraint(ys.Contract):
        name: str = ys.Field("Name", min_length=1)

    with pytest.raises(ys._native.ContractError, match="processing metadata"):
        FieldConstraint.contract_schema()

    class DocumentationMetadata(ys.Contract):
        name: typing.Annotated[str, Doc("A human-readable name.")] = ys.Field("Name")

    assert len(DocumentationMetadata.contract_schema().fields) == 1


def test_explicit_budgets_preserve_extraction_and_validation_rejections():
    from yosoi.contracts import ExtractionLimits, ValidationLimits

    document = ys.Document.html(
        "books",
        """
        <article><b class=author>Ada</b><b class=price>$12.34</b></article>
    """,
    )
    located = document.locate(Book.plan())
    rejected = Book.extract(located, limits=ExtractionLimits.uniform(0))
    assert rejected.status == "rejected"
    assert rejected.failure is not None
    assert rejected.failure.kind == "limit_exceeded"
    assert rejected.validate().status == "extraction_rejected"
    assert rejected.validate().to_archived().status == "extraction_rejected"
    outcome = Book.extract(located).validate(limits=ValidationLimits(max_records=0))
    assert outcome.status == "validation_rejected"
    assert outcome.failure is not None
    assert outcome.failure.kind == "record_limit_exceeded"
    archived = outcome.to_archived()
    assert archived.failure is not None
    assert archived.failure.kind == "record_limit_exceeded"
    with pytest.raises(ContractIssues):
        outcome.require_all()


def test_custom_field_ids_map_schema_plan_candidate_and_record_names() -> None:
    class ExternalIds(ys.Contract):
        """External field names are stable independently of Python attributes."""

        contract_id = "external-ids"
        contract_description = "Stable field IDs"
        root = ys.css("article")
        headline: str = ys.Field("Headline", id="title", locator=ys.css("h2"))
        labels: list[str] = ys.Field("Labels", id="tags", locator=ys.css(".tag"))

    class RenamedAttributes(ys.Contract):
        """The same Rust schema may use different Python attribute names."""

        contract_id = "external-ids"
        contract_description = "Stable field IDs"
        root = ys.css("article")
        title_value: str = ys.Field("Headline", id="title", locator=ys.css("h2"))
        tag_values: list[str] = ys.Field("Labels", id="tags", locator=ys.css(".tag"))

    schema = ExternalIds.contract_schema()
    assert [field.id for field in schema.fields] == ["title", "tags"]
    assert ExternalIds.identity() == RenamedAttributes.identity()
    compiled = cast(Any, ExternalIds.plan().compiled())
    assert [output["id"] for output in compiled["outputs"]] == ["title", "tags"]

    document = ys.Document.html(
        "external-ids",
        "<article><h2>Ada</h2><i class='tag'>rust</i></article>"
        "<article><i class='tag'>python</i></article>",
    )
    extracted = ys.extract(document, ExternalIds)
    first_candidate = cast(Any, extracted.candidates[0])
    assert first_candidate.headline.field_id == "title"
    assert first_candidate.headline.values[0].value == "Ada"
    outcome = extracted.validate()
    assert outcome.records[0].value.headline == "Ada"
    assert outcome.records[0].value.labels == ["rust"]
    assert outcome.issues[0].fields[0].field == "title"
    with pytest.raises(ContractIssues):
        outcome.require_all()


@pytest.mark.parametrize(
    "values",
    [
        {
            "id": "",
            "description": "name",
            "cardinality": "exactly_one",
            "value_type": "string",
        },
        {
            "id": "name",
            "description": "",
            "cardinality": "exactly_one",
            "value_type": "string",
        },
        {
            "id": "name",
            "description": "name",
            "cardinality": "exactly_one",
            "value_type": "",
        },
    ],
)
def test_standalone_field_schema_uses_rust_validation(values: dict[str, str]) -> None:
    with pytest.raises((ys._native.ContractError, ValidationError)):
        ys.contracts.FieldSchema.model_validate(values)


def test_untyped_list_and_python_processing_hooks_are_rejected() -> None:
    class BareList(ys.Contract):
        values: list = ys.Field("Values")

    with pytest.raises(ys._native.ContractError, match="list fields require"):
        BareList.contract_schema()
    with pytest.raises(ys._native.ContractError, match="list fields require"):
        ys.contracts._field_type(typing.List)  # noqa: UP006

    class WithValidator(ys.Contract):
        value: str = ys.Field("Value")

        @field_validator("value")
        @classmethod
        def normalize(cls, value: str) -> str:
            return value.strip()

    class WithSerializer(ys.Contract):
        value: str = ys.Field("Value")

        @field_serializer("value")
        def serialize_value(self, value: str) -> str:
            return value.strip()

    class WithComputedField(ys.Contract):
        value: str = ys.Field("Value")

        @computed_field
        @property
        def normalized(self) -> str:
            return self.value.strip()

    for contract in (WithValidator, WithSerializer, WithComputedField):
        with pytest.raises(ys._native.ContractError, match="processing hooks"):
            contract.contract_schema()
