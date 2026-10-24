---
title: Rust and Python parity
description: Read the machine-readable surface inventory and conformance status without overstating coverage.
order: 7
---

# Rust and Python parity

Python Contracts use Rust to locate and group raw candidate evidence, then use
Pydantic to construct and validate Python records. The package also has Python
surfaces for documents, locators, policy, Requests, Map, Search, and local Archive workflows. Documents, compiled Plans, and automation records can be saved and restored; bounded View pages inspect retained observations. The local Archive backend currently supports Unix only. The
machine-readable parity report tracks SDK mappings and executed capability
checks. Its full Rust inventory remains available as a separate audit.

> [!NOTE]
> **Python**
>
> A Python Contract's field types, validators, defaults, and model configuration
> are Python business rules. The exact cross-language Contract conformance case
> uses `RuntimeContract`, whose schema and validation stay Rust-owned.

## SDK parity gate

The release gate measures equivalent SDK concepts across the two languages.
A Rust accessor can map to a Pydantic field; a Rust enum can map to a tagged
union or a returned outcome view. Matching Rust's compiler-generated trait
methods is a separate inventory concern.

`python/parity/sdk-contract.json` records the reviewed SDK declarations, their
structural signatures, Python mappings, and Rust-language dispositions. New
declarations, removed declarations, changed arguments, changed Python schemas,
and incomplete mappings fail the SDK gate. Changes to Rust implementation
bytes or a rebuilt native extension require fresh evidence rather than a
workstation-specific binary hash in the committed mapping baseline.

Run the gate from a checkout with an installed Python wheel and the pinned
Rust reference compiler available:

```sh
uv run --no-sync python scripts/sdk-parity/run_sdk_parity.py --output-dir .generated/python-parity
```

The command generates the compiler inventory, prepares an output-only runtime
ledger, builds the nine Rust fixture executables serially, runs their Python
comparisons, and enforces the SDK report. It never rewrites the reviewed ledger
or SDK contract. The Python CI workflow runs this gate on normal Python 3.14
and uploads the report, runtime pins, compiler reference, and raw evidence even
when the gate fails. The separate package matrix checks all supported ABIs.

The report distinguishes mapping completeness, capability-suite results, and
individual-item evidence. A mapped item does not become individually verified
merely because its capability suite passes. All required suites must contain
passing comparisons with current source, runtime, and native-binary pins.

The gate requires a clean checkout at the selected source commit and rebuilds
its fixtures. It rejects `--skip-build`, dirty worktrees, and a source revision
that differs from the build checkout. `--rust-reference` can reuse a verified
compiler inventory only when that inventory matches the same selected commit.

## Browser behavior evidence

Installed-wheel browser journeys produce a separate report through
`scripts/sdk-parity/browser_evidence.py`. It records passing required stories,
the selected wheel and installed native hashes, the source revision, and regular
Chrome identity. Pass it to the SDK gate with `--browser-evidence`; the gate
rejects stale source or extension identities. Python CI runs these journeys
for normal and free-threaded Python 3.14 before consuming the report.

The beta contract explicitly defers the Rust Archive/View facade while retaining
those declarations in the audit. New browser namespaces and the Rust-only
Contract trait adapter have narrow recorded dispositions; they do not exempt
functional APIs from mapping or behavior checks. Mapping completeness, required
suite results, and per-declaration evidence remain distinct claims.

## What the report consumes

The parity tool starts from the compiler-derived Rust API reference inventory,
not a search through Rust source text. It joins that inventory with live
introspection of the Python package, a reviewed mapping ledger, and
snapshot-bound conformance evidence. The report consumer schema is
`python/parity/report.schema.json`.

Each report pins the Rust source revision, compiler inventory signature, and
feature profile, along with Python surface and implementation digests. The
inventory-audit denominator is the set of Rust public items in that compiler
inventory, including language-level trait mechanics. The SDK gate has its own
reviewed scope. An item is individually verified only when its mapping and executed
conformance evidence match the same pinned snapshot.

## Status meanings

| Status              | Meaning                                                                                             |
| ------------------- | --------------------------------------------------------------------------------------------------- |
| `mapped`            | A Python target is recorded and present, but matching conformance evidence is absent.               |
| `verified`          | The mapped Python target has accepted conformance evidence for this exact Rust and Python snapshot. |
| `stale`             | A source pin, signature, Python target, or available evidence differs from the reviewed snapshot.   |
| `missing`           | A Rust public symbol has no explicit Python mapping.                                                |
| `language-specific` | A reviewed reason records why an item intentionally has no cross-language mapping.                  |

In the full inventory audit, only `verified` and reviewed `language-specific` items count as covered.
`mapped` is reported separately as mapped-but-unverified. A stale report or an
unmapped item keeps that inventory audit incomplete. The SDK gate separately
requires complete semantic mappings and passing capability suites. A generated count or percentage
must come from the consumer report; it should not be replaced with an estimate
based on feature names.

