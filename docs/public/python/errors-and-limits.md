---
title: Python errors and limits
description: Distinguish Pydantic model errors from native operation outcomes and budgets.
order: 5
---

# Python errors and limits

Python reports invalid model input as a Pydantic `ValidationError`. Native
setup and resource-lifecycle failures use named exceptions from
`yosoi.errors`:

| Exception                                 | Stage                                                 |
| ----------------------------------------- | ----------------------------------------------------- |
| `DocumentError`                           | Document ID, profile, or payload authoring            |
| `LocatorError`                            | Query authoring or Rust validation                    |
| `ParseError`                              | Creating a reusable parsed document                   |
| `ClosedResourceError`                     | Using a parsed handle after closing it                |
| `PolicyError`                             | Rust policy validation, identity, or resolution       |
| `RequestError`, `MapError`, `SearchError` | Operation preparation or initialization               |
| `ContractError`                           | Contract declaration, schema, or native input parsing |

`YosoiError` is the common native base class. Import exceptions explicitly,
for example `from yosoi.errors import PolicyError`. Document, locator,
request, Map, and Search execution results also carry typed statuses; do not
convert those statuses into exceptions or empty collections without deciding
what that means for your application.

## Structured error details

Supported native authoring errors retain their Rust discriminant and payload:

```python
import yosoi as ys
from yosoi.errors import LocatorError, rust_error_details

try:
    ys.css("")
except LocatorError as error:
    detail = rust_error_details(error)
    if detail is not None:
        print(detail.rust_type, detail.variant, detail.details)
```

`rust_error_details()` also searches Python exception causes and Pydantic
validation contexts, preserving the original exception category. It returns
`None` when the binding has no typed metadata. The returned detail is a frozen
view; nested payloads are preserved and `source_chain` contains only sources
the Rust error actually exposes. Malformed serialized inputs are reported as
`serde_json::Error` categories rather than guessed domain variants.
For an opaque public Rust error struct, `variant` is `None`: its private
implementation is not part of the SDK contract.
Request preparation/send and Map errors use this opaque boundary. Search
query and operation errors expose their public Rust enum variants, and
activity/capture identity parsing preserves invalid UUID, noncanonical, and
non-v4 distinctions.

Document authoring preserves public `DocumentError` and `DocumentProfileError`
variants. Parse errors retain the public `ParseError` variant and nested
`DocumentParseError` type and message. The nested parser error's private variant
is not inferred from its message. A transparent Rust error can expose an empty
source chain even when the typed payload contains a nested error.

JSON projections reject NaN and positive or negative infinity, including
non-finite numbers nested in arrays or objects. These values cannot be
represented by the Rust SDK's JSON value type.

Request and Search results expose typed diagnostic/reason unions, including
browser failures, transport and redirect failures, artifact families, and
decoding codes. These preserve the Rust tags and payloads. Use their fields or
explicit serialization to inspect them; default displays redact sensitive
request/search content. `ys.map.rejection_message(reason)` returns Rust's
human-readable message while retaining the original rejection tag.
The public `ys.locators.JsonQuerySyntaxError` alias describes the four exact
syntax-error tags carried in nested JSON query errors.

Diagnostic unions describe values rather than callable constructors. To
validate an authored diagnostic or decoded payload, use Pydantic's TypeAdapter:

```python
from pydantic import TypeAdapter
from yosoi.diagnostics import PartialReason

reason = TypeAdapter(PartialReason).validate_python(
    {"kind": "browser_artifact_truncated", "family": "rendered_dom"}
)
if reason.kind == "browser_artifact_truncated":
    print(reason.family)
```

## Contract outcomes

`ys.contracts.ContractSchemaFailure` is a typed view of portable schema-error
variants and their payloads. Invalid-schema failure views accept a nested
`schema_error` while retaining `kind` and `message`. `RuntimeContract` validates
that native schema before extraction, so schema failures are raised during
authoring rather than emitted as extraction outcomes.

Ordinary `ys.extract(document, Product)` returns a list of validated Product
models. By default, a rejected candidate raises an error. Use a report when
you need both the accepted values and every rejection:

```python
import yosoi as ys

report = ys.extract_report(document, Product)
for record in report.records:
    print(record.value, record.candidate.document_id)
for issue in report.issues:
    print(issue.kind, issue.field_ids, issue.errors)
```

