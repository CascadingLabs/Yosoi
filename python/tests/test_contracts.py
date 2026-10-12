"""Pydantic Contract validation over Rust-located evidence."""

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
    extracted = Book.assemble(document.locate(Book.plan()))
    assert extracted.status == "candidates"
    assert len(extracted.candidates) == 2
    assert isinstance(extracted.candidates, tuple)
    candidate = extracted.candidates[0]
    candidate_author = cast(Any, candidate).author
    assert isinstance(candidate_author.evidence, tuple)
    assert candidate_author.evidence[0].value == "Ada"
    assert candidate_author.values[0].value == "Ada"
    assert candidate.region is not None
    assert candidate.region.region_id == "Book"
    assert "Ada" not in repr(candidate)
    assert "Ada" not in repr(candidate_author)
    outcome = extracted.validate()
    assert outcome.status == "evaluated"
    assert isinstance(outcome.records, tuple)
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
    records[0].tags.append("updated")
    assert records[0].tags == ["a", "b", "updated"]
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
    staged = Book.assemble(document.locate(Book.plan()))
    with document.parse() as parsed:
        reused = ys.extract(parsed, Book)
    assert direct == staged.validate().require_all() == reused


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
    extracted = ys.extract_report(document, Book)
    assert len(extracted.candidates) == 4
    assert cast(Any, extracted.candidates[0]).author.is_absent
    outcome = extracted
    assert len(outcome.records) == 1
    assert len(outcome.issues) == 3
    assert outcome.records[0].value.author == "C"
    assert [issue.field_ids for issue in outcome.issues] == [
        ("author", "price"),
        ("price",),
        ("author",),
    ]
    assert all(isinstance(issue.error, ValidationError) for issue in outcome.issues)
    assert [issue.kind for issue in outcome.issues] == [
        "missing_required",
        "validation_error",
        "excess_candidates",
    ]
    assert all(issue.errors for issue in outcome.issues)
    with pytest.raises(ContractIssues):
        outcome.require_all()