## Current evidence boundary

The checked-in SDK contract accounts for 1,288 SDK declarations: 1,286 direct
mappings and two reviewed owning-view adaptations. The committed summary was
generated on 2026-10-05 for Rust source revision
`0fd4ec5ac6b14ec180ba48c404a1c3166535f87a`. At that snapshot, the local semantic
SDK gate passed all nine required capability suites with no structural drift
or unresolved mappings. Its individual-item evidence remains separately
visible; passing the SDK gate does not imply that every generated Rust
inventory item has an individual comparison. Hosted CI results are separate
from this local verification claim.

That recorded comparison runner has 63 matching Rust/Python workflows,
including independent Policy defaults, query metadata and namespace errors,
native `RuntimeContract` extraction, validation and archival conversion,
detached cloning, and exact null-versus-absence serialization. It does not
compare arbitrary Python Contract validators with Rust Contract validation.
The 2026-10-05 summary predates the current Pydantic Contract extraction path;
regenerate the runner evidence and summary before using it as evidence for the
current source. Those workflow results do not verify every public symbol or
argument mapping.

The Contract identity workflow compares native built-in, custom, and empty
transport type IDs. `RuntimeContract` permits custom schema IDs but reads only
the scalar values supported by the Rust SDK. Those native IDs do not fingerprint
a Python Contract's Pydantic types or validation behavior.

WebTarget fixtures compare 24 authored values through every public Rust `From`
string ownership form, `AsRef<str>`, `new`, and `as_str`. Unicode, whitespace,
empty targets, and invalid URL text remain unchanged during construction; URL
preparation is a separate SDK operation. Each trait implementation is selected
by its exact compiler symbol and argument type.

A separate independent Rust fixture supplies 131 diagnostic values and Map
rejection messages. Python validates their typed views and compares serialized
tags and payloads exactly. Its source-pinned evidence is attributed to mapped
enum types, exact variants, and individually checked payload arguments.

Tagged-union payload mappings record the discriminator, selected variant, and
dictionary fields accepted by `TypeAdapter.validate_python`. The checker
validates these against the live Pydantic member schema, and evidence compares
each mapped payload argument independently. A type alias is never presented as
a callable constructor.

An independent operation-error runner compares 12 Request, Map, Search, and
identity parsing failures, including Rust messages, public variants or opaque
markers, payloads, and source chains. Its evidence is attributed to the exact
operations and error paths exercised.

Document-error fixtures add seven exact comparisons for document IDs, epochs,
empty payloads, incompatible profile axes, and JSON/HTML parsing failures.
They compare messages, error types, public variants, payloads, and actual Rust
source chains. Six cases have individually mapped ledger attributions; passing
an additional case does not automatically verify an unmapped public item.

Serialization fixtures compare 60 values across 41 public Rust types, including
independently constructed defaults, coordinates, projections, and runtime
Contract values. The Contract comparison exercises the Python `RuntimeContract`
wire and Rust archive representation, not arbitrary Pydantic model serialization.
The fixtures check exact JSON keys and nulls, with no blanket removal of null
fields. This proves the exercised JSON representations; it does not claim
compatibility with every serializer supported by Rust's Serde traits.

Schema-error representation fixtures cover all ten public schema errors,
each wrapped in both extraction and validation failures: 30 comparisons. They
check typed source payloads and message retention. They do not claim that an
already validated runtime schema can emit an invalid-schema outcome.

Rust methods represented by free Python functions record the receiver as well
as ordinary arguments. The evidence gate requires a separate receiver check;
matching only the second comparison operand cannot verify equality.

The projection equality fixture compares 22 value pairs across all five Rust
projection variants, including cross-variant comparisons, JSON number types,
null, array order, and object key order. Both operands and the returned
comparison results match Rust.

Map ordering has 97 independent comparisons across seven public types.
The evidence checks both operands and the fixed type discriminator used by
the Rust-backed Python comparator. Rust declaration order is preserved for
enums whose ordinary string ordering differs.

The [committed inventory summary](../assets/python-sdk-parity.json) is available
as a public docs asset for frontend consumers. Its schema is
`python/parity/summary.schema.json`. It contains source and runtime pins,
coverage counts, the complete report's SHA-256, and an explicit local-validation
provenance label. It retains `incomplete` or `stale` status; mapped-but-unverified
symbols do not become verified in the summary.

Generate both artifacts with the parity command's `--output` and
`--summary-output` options after running matching conformance evidence. The
summary is derived from the report, rather than maintained as a separate count.

The historical local wheel report in `python/COMPATIBILITY.md` records normal
3.14.8 and free-threaded 3.14.8t results, alongside clearly marked historical
scaffold evidence. See the separate
[current compatibility status](compatibility.md) for the present build and
platform limits.
