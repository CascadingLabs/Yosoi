---
title: Python Contracts
description: Declare typed Pydantic records and let Rust extract, convert, and validate them.
order: 3
---

# Python Contracts

Subclass `ys.Contract` to describe a record. Use `ys.Field` for each named
field. Pydantic supplies the authoring model; the native Rust SDK owns schema
identity, evidence grouping, cardinality checks, conversion, semantic
validation, and the final `require_all()` decision.

```python
import yosoi as ys

class Book(ys.Contract):
    """A book offered for sale."""

    root = ys.css("article")
    author: str = ys.Field("Author", id="byline", locator=ys.css(".author"))
    price: ys.Money = ys.Field("USD price", locator=ys.css(".price"))
    subtitle: str | None = ys.Field("Optional subtitle", locator=ys.css(".subtitle"))
    tags: list[str] = ys.Field("Book tags", locator=ys.css(".tag"))

document = ys.Document.html(
    "books",
    "<article><b class='author'>Ada</b><b class='price'>$12.34</b>"
    "<i class='tag'>computing</i></article>",
)
extracted = ys.extract(document, Book)
outcome = extracted.validate()
```

## Types determine cardinality

The first Contract slice accepts `str`, `ys.Money`, `T | None`, and
`list[T]`, where `T` is `str` or `ys.Money`:

| Python annotation                   | Rust cardinality | Meaning                                         |
| ----------------------------------- | ---------------- | ----------------------------------------------- |
| `str` or `ys.Money`                 | `exactly_one`    | One complete scalar value is required.          |
| `str \| None` or `ys.Money \| None` | `zero_or_one`    | No value or one complete scalar value is valid. |
| `list[str]` or `list[ys.Money]`     | `many`           | Zero or more complete values are valid.         |

Two or more findings for either scalar shape produce an `excess_candidates`
issue. A `list[T]` preserves every value in locator order. A partial or unknown
finding remains an `incomplete_evidence` issue; Rust does not turn uncertain
absence into `None` or an empty list. `ys.Money` represents USD integer
minor-units. Its extraction conversion accepts the Rust USD text format and
rejects negative amounts as a semantic validation issue.

`ys.Field(description, locator=...)` stores ordinary Pydantic field metadata.
A bare query passed as `locator` uses its text projection; use a `Locator` to
choose another supported projection. Field descriptions are required. Use
`id="byline"` to choose the Rust schema and locator output ID independently
from the Python attribute name `author`. Pydantic aliases remain unsupported;
Rust output IDs must match the Contract's field IDs.

## Schema and plan are separate

`Book.contract_schema()` describes the semantic record: contract ID,
description, page or repeated scope, field IDs, cardinalities, and value types.
`Book.identity()` asks Rust for that schema's stable identity. Locator
expressions are stored in a `Plan`; they do not define the semantic schema
identity.

When every field has a locator, `Book.plan()` returns the Rust-compiled plan.
Pin all fields or leave all fields unpinned. A class-level `root` query makes
the schema repeated and supplies the region for every field. The default
contract ID is the class name; set `contract_id` and `contract_description` on
the class to author them explicitly.

```python
plan = Book.plan()
compiled_plan = plan.compiled()
schema = Book.contract_schema()
schema_identity = Book.identity()
```

For an unpinned Contract, create a plan separately and pass its
`LocateOutcome` to `Book.extract(located)`. The field output IDs must still
match the Contract's field IDs. This keeps locating usable on its own and lets
an application reuse a plan across record types.

## Use a runtime schema

Use `ys.contracts.RuntimeContract` when schema fields come from configuration
or a Python class is not the right authoring model. The Rust constructor
validates the schema and owns its identity, extraction, and validation:

```python
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
            description="USD price",
            cardinality="zero_or_one",
            value_type="money.usd",
        ),
    ),
)
runtime = ys.contracts.RuntimeContract(contract_schema=schema)

identity = runtime.identity()
extracted = runtime.extract(located)
outcome = extracted.validate()
```

The schema-only path uses Rust field IDs directly and supports `string` and
`money.usd` values with page or repeated scope. `runtime.contract_schema`
returns the validated schema; `runtime.identity()` returns its Rust identity.
The schema does not contain locator expressions: create an ordinary `Plan`
whose output IDs match the field IDs, then pass its `LocateOutcome` to
`runtime.extract`. For repeated scope, the plan's region ID must match
`schema.id`. Pass `limits=` to `extract` or `validate` to override their Rust
defaults.
`RuntimeContractOutcome.require_all()` follows the same Rust success rules and
returns `RuntimeValidatedRecord` objects. Each `record.value` is a map keyed by
field ID, whose values retain the cardinality tag and typed scalar; each record
also preserves its `candidate`. The class-based `Book` path instead maps those
Rust values back to named Pydantic fields.

## Inspect each stage

```python
extracted = ys.extract(document, Book)
print(extracted.status)
print(extracted.candidates)
print(extracted.diagnostics)

outcome = extracted.validate()
print(outcome.status)
print(outcome.records)
print(outcome.issues)
print(outcome.extraction_diagnostics)
```

Each candidate exposes `document_id`, `region`, and a named `CandidateField`
for every Contract field. A candidate field provides ordered `evidence`,
projected `values`, `is_absent`, and `is_empty`. Every finding retains its
coordinate, completeness, and parent-region lineage. Empty repeated roots are
still candidates, so validation can report required fields that were absent
inside an existing row.

An `outcome.records` item has a typed `value` and the original `candidate`.
An `outcome.issues` item also retains its candidate plus field issues and their
evidence. Rust constructs record values after validation. Python uses
`model_construct` for this conversion, so Pydantic defaults are not applied to
missing fields and Python hooks cannot change a Rust record. Contract
definitions with field/model validators, serializers, computed fields, a
root validator, custom `__init__`, or `model_post_init` are rejected when the
Rust schema is created; conversion and validation remain Rust-owned.

Extracted and validated outcome views are read-only after creation. Their
candidate, record, issue, and evidence collections use immutable views, and
record/evidence values are omitted from `repr` output. Call `model_dump()` or
`model_dump_json()` when you explicitly want to serialize their values. A
`require_all()` result is a fresh Python list of the already validated record
models.

The statuses distinguish evaluated records, complete `no_match`,
`indeterminate` evidence, locator failure, extraction rejection, and
validation rejection. The `require_all()` method returns the Pydantic record
values only when there are no record issues or extraction diagnostics. It
returns an empty list for complete `no_match` and raises `ContractIssues` for
issues, incomplete outcomes, or terminal failures.

```python
try:
    books = outcome.require_all()
except ys.contracts.ContractIssues as error:
    print(error.detail)
```

Both stages accept explicit limits: `Contract.extract(..., limits=...)` takes
`ExtractionLimits`, and `Extracted.validate(limits=...)` takes
`ValidationLimits`. Omit them to use the Rust defaults. See
[errors and limits](errors-and-limits.md) for their domains.
