---
title: Python Contracts
description: Extract validated Pydantic models, including custom types and field validators.
order: 3
---

# Python Contracts

Subclass `ys.Contract` to describe a record and use `ys.Field` for extraction bindings. Rust locates and groups the original evidence. Python constructs the resulting records through Pydantic, including your constraints, defaults, field validators and model validators.

## Example: validated records

`Book.extract(book_document)` returns validated Book instances. `ys.extract(document, Book)` is the equivalent functional entry point. Neither requires a separate validation call.

`ys.Field` accepts ordinary Pydantic field options alongside a locator, description and optional output ID. A bare query uses text projection.

```python
from pydantic import field_validator
import yosoi as ys

class Book(ys.Contract):
    """A book offered for sale."""

    root = ys.css("article")
    author: str = ys.Field("Author", locator=ys.css(".author"), min_length=1)
    price: str = ys.Field("Price text", locator=ys.css(".price"))
    subtitle: str | None = ys.Field("Optional subtitle", locator=ys.css(".subtitle"), default=None)
    tags: list[str] = ys.Field("Book tags", locator=ys.css(".tag"))

    @field_validator("author", mode="before")
    @classmethod
    def clean_author(cls, value: str) -> str:
        return value.strip()

book_document = ys.Document.html(
    "books",
    "<article><b class='author'> Ada </b><b class='price'>$12.34</b>"
    "<i class='tag'>computing</i></article>",
)
# callout: The class method and ys.extract(book_document, Book) share the same Pydantic validation path.
books = Book.extract(book_document)
for book in books:
    print(book.author, book.price, book.tags)
```

The name validator trims the extracted text before Pydantic checks its length. The price remains text, the absent subtitle becomes None, and the tags remain an ordered list. These selectors are explicit bindings for the supplied HTML; descriptions alone do not discover elements.

## Custom field types

A Contract field can use a Pydantic model, an Annotated type with validators, or a custom class with Pydantic integration. The type does not need registration in Rust. Parsing and business validation follow Pydantic's normal model construction.

```python
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_validator
import yosoi as ys

class CustomMoney(BaseModel):
    amount: Decimal = Field(ge=0)
    currency: Literal["USD"]

    # callout: The custom type receives the original projected value before type validation.
    @model_validator(mode="before")
    @classmethod
    def parse_price(cls, value):
        if isinstance(value, str):
            if not value.startswith("$"):
                raise ValueError("Expected a USD price")
            return {"amount": value[1:], "currency": "USD"}
        return value

class Product(ys.Contract):
    """A product with an application-defined price type."""

    name: str = ys.Field("Product name", locator=ys.css("h1"), min_length=1)
    price: CustomMoney = ys.Field("Advertised price", locator=ys.css(".price"))

    @field_validator("price", mode="after")
    @classmethod
    def require_positive_price(cls, value: CustomMoney) -> CustomMoney:
        if value.amount <= 0:
            raise ValueError("Product price must be positive")
        return value

document = ys.Document.html("product", "<h1>Desk lamp</h1><b class='price'>$29.00</b>")
for product in Product.extract(document):
    print(product.name, product.price.amount, product.price.currency)
```

CustomMoney interprets the extracted text. Product's price validator then adds an application rule. The same CustomMoney type can be used in an ordinary Pydantic model outside Yosoi. This parses one extracted value into a structured object; it does not automatically locate separate nested fields.

## Cardinality and defaults

A scalar field accepts one finding and a list field collects ordered findings. A nullable annotation permits None; add `default=None` when complete absence should produce None instead of a missing-field error. Multiple findings for a scalar remain an issue. Incomplete evidence cannot become a complete absent value or an empty successful list.

Pydantic defaults and default factories apply when an absent field has a declared default. Constraints, aliases, custom validators, serializers and model configuration are handled by Pydantic. Original findings remain separate from transformed model values.

Pin every field or leave every field unpinned. A class-level root selects repeated records and scopes each field locator to its row.

## Acceptance policy

Ordinary extraction raises a Pydantic `ValidationError` for a single model rejection, or `ys.contracts.ContractIssues` for combined or terminal failures. A single scalar-cardinality rejection can also surface as a Pydantic validation error. A complete no-match returns an empty list unless a minimum record count is requested.

```python
# callout: An empty complete result is allowed by default. This policy requires at least one accepted record.
policy = ys.ExtractionPolicy(minimum_records=1)
books = Book.extract(book_document, policy=policy)
```

To use accepted records while tolerating rejected candidates, set `on_rejected_record="collect"`. Every returned record still passes Pydantic validation. Use a report when you need the rejected evidence and detailed errors too.

