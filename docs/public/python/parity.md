---
title: Rust and Python parity
description: Read the machine-readable surface inventory and conformance status without overstating coverage.
order: 7
---

# Rust and Python parity

Python Contracts are now bound to the Rust Contract runtime. The package also
has Python surfaces for documents, locators, policy, Requests, Map, and Search.
The machine-readable parity report tracks each public Rust symbol separately;
the presence of a Python class or module does not prove semantic parity.

## What the report consumes

The parity tool starts from the compiler-derived Rust API reference inventory,
not a search through Rust source text. It joins that inventory with live
introspection of the Python package, a reviewed mapping ledger, and
snapshot-bound conformance evidence. The report consumer schema is
`python/parity/report.schema.json`.

Each report pins the Rust source revision, compiler inventory signature, and
feature profile, along with Python surface and implementation digests. The
coverage denominator is the set of Rust public items in that compiler
inventory. An item is verified only when its mapping and executed
conformance evidence match the same pinned snapshot.

## Status meanings

| Status              | Meaning                                                                                             |
| ------------------- | --------------------------------------------------------------------------------------------------- |
| `mapped`            | A Python target is recorded and present, but matching conformance evidence is absent.               |
| `verified`          | The mapped Python target has accepted conformance evidence for this exact Rust and Python snapshot. |
| `stale`             | A source pin, signature, Python target, or available evidence differs from the reviewed snapshot.   |
| `missing`           | A Rust public symbol has no explicit Python mapping.                                                |
| `language-specific` | A reviewed reason records why an item intentionally has no cross-language mapping.                  |

Only `verified` and reviewed `language-specific` items count as covered.
`mapped` is reported separately as mapped-but-unverified. A stale report or an
unmapped item keeps overall parity incomplete. A generated count or percentage
must come from the consumer report; it should not be replaced with an estimate
based on feature names.

## Current evidence boundary

The checked-in ledger currently has no Rust or Python snapshot pins, and no
current generated `report.json` is included. That means this documentation
does not claim a computed item count or completed parity percentage. The
current Contracts authoring and native runtime mapping are present in source;
fresh Contract conformance and wheel evidence are still pending for the
current snapshot.

The earlier local wheel report in `python/COMPATIBILITY.md` records a prior
SDK snapshot. It explicitly predates Contract authoring and used
free-threaded CPython 3.14.3t. See the separate
[current compatibility status](compatibility.md) for the present build and
platform limits.
