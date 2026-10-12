"""Black-box acceptance coverage for Python-native Contracts."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

import pytest
from pydantic import (
    AfterValidator,
    AliasPath,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    TypeAdapter,
    ValidationError,
    computed_field,
    field_serializer,
    field_validator,
    model_validator,
)

import yosoi as ys
from yosoi.contracts import (
    ContractIssues,
    ExtractionLimits,
    ExtractionPolicy,
    ValidationLimits,
)
from yosoi.outcomes import LocateOutcome


def test_full_pydantic_lifecycle_aliases_defaults_and_attribute_text() -> None:
    seen: dict[str, list[Any]] = {
        "title_before": [],
        "title_after": [],
        "field_title_before": [],
        "url_before": [],
        "money_before": [],
        "money_after": [],
        "model_before": [],
        "model_after": [],
    }
    default_calls = 0

    def parse_title(value: Any) -> str:
        seen["title_before"].append(value)
        return str(value).removeprefix("name:").strip()

    def title_case(value: str) -> str:
        seen["title_after"].append(value)
        return value.title()

    def parse_url(value: Any) -> str:
        seen["url_before"].append(value)
        return str(value).lower()

    def make_default_note() -> str:
        nonlocal default_calls
        default_calls += 1
        return "from factory"

    class PurchaseMoney(BaseModel):
        amount: Decimal
        currency: Literal["USD"]

        @model_validator(mode="before")
        @classmethod
        def parse_text(cls, value: Any) -> Any:
            seen["money_before"].append(value)
            if isinstance(value, str) and value.startswith("$"):
                return {"amount": value[1:], "currency": "USD"}
            return value

        @field_validator("amount", mode="after")
        @classmethod
        def retain_decimal(cls, value: Decimal) -> Decimal:
            seen["money_after"].append(value)
            return value

    class Product(ys.Contract):
        model_config = ConfigDict(
            validate_by_alias=True,
            validate_by_name=False,
            serialize_by_alias=True,
            str_strip_whitespace=True,
        )

        headline: Annotated[
            str,
            BeforeValidator(parse_title),
            AfterValidator(title_case),
        ] = ys.Field(
            "Product headline",
            id="headline-id",
            locator=ys.css("h1"),
            validation_alias="incoming-headline",
            serialization_alias="headline-output",
            min_length=3,
        )
        url: Annotated[str, BeforeValidator(parse_url)] = ys.Field(
            "Product URL",
            locator=ys.css("a").attribute("href"),
        )
        price: PurchaseMoney = ys.Field(
            "Custom money model", locator=ys.css(".price")
        )
        release_date: date = ys.Field("Release date", locator=ys.css("time"))
        note: str = ys.Field(
            "Optional generated note",
            locator=ys.css(".note"),
            default_factory=make_default_note,
        )

        @field_validator("headline", mode="before")
        @classmethod
        def observe_headline_input(cls, value: Any) -> Any:
            seen["field_title_before"].append(value)
            return value

        @model_validator(mode="before")
        @classmethod
        def observe_model_input(cls, value: Any) -> Any:
            seen["model_before"].append(value)
            return value

        @model_validator(mode="after")
        def require_consistent_money(self) -> Product:
            seen["model_after"].append(self.price.amount)
            if self.price.amount <= 0:
                raise ValueError("price must be positive")
            return self

        @field_serializer("headline")
        def serialize_headline(self, value: str) -> str:
            return value.upper()

        @computed_field(alias="summary")
        @property
        def display_summary(self) -> str:
            return f"{self.headline} {self.release_date.isoformat()}"

    document = ys.Document.html(
        "pydantic-product",
        "<h1>name: ada widget</h1><a href='/SHOP/42'>view</a>"
        "<span class='price'>$12.50</span><time>2026-10-12</time>",
    )

    record = Product.extract(document)[0]
    assert isinstance(record, Product)
    assert record.headline == "Ada Widget"
    assert record.url == "/shop/42"
    assert record.price.model_dump() == {
        "amount": Decimal("12.50"),
        "currency": "USD",
    }
    assert record.release_date == date(2026, 10, 12)
    assert record.note == "from factory"
    assert default_calls == 1
    assert seen["title_before"] == ["name: ada widget"]
    assert seen["title_after"] == ["ada widget"]
    assert seen["field_title_before"] == ["name: ada widget"]
    assert seen["url_before"] == ["/SHOP/42"]
    assert seen["money_before"] == ["$12.50"]
    assert seen["money_after"] == [Decimal("12.50")]
    assert len(seen["model_before"]) == 1
    assert seen["model_after"] == [Decimal("12.50")]
    assert record.model_dump(mode="json") == {
        "headline-output": "ADA WIDGET",
        "url": "/shop/42",
        "price": {"amount": "12.50", "currency": "USD"},
        "release_date": "2026-10-12",
        "note": "from factory",
        "summary": "Ada Widget 2026-10-12",
    }

    report = ys.extract_report(document, Product)
    assert report.records[0].value == record
    assert default_calls == 2


def test_json_projection_preserves_numbers_for_annotated_validator() -> None:
    observed: list[Any] = []

    def see_number(value: Any) -> Any:
        observed.append(value)
        return value

    class JsonProduct(ys.Contract):
        amount: Annotated[Decimal, BeforeValidator(see_number)] = ys.Field(
            "Native JSON amount",
            locator=ys.json_pointer("/amount").value(),
        )
        published: date = ys.Field(
            "JSON date", locator=ys.json_pointer("/published").value()
        )

    document = ys.Document.from_json(
        "json-product", '{"amount":42,"published":"2026-10-12"}'
    )
    [record] = ys.extract(document, JsonProduct)

    assert observed == [42]
    assert type(observed[0]) is int
    assert record.amount == Decimal("42")
    assert record.published == date(2026, 10, 12)


def test_alias_path_config_and_preflight_budget_behavior() -> None:
    class NegativePath(ys.Contract):
        model_config = ConfigDict(validate_by_alias=True, validate_by_name=False)

        sku: str = ys.Field(
            "SKU",
            locator=ys.css(".sku"),
            validation_alias=AliasPath("rows", -1, "sku"),
        )

    class AliasDisabled(ys.Contract):
        model_config = ConfigDict(validate_by_alias=False, validate_by_name=True)

        sku: str = ys.Field(
            "SKU", locator=ys.css(".sku"), alias="wire-sku"
        )

    document = ys.Document.html("aliased", "<b class='sku'>tea-42</b>")
    assert NegativePath.extract(document)[0].sku == "tea-42"
    assert AliasDisabled.extract(document)[0].sku == "tea-42"

    validation_calls = 0

    class LargePath(ys.Contract):
        sku: str = ys.Field(
            "SKU",
            locator=ys.css(".sku"),
            validation_alias=AliasPath("rows", 10_000, "sku"),
        )

        @field_validator("sku")
        @classmethod
        def count_validation(cls, value: str) -> str:
            nonlocal validation_calls
            validation_calls += 1
            return value

    limited = LargePath.extract_report(
        document,
        policy=ExtractionPolicy(
            validation_limits=ValidationLimits(max_conversions=1)
        ),
    )
    assert limited.status == "validation_rejected"
    assert limited.failure is not None
    assert limited.failure.limit == "conversions"
    assert limited.failure.observed == 10_002
    assert validation_calls == 0


def test_class_and_module_extract_match_and_report_rejected_evidence() -> None:
    class Name(ys.Contract):
        root = ys.css("article")
        name: str = ys.Field("Name", locator=ys.css("b"), min_length=2)

    document = ys.Document.html(
        "names", "<article><b>Ada</b></article><article><b>A</b></article>"
    )
    collect = ExtractionPolicy(on_rejected_record="collect")
    class_records = Name.extract(document, policy=collect)
    module_records = ys.extract(document, Name, policy=collect)
    assert class_records == module_records
    assert [record.name for record in class_records] == ["Ada"]

    report = Name.extract_report(document, policy=collect)
    assert len(report.records) == 1
    assert report.records[0].value == class_records[0]
    assert len(report.issues) == 1
    issue = report.issues[0]
    assert issue.kind == "validation_error"
    assert issue.field_ids == ("name",)
    assert issue.errors[0]["type"] == "string_too_short"
    assert issue.errors[0]["loc"] == ("name",)
    assert "input" not in issue.errors[0]
    assert issue.candidate.field("name").evidence[0].value == "A"
    assert (
        issue.evidence[0].coordinate
        == issue.candidate.field("name").evidence[0].coordinate
    )

    with pytest.raises(ValidationError) as class_error:
        Name.extract(document)
    with pytest.raises(ValidationError) as module_error:
        ys.extract(document, Name)
    assert class_error.value.errors(include_input=False, include_url=False) == (
        module_error.value.errors(include_input=False, include_url=False)
    )
    with pytest.raises(ContractIssues):
        report.require_all()


def test_inherited_classmethod_extracts_the_subclass_model() -> None:
    class BaseProduct(ys.Contract):
        root = ys.css("article")
        name: str = ys.Field("Name", locator=ys.css(".name"))

        @classmethod
        def first(cls, document: ys.Document) -> BaseProduct:
            return cls.extract(document)[0]

    class DecoratedProduct(BaseProduct):
        code: int = ys.Field("Code", locator=ys.css(".code"))

    document = ys.Document.html(
        "derived-product",
        "<article><b class='name'>Ada</b><i class='code'>7</i></article>",
    )
    result = DecoratedProduct.first(document)

    assert type(result) is DecoratedProduct
    assert result.name == "Ada"
    assert result.code == 7


def test_optional_many_incomplete_and_minimum_record_policies() -> None:
    class Entry(ys.Contract):
        root = ys.css("article")
        required: str = ys.Field("Required", locator=ys.css(".required"))
        optional: int | None = ys.Field(
            "Optional", locator=ys.css(".optional"), default=None
        )
        tags: list[int] = ys.Field("Tags", locator=ys.css(".tag"))

    document = ys.Document.html(
        "entries",
        "<article><b class='required'>first</b></article>"
        "<article><b class='required'>second</b><i class='optional'>7</i>"
        "<i class='tag'>1</i><i class='tag'>2</i></article>"
        "<article><b class='required'>third</b>"
        "<b class='required'>fourth</b></article>",
    )
    report = Entry.extract_report(
        document, policy=ExtractionPolicy(on_rejected_record="collect")
    )
    assert [record.value.required for record in report.records] == ["first", "second"]
    assert report.records[0].value.optional is None
    assert report.records[0].value.tags == []
    assert report.records[1].value.optional == 7
    assert report.records[1].value.tags == [1, 2]
    assert len(report.issues) == 1
    assert report.issues[0].kind == "excess_candidates"
    assert report.issues[0].field_ids == ("required",)
    assert report.issues[0].observed == 2
    third_values = report.issues[0].candidate.field("required").evidence
    assert [item.value for item in third_values] == [
        "third",
        "fourth",
    ]

    empty = ys.Document.html("empty-entries", "<p>no entries</p>")
    default_empty = ys.extract(empty, Entry)
    assert default_empty == []
    empty_report = Entry.extract_report(
        empty, policy=ExtractionPolicy(minimum_records=1)
    )
    assert empty_report.status == "no_match"
    assert empty_report.records == ()
    assert not empty_report.meets_minimum_records
    with pytest.raises(ContractIssues, match="minimum_records"):
        ys.extract(empty, Entry, policy=ExtractionPolicy(minimum_records=1))

    validator_calls = 0

    class Guarded(ys.Contract):
        value: int = ys.Field("Value", locator=ys.css("b"))

        @field_validator("value")
        @classmethod
        def count_validation(cls, value: int) -> int:
            nonlocal validator_calls
            validator_calls += 1
            return value

    guarded_document = ys.Document.html("partial", "<b>8</b>")
    located = guarded_document.locate(Guarded.plan())
    wire = located.model_dump(mode="json", exclude_none=True, by_alias=True)
    wire["result"]["findings"][0]["completeness"] = {
        "status": "partial",
        "reason_code": "test_loss",
        "lost_items": 1,
    }
    partial = TypeAdapter(LocateOutcome).validate_python(wire)
    incomplete_report = Guarded.assemble(partial).validate()
    assert incomplete_report.status == "indeterminate"
    assert incomplete_report.issues[0].kind == "incomplete_evidence"
    assert incomplete_report.issues[0].evidence[0].completeness.status == "partial"
    assert validator_calls == 0
    collected_incomplete = Guarded.assemble(partial).validate(
        policy=ExtractionPolicy(on_rejected_record="collect")
    )
    with pytest.raises(ContractIssues):
        collected_incomplete.require_all()


def test_validation_budget_rejects_before_user_validator_side_effects() -> None:
    calls = 0

    class Budgeted(ys.Contract):
        root = ys.css("article")
        number: int = ys.Field("Number", locator=ys.css("b"))

        @field_validator("number")
        @classmethod
        def observe_validation(cls, value: int) -> int:
            nonlocal calls
            calls += 1
            return value

    document = ys.Document.html("budgeted", "<article><b>42</b></article>")
    report = Budgeted.extract_report(
        document,
        policy=ExtractionPolicy(
            validation_limits=ValidationLimits(max_conversions=0)
        ),
    )

    assert report.status == "validation_rejected"
    assert report.failure is not None
    assert report.failure.kind == "conversion_limit_exceeded"
    assert report.failure.limit == "conversions"
    assert report.failure.maximum == 0
    assert report.failure.observed == 1
    assert calls == 0

    extraction_report = Budgeted.extract_report(
        document,
        policy=ExtractionPolicy(extraction_limits=ExtractionLimits.uniform(0)),
    )
    assert extraction_report.status == "extraction_rejected"
    assert calls == 0


def test_midrun_issue_budget_does_not_expose_an_accepted_prefix() -> None:
    class BudgetedRows(ys.Contract):
        root = ys.css("article")
        name: str = ys.Field("Name", locator=ys.css("b"), min_length=2)

    document = ys.Document.html(
        "issue-budget",
        "<article><b>Ada</b></article><article><b>A</b></article>",
    )
    report = BudgetedRows.extract_report(
        document,
        policy=ExtractionPolicy(
            on_rejected_record="collect",
            validation_limits=ValidationLimits(max_issues=0),
        ),
    )

    assert report.status == "validation_rejected"
    assert report.failure is not None
    assert report.failure.kind == "issue_limit_exceeded"
    assert report.failure.limit == "issues"
    assert report.failure.observed == 1
    assert report.candidates and len(report.candidates) == 2
    assert report.records == ()
    # A zero-issue budget retains failure facts and raw candidates, not an
    # over-budget diagnostic collection.
    assert report.issues == ()
    assert report.candidates[1].field("name").evidence[0].value == "A"


def test_local_assertion_callback_uses_pydantic_without_browser() -> None:
    validation_calls = 0

    class AssertedProduct(ys.Contract):
        amount: Decimal = ys.Field("Amount", locator=ys.css(".amount"))
        code: str = ys.Field("Code", locator=ys.css(".code"))

        @field_validator("amount", mode="before")
        @classmethod
        def observe_input(cls, value: Any) -> Any:
            nonlocal validation_calls
            validation_calls += 1
            return value

    assertion = ys.assert_all(
        AssertedProduct,
        checks=[
            ys.check(
                "typed-decimal",
                lambda product: isinstance(product.amount, Decimal)
                and product.amount == Decimal("12.50")
                and product.code == "ACME",
            )
        ],
    )
    good_document = ys.Document.html(
        "assertion-good",
        "<b class='amount'>12.50</b><i class='code'>ACME</i>",
    )
    good_located = good_document.locate(AssertedProduct.plan())
    good_wire = assertion._binding(
        good_located.model_dump_json(exclude_none=True, by_alias=True),
        ys.Policy().to_json(),
    )
    good_report = json.loads(good_wire)
    assert good_report["passed"] is True
    assert good_report["checks"][0]["passed"] is True
    assert validation_calls == 1

    bad_document = ys.Document.html(
        "assertion-bad", "<b class='amount'>not-a-number</b>"
    )
    bad_located = bad_document.locate(AssertedProduct.plan())
    bad_report = json.loads(
        assertion._binding(
            bad_located.model_dump_json(exclude_none=True, by_alias=True),
            ys.Policy().to_json(),
        )
    )
    assert bad_report["passed"] is False
    assert bad_report["source_error"] == {"kind": "invalid_contract"}
    assert bad_report["checks"][0]["passed"] is None
    issues = {item["field"]: item for item in bad_report["field_issues"]}
    assert issues["amount"]["kind"] == {"kind": "conversion_failed"}
    assert issues["code"]["kind"] == {"kind": "missing_required"}
    sidecar = next(
        item
        for item in bad_report["extraction_diagnostics"]
        if item["kind"] == "python_validation_errors"
    )
    python_errors = sidecar["validation_errors"][0]["errors"]
    assert sidecar["validation_errors"][0]["fields"] == ["amount", "code"]
    assert {error["type"] for error in python_errors} == {
        "decimal_parsing",
        "missing",
    }
    assert all("input" not in error for error in python_errors)
    assert issues["amount"]["evidence"][0]["value"] == {
        "kind": "text",
        "value": "not-a-number",
    }
    assert issues["code"]["evidence"] == []

    partial_wire = good_located.model_dump(
        mode="json", exclude_none=True, by_alias=True
    )
    partial_wire["result"]["findings"][0]["completeness"] = {
        "status": "partial",
        "reason_code": "assertion_loss",
        "lost_items": 1,
    }
    partial_located = TypeAdapter(LocateOutcome).validate_python(partial_wire)
    partial_report = json.loads(
        assertion._binding(
            partial_located.model_dump_json(exclude_none=True, by_alias=True),
            ys.Policy().to_json(),
        )
    )
    assert partial_report["source_error"] == {"kind": "invalid_contract"}
    assert partial_report["field_issues"][0]["kind"] == {
        "kind": "incomplete_evidence"
    }


def test_local_assertion_reports_each_excess_field_count() -> None:
    class MultiOverflow(ys.Contract):
        root = ys.css("article")
        first: str = ys.Field("First", locator=ys.css(".first"))
        second: str = ys.Field("Second", locator=ys.css(".second"))

    assertion = ys.assert_all(
        MultiOverflow,
        checks=[ys.check("unused-on-invalid-source", lambda _: True)],
    )
    document = ys.Document.html(
        "multiple-excess-fields",
        "<article><b class='first'>a</b><b class='first'>b</b>"
        "<i class='second'>x</i><i class='second'>y</i>"
        "<i class='second'>z</i></article>",
    )
    located = document.locate(MultiOverflow.plan())
    report = json.loads(
        assertion._binding(
            located.model_dump_json(exclude_none=True, by_alias=True),
            ys.Policy().to_json(),
        )
    )
    issues = {item["field"]: item for item in report["field_issues"]}

    assert issues["first"]["kind"] == {
        "kind": "excess_candidates",
        "observed": 2,
    }
    assert issues["second"]["kind"] == {
        "kind": "excess_candidates",
        "observed": 3,
    }
