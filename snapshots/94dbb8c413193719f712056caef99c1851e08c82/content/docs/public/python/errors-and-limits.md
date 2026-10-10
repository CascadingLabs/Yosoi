---
title: Python errors and limits
description: Distinguish authoring exceptions from Rust operation outcomes and their budgets.
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

`ys.contracts.ContractSchemaFailure` is a typed view of schema-error variants
and their payloads. Invalid-schema failure views accept a nested
`schema_error` while retaining `kind` and `message`. The current runtime
Contract constructor validates schemas before extraction; its schema failures
are raised during authoring rather than emitted as extraction outcomes.

Contract extraction and validation return outcomes that preserve each stage:

| Status or issue                                                          | Interpretation                                                                                     |
| ------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------- |
| `evaluated`                                                              | Rust checked every extracted candidate; inspect `records`, `issues`, and `extraction_diagnostics`. |
| `no_match`                                                               | Location completed and found no Contract candidate. `require_all()` returns an empty list.         |
| `indeterminate`                                                          | Evidence is partial or unknown, so absence cannot be concluded.                                    |
| `locate_failed`                                                          | The input plan or locator evaluation failed before Contract extraction.                            |
| `extraction_rejected`                                                    | A Rust Contract extraction budget was exceeded or extraction could not proceed.                    |
| `validation_rejected`                                                    | A Rust validation budget was exceeded or validation could not proceed.                             |
| `missing_required`, `excess_candidates`                                  | A scalar has zero or multiple findings.                                                            |
| `incomplete_evidence`, `conversion_failed`, `semantic_validation_failed` | A finding cannot produce a validated field value.                                                  |

Field issues retain the candidate and source `Finding` evidence. `require_all()`
returns values only when there are no record issues or extraction diagnostics;
otherwise it raises `ys.contracts.ContractIssues` with Rust's structured
rejection detail. `NoMatch` is the one terminal status that returns an empty
list.

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

Contract extraction has its own counters for scanned regions and findings,
matching findings, candidates, values per field, retained evidence, and
diagnostics. By default it uses the Rust locator policy's `max_matches` value
for match/evidence counters and `max_regions` for candidate records. A
repeated Contract can therefore hit its candidate bound independently of
another locator or parser budget.

`ys.contracts.ExtractionLimits` can set those extraction counters explicitly;
`ExtractionLimits.uniform(n)` sets all seven to the same bound.
`ys.contracts.ValidationLimits` controls validation fields, records,
conversions, issues, and retained provenance. Its Rust defaults allow 1,024
fields and 100,000 records, conversions, issues, and provenance items in their
respective domains. Pass limits to `Contract.extract(..., limits=...)` or
`Extracted.validate(limits=...)` when the application needs a different bound.

An exhausted budget remains a typed failure with the relevant limit, maximum,
and observed count. Inspect the stage that stopped and adjust only that
operation's budget.
