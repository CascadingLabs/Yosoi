"""Pydantic-owned validation over bounded native Contract candidates."""

from __future__ import annotations

from typing import Annotated, Any, cast

import pytest
from pydantic import (
    AfterValidator,
    BaseModel,
    ValidationError,
    computed_field,
    field_serializer,
    field_validator,
    model_validator,
)

import yosoi as ys


class Product(ys.Contract):
    """One catalog item with Pydantic-owned business validation."""

    root = ys.css("article")
    name: Annotated[str, AfterValidator(str.strip)] = ys.Field(
        "Product name", id="product_name", locator=ys.css(".name"), min_length=2
    )
    sku: str = ys.Field(
        "Stock keeping unit",
        id="sku_id",
        locator=ys.css(".sku"),
        alias="productSku",
    )
    price: ys.Money = ys.Field("Price", locator=ys.css(".price"))
    quantity: int = ys.Field(
        "Available quantity", id="quantity_id", locator=ys.css(".quantity"), ge=1
    )
    labels: list[int] = ys.Field("Numeric labels", locator=ys.css(".label"))
    note: str | None = ys.Field("Optional note", locator=ys.css(".note"), default=None)

    @field_validator("name", mode="before")
    @classmethod
    def _trim_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _valid_price_quantity(self) -> Product:
        if self.quantity > 100_000:
            raise ValueError("quantity exceeds the catalog limit")
        return self

    @field_serializer("price")
    def _serialize_price(self, value: ys.Money) -> str:
        return str(value)

    @computed_field
    @property
    def summary(self) -> str:
        return f"{self.name}: {self.price}"


def _document() -> ys.Document:
    return ys.Document.html(
        "catalog",
        """
        <article>
          <b class="name">  Tea  </b><b class="sku">tea-1</b>
          <b class="price">$29.00</b><b class="quantity">3</b>
          <i class="label">2</i><i class="label">5</i>
        </article>
        <article>
          <b class="name">Coffee</b><b class="sku">coffee-1</b>
          <b class="price">$7.25</b><b class="quantity">unavailable</b>
        </article>
        """,
    )


def test_contract_is_mutable_pydantic_and_money_accepts_text() -> None:
    class CartLine(BaseModel):
        price: ys.Money

    product = Product(
        name="  Tea  ",
        price=cast(Any, "$29.00"),
        quantity="3",
        labels=["2", "5"],
        **cast(Any, {"productSku": "tea-1"}),
    )
    assert isinstance(product, BaseModel)
    assert CartLine(price=cast(Any, "$29.00")).price.minor_units == 2900
    assert product.name == "Tea"
    assert product.labels == [2, 5]
    assert product.model_dump()["productSku"] == "tea-1"
    assert product.model_dump()["price"] == "$29.00"
    assert product.model_dump()["summary"] == "Tea: $29.00"

    product.name = "Herbal tea"
    product.labels.append(8)
    assert product.name == "Herbal tea"
    assert product.labels == [2, 5, 8]


def test_extract_report_keeps_accepted_models_errors_and_candidate_evidence() -> None:
    policy = ys.ExtractionPolicy(on_rejected_record="collect")
    report = Product.extract_report(_document(), policy=policy)

    assert report.status == "evaluated"
    assert report.completeness is not None
    assert report.completeness.status == "complete"
    assert len(report.candidates) == 2
    assert len(report.records) == 1
    assert report.records[0].value.name == "Tea"
    original_name = report.records[0].candidate.field("product_name").values[0].value
    assert original_name == "Tea"
    assert report.issues[0].kind == "validation_error"
    assert report.issues[0].field_ids == ("quantity_id",)
    assert report.issues[0].candidate.field("quantity_id").values[0].value == (
        "unavailable"
    )
    assert report.issues[0].errors
    assert all("input" not in detail for detail in report.issues[0].errors)
    assert "unavailable" not in repr(report.issues[0])
    assert report.accepted_records[0].price.minor_units == 2900

    assert ys.extract(_document(), Product, policy=policy)[0].name == "Tea"
    with pytest.raises(ValidationError):
        Product.extract(_document())


def test_raw_json_projection_validates_nested_pydantic_models() -> None:
    class Address(BaseModel):
        city: str
        postal_code: int

    class Listing(ys.Contract):
        address: Address = ys.Field(
            "Shipping address",
            locator=ys.json_pointer("/address").value(),
        )

    document = ys.Document.from_json(
        "listing", b'{"address":{"city":"Boston","postal_code":"02108"}}'
    )
    report = Listing.extract_report(document)
    assert report.status == "evaluated"
    assert report.records[0].value.address.city == "Boston"
    assert report.records[0].value.address.postal_code == 2108


def test_validation_limits_preflight_and_minimum_record_acceptance() -> None:
    calls = 0

    class Counted(ys.Contract):
        value: int = ys.Field("Value", locator=ys.css("b"))

        @field_validator("value", mode="before")
        @classmethod
        def _count_validation(cls, value: object) -> object:
            nonlocal calls
            calls += 1
            return value

    document = ys.Document.html("bounded", "<b>3</b>")
    report = Counted.extract_report(
        document,
        policy=ys.ExtractionPolicy(
            validation_limits=ys.contracts.ValidationLimits(max_records=0)
        ),
    )
    assert report.status == "validation_rejected"
    assert isinstance(report.failure, ys.contracts.TerminalFailure)
    assert report.failure.limit == "records"
    assert calls == 0

    empty = Counted.extract_report(
        ys.Document.html("empty", "<p>none</p>"),
        policy=ys.ExtractionPolicy(minimum_records=1),
    )
    assert empty.status == "no_match"
    assert empty.meets_minimum_records is False
    with pytest.raises(ys.contracts.ContractIssues):
        Counted.extract(
            ys.Document.html("empty-again", "<p>none</p>"),
            policy=ys.ExtractionPolicy(minimum_records=1),
        )