`ys.ExtractionPolicy` controls result acceptance and extraction/validation budgets. `ys.Policy` controls document processing and locator budgets; apply it through `document.bind(policy)` before extraction.

## Inspect evidence and errors

```python
# callout: Reports retain original findings even when validators transform the model values.
report = Book.extract_report(book_document)
for record in report.records:
    print(record.value, record.candidate)
for issue in report.issues:
    print(issue.field_ids, issue.kind, issue.errors)
```

A report validates automatically but does not require all candidates to pass. It retains accepted records, rejected candidates, extraction diagnostics and terminal states. Each accepted record has its original candidate; field issues retain findings. Pydantic validation details remain available alongside structural issues. Evidence may contain source content, so choose deliberately what to retain or display.

For an unpinned Contract or a manually authored plan, use the explicit stages:

```python
located = book_document.locate(Book.plan())
assembled = Book.assemble(located)
report = assembled.validate()
books = report.require_all()
```

`assemble` takes located evidence without running Pydantic validation. Pass `limits=` to assemble or validate for their respective resource budgets. The ordinary extraction methods apply both stages for you.

## Schema identity

`Book.contract_schema()` and `Book.identity()` describe the native transport shape used to assemble evidence. This identity does not fingerprint Python type behavior, validators, defaults, aliases or model configuration. It is not a claim that Python validation matches Rust validation. Locator expressions remain in `Book.plan()`.

`ys.contracts.ContractValue` and `value_type_id` describe the portable native value vocabulary. A Python custom field type does not need a TYPE_ID or that registry.

## Use a runtime schema

Use `ys.contracts.RuntimeContract` when schema fields come from configuration
or a Python class is not the right authoring model. The Rust constructor
validates the schema and owns its identity, extraction, and validation:

```python
import yosoi as ys

# Declare the record independently of its queries.
schema = ys.contracts.ContractSchema(
    id="catalog_item",
    description="One item in a catalog",
    scope="repeated",
    fields=(
        ys.contracts.FieldSchema(
            id="name",
            description="Item name",
            cardinality="exactly_one",
            value_type="string",
        ),
        ys.contracts.FieldSchema(
            id="price",
            description="Price text",
            cardinality="zero_or_one",
            value_type="string",
        ),
    ),
)
runtime = ys.contracts.RuntimeContract(contract_schema=schema)

identity = runtime.identity()

# Bind the schema field IDs to a controlled product region.
document = ys.Document.html("catalog", "<article><h2>Tea</h2><b class=price>$4.50</b></article>")
region = ys.css("article").each_as_region("catalog_item")
plan = ys.Plan(outputs=[
    ys.output("name", region.find(ys.css("h2")).text()),
    ys.output("price", region.find(ys.css(".price")).text()),
])
located = document.locate(plan)
# callout: RuntimeContract keeps the portable Rust string pipeline. It does not run application-defined Python validators.
extracted = runtime.extract(located)
outcome = extracted.validate()
```

The schema-only path uses Rust field IDs directly and supports
`string` values with page or repeated scope. `runtime.contract_schema`
returns the validated schema; `runtime.identity()` returns its Rust identity.
The schema does not contain locator expressions: create an ordinary `Plan`
whose output IDs match the field IDs, then pass its `LocateOutcome` to
`runtime.extract`. For repeated scope, the plan's region ID must match
`schema.id`. Pass `limits=` to `extract` or `validate` to override their Rust
defaults.
`RuntimeContractOutcome.require_all()` follows the same Rust success rules and
returns `RuntimeValidatedRecord` objects. Each `record.value` is a map keyed by
field ID, whose values retain the cardinality tag and typed scalar; each record
also preserves its `candidate`. The class-based `Book` path instead constructs records through Pydantic. Its custom types and validators are Python behavior, separate from the portable Rust runtime.

## Portable outcomes

Python model reports can contain arbitrary types, transformed values and application validators. They cannot be represented faithfully by the Rust portable Contract format; `to_archived()` directs callers to RuntimeContract instead. Use ordinary Pydantic serialization for your model values and retain the report's original evidence separately.

`RuntimeContractOutcome.to_archived()` continues to use the Rust schema and wire format. It checks string projections, cardinality and completeness before producing portable archive values. General Python custom types do not extend that portable Rust vocabulary.

## Python API migration

`Product.extract` now accepts a document and returns validated Product instances. The former located-evidence method is `Product.assemble(located)`. `ys.extract` now returns model values; use `ys.extract_report` for validated outcomes and issues. Rust Contracts retain string fields and apply native structural validation.