def test_no_match_is_empty_but_indeterminate_and_failure_are_errors():
    empty = ys.Document.html("empty", "<p>none</p>")
    assert ys.extract(empty, Book) == []
    no_match = ys.extract_report(empty, Book)
    assert no_match.status == "no_match"
    assert no_match.require_all() == []
    outcome = Book.assemble(
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
    with pytest.raises(ContractIssues):
        outcome.require_all()
    failed = Book.assemble(
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
    with pytest.raises(ContractIssues):
        failed.require_all()


def test_runtime_contract_archive_preserves_portable_values_and_evidence():
    document = ys.Document.html(
        "books",
        """
        <article><b class=author>Ada</b><b class=price>$12.34</b>
          <a href=/ada></a><i class=tag>rust</i></article>
        <article><b class=author>Grace</b><b class=price>$0.00</b></article>
        """,
    )
    native_contract = ys.contracts.RuntimeContract.new(Book.contract_schema())
    outcome = native_contract.extract(document.locate(Book.plan())).validate()
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


def test_partial_native_evidence_and_bad_pydantic_values_are_not_defaults():
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
    native_contract = ys.contracts.RuntimeContract.new(Book.contract_schema())
    outcome = native_contract.extract(_read(json.dumps(wire))).validate()
    assert outcome.issues[0].fields[0].kind.kind == "incomplete_evidence"
    with pytest.raises(ContractIssues):
        outcome.require_all()

    class Price(ys.Contract):
        price: ys.Money | None = ys.Field("Price", locator=ys.css("b"), default=None)

    outcome = ys.extract_report(ys.Document.html("bad", "<b>free</b>"), Price)
    assert outcome.records == ()
    assert outcome.issues[0].field_ids == ("price",)
    assert outcome.issues[0].kind == "validation_error"
    assert outcome.issues[0].errors
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
    assert Manual.assemble(located).validate().require_all()[0].author == "Ada"


def test_contract_coerces_arbitrary_pydantic_field_types_from_text():
    class TypedValues(ys.Contract):
        count: int = ys.Field("Count", locator=ys.css("b"))
        values: list[int] = ys.Field("Values", locator=ys.css(".value"))

    document = ys.Document.html(
        "typed-values",
        "<b>42</b><i class='value'>3</i><i class='value'>8</i>",
    )
    [record] = ys.extract(document, TypedValues)
    assert record.count == 42
    assert record.values == [3, 8]

    with pytest.raises((ys._native.ContractError, ValidationError)):
        ys.Money(minor_units=-1)
    with pytest.raises((ys._native.ContractError, ValidationError)):
        ys.Money(minor_units=2**63)
    with pytest.raises((ys._native.ContractError, ValidationError)):
        ys.Money(minor_units=1).model_copy(update={"minor_units": -1})


def test_contract_uses_pydantic_validators_serializers_and_computed_fields():
    class Hooked(ys.Contract):
        name: typing.Annotated[str, AfterValidator(str.strip)] = ys.Field(
            "Name", locator=ys.css("b"), min_length=2
        )

        @field_validator("name")
        @classmethod
        def title_case(cls, value: str) -> str:
            return value.title()

        @field_serializer("name")
        def serialize_name(self, value: str) -> str:
            return value.upper()

        @computed_field
        @property
        def display_name(self) -> str:
            return f"Book: {self.name}"

    assert len(Hooked.contract_schema().fields) == 1
    document = ys.Document.html("hooks", "<b> ada </b>")
    [record] = ys.extract(document, Hooked)
    assert record.name == "Ada"
    assert record.display_name == "Book: Ada"
    assert record.model_dump() == {
        "name": "ADA",
        "display_name": "Book: Ada",
    }


def test_rejected_candidate_policy_collects_only_valid_python_models():
    class ShortName(ys.Contract):
        root = ys.css("article")
        name: str = ys.Field("Name", locator=ys.css("b"), min_length=2)

    document = ys.Document.html(
        "names", "<article><b>Ada</b></article><article><b>A</b></article>"
    )
    with pytest.raises(ValidationError):
        ys.extract(document, ShortName)

    policy = ys.ExtractionPolicy(on_rejected_record="collect")
    records = ys.extract(document, ShortName, policy=policy)
    assert [record.name for record in records] == ["Ada"]

    report = ys.extract_report(document, ShortName)
    assert [record.value.name for record in report.records] == ["Ada"]
    assert report.issues[0].kind == "validation_error"
    assert report.issues[0].field_ids == ("name",)
    assert report.issues[0].errors[0]["type"] == "string_too_short"
    with pytest.raises(ContractIssues):
        report.require_all()

    empty = ys.Document.html("empty", "<p>none</p>")
    with pytest.raises(ContractIssues):
        ys.extract(empty, ShortName, policy=ys.ExtractionPolicy(minimum_records=1))


def test_explicit_budgets_preserve_extraction_and_validation_rejections():
    from yosoi.contracts import ExtractionLimits, ExtractionPolicy, ValidationLimits

    document = ys.Document.html(
        "books",
        """
        <article><b class=author>Ada</b><b class=price>$12.34</b></article>
    """,
    )
    rejected = ys.extract_report(
        document,
        Book,
        policy=ExtractionPolicy(extraction_limits=ExtractionLimits.uniform(0)),
    )
    assert rejected.status == "extraction_rejected"
    assert rejected.failure is not None
    assert rejected.failure.kind == "limit_exceeded"
    outcome = ys.extract_report(
        document,
        Book,
        policy=ExtractionPolicy(validation_limits=ValidationLimits(max_records=0)),
    )
    assert outcome.status == "validation_rejected"
    assert outcome.failure is not None
    assert outcome.failure.kind == "record_limit_exceeded"
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
    extracted = ExternalIds.assemble(document.locate(ExternalIds.plan()))
    first_candidate = cast(Any, extracted.candidates[0])
    assert first_candidate.headline.field_id == "title"
    assert first_candidate.headline.values[0].value == "Ada"
    outcome = extracted.validate()
    assert outcome.records[0].value.headline == "Ada"
    assert outcome.records[0].value.labels == ["rust"]
    assert outcome.issues[0].field_ids == ("title",)
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
