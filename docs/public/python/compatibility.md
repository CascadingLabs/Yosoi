---
title: Python compatibility status
description: Separate declared interpreter targets from current wheel, browser, and provider evidence.
order: 6
---

# Python compatibility status

The package declares `>=3.12,<3.16` and requires Pydantic `>=2.14,<3`.
The current CI configuration selects normal CPython 3.12, 3.13, 3.14.8, and
3.15.0, plus free-threaded CPython 3.14.8t and 3.15.0t.
These selectors describe configured targets; they are not, by themselves,
proof that the current revision built, installed, or passed on each target.

| Target                        | Current status                                                                                                                                                                                |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CPython 3.12                  | Current 3.12.14 installed wheel: 282 passed, one free-threading-only skip.                                                                                                                    |
| CPython 3.13                  | Current 3.13.1 installed wheel: 282 passed, one free-threading-only skip.                                                                                                                     |
| CPython 3.14.8                | Current local Linux x86-64 installed-wheel checks: 282 passed, one free-threading-only skip.                                                                                                  |
| Free-threaded CPython 3.14.8t | Current separate `cp314t` wheel: 283 passed, including fresh-interpreter imports and concurrent parsing/Contract validation with the GIL disabled.                                            |
| CPython 3.15.0                | Local installed wheel: 282 passed, one free-threading-only skip.                                                                                                                              |
| Free-threaded CPython 3.15.0t | Local separate `cp315t` wheel: 283 passed, including synchronized shared parsing and Contract validation with the GIL disabled.                                                               |
| Browser feature               | The Maturin configuration requests the Rust feature; current wheel startup and browser execution have not been verified. A regular Chrome or Chromium executable remains an external install. |
| Search providers              | Built-in routes remain previews. Local examples do not certify live providers.                                                                                                                |

Wheel support still depends on operating system, architecture, and platform
tags. The current CI matrix does not establish that a release has published a
wheel for every such target.

These current wheels were built from the integrated workspace in the
development profile with the Rust browser feature enabled. They are local
validation artifacts, not published release wheels or hosted CI results.
One operation-error source distribution built and passed on all four targets.
The current identity, typed-failure, equality, and clone additions passed
installed-wheel checks on all four interpreters. Browser
execution and hosted CI remain pending.

The Python 3.15 checks use Pydantic 2.14.0 and pydantic-core 2.50.0.
Both interpreter-specific wheels are built from an sdist with the Rust
browser feature enabled. These checks cover local Linux x86-64 development
builds; hosted CI, browser certification, and published wheels remain separate.

## Earlier local compatibility evidence

`python/COMPATIBILITY.md` records a local Linux x86-64 development-profile
matrix for an earlier Python SDK snapshot. It used CPython 3.12.14, 3.13.1,
3.14.3, and free-threaded 3.14.3t. That report predates Python Contract
authoring and did not enable the browser feature. Its passing tests, examples,
and wheel filenames remain historical evidence for that snapshot; they do not
verify the new Contract bridge, 3.14.8t, browser execution, release artifacts,
or hosted CI.

The workflow file currently includes a `contracts` example step for each
configured interpreter. A successful result must be recorded from that
workflow or an equivalent current local run before claiming the matrix passed.
The [parity report](parity.md) separately tracks symbol-level Python/Rust
coverage and requires matching compiler inventory and conformance evidence.