`report.records` contains immutable evidence wrappers. Their `.value` is the
mutable Pydantic model and `.candidate` retains its original findings;
`report.accepted_records` gives the models directly. An issue exposes
`.field_ids`, a `.kind`, the original Pydantic `ValidationError` in `.error`,
and safe `.errors` details without input values. `report.require_all()` returns
the models only when all candidates and extraction diagnostics pass. A lone
Pydantic rejection from ordinary extraction can raise `ValidationError`;
combined issues and terminal failures use `ys.contracts.ContractIssues`.

| Status                | Interpretation                                                                                   |
| --------------------- | ------------------------------------------------------------------------------------------------ |
| `evaluated`           | Location completed. Inspect accepted records, rejected candidates, and issues.                   |
| `no_match`            | Complete location found no candidate; ordinary extraction returns `[]` when the minimum is zero. |
| `indeterminate`       | Evidence is partial or unknown, so absence cannot be concluded.                                  |
| `locate_failed`       | The plan or locator evaluation failed before record validation.                                  |
| `extraction_rejected` | Native candidate assembly exceeded an extraction budget or could not proceed.                    |
| `validation_rejected` | Native validation preflight exceeded a work budget or could not proceed.                         |

Record issue kinds include `missing_required`, `excess_candidates`,
`incomplete_evidence`, and `validation_error`. The last kind retains Pydantic
field and model validation details. `on_rejected_record="collect"` returns only
accepted models from ordinary extraction; use `extract_report` if rejected
evidence must remain available. Incomplete, failed, and budget-rejected reports
never become ordinary extraction successes, even with `collect`.

`ExtractionPolicy.minimum_records` defaults to zero. Set it to one or higher
when ordinary extraction should fail on an empty result. An optional Pydantic
field still needs an explicit default such as `default=None`; Pydantic does not
invent that default.

Python Contract outcomes cannot be converted into the portable Rust archive
format because Python models can have custom types and validation behavior.
`ContractOutcome.to_archived()` raises `TypeError`; use `RuntimeContract` when
the Rust String value format and archive are required.

## Separate budgets

Rust obtains default Policy values through `Policy()`. A byte budget does not
also raise a node, depth, match, or retained-evidence budget. Common units are:

| Fields                                                                       | Unit                                                        |
| ---------------------------------------------------------------------------- | ----------------------------------------------------------- |
| `*_bytes`, `*_utf8_bytes`, `max_input_bytes`, `max_output_bytes`             | Bytes in the named domain                                   |
| `maximum_elapsed` under Request or Search                                    | Integer microseconds                                        |
| `map.limits.maximum_elapsed`                                                 | `Duration(seconds, nanoseconds)`                            |
| `max_nodes`, `max_matches`, `max_regions`, `max_requests`, `max_concurrency` | Nodes, matches, regions, requests, or concurrent operations |
| `max_depth`, `max_query_steps`, `max_link_depth`                             | Depth or bounded steps                                      |

Request source limits distinguish content-coded bytes, decoded representation
bytes, and UTF-8 bytes. They are separate because decoding or decompression can
change payload size. The Rust [Policy and Limits references](../sdk/policy.md)
list current defaults.

`ys.ExtractionPolicy` supplies optional `extraction_limits` and
`validation_limits` to `Product.extract(document, policy=...)`,
`ys.extract(document, Product, policy=...)`, or `ys.extract_report(...)`.
`ExtractionLimits.uniform(n)` sets all seven extraction counters to the same
bound. `minimum_records` and `on_rejected_record` control result acceptance,
not native work.

For explicit stages, `Product.assemble(located, limits=...)` groups the raw
findings. `extracted.validate(limits=...)` returns the Python report. Python preflight bounds candidate counts, schema work, field inputs and retained provenance before user Pydantic hooks run. Its conversion-work budget also charges default slots and alias-container expansion, so an authored AliasPath cannot allocate an unbounded list. Field and record budgets also bound
the validation domain. A global validation-budget rejection withholds accepted records and over-budget issue collections while retaining raw candidates and failure facts. The issue budget is charged after Pydantic errors have
been collected, so it does not interrupt arbitrary work inside a custom
validator.

`RuntimeContract` keeps the Rust-owned staged path and accepts the same
`ExtractionLimits` and `ValidationLimits`. It supports Rust String
conversions. An exhausted native budget remains a typed terminal report with
the relevant limit, maximum, and observed count. Inspect its stage before
adjusting that operation's budget.
