---
title: Python compatibility status
description: Separate declared interpreter targets from current wheel, browser, and provider evidence.
order: 6
---

# Python compatibility status

The package declares `>=3.12,<3.15`. The current CI configuration selects
normal CPython 3.12, 3.13, and 3.14.8, plus free-threaded CPython 3.14.8t.
These selectors describe configured targets; they are not, by themselves,
proof that the current revision built, installed, or passed on each target.

| Target                        | Current status                                                                                                                                                                                |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CPython 3.12                  | Declared and selected by CI; fresh wheel/test evidence after the Contract binding change is pending.                                                                                          |
| CPython 3.13                  | Declared and selected by CI; fresh wheel/test evidence after the Contract binding change is pending.                                                                                          |
| CPython 3.14.8                | Declared and selected by CI; fresh wheel/test evidence after the Contract binding change is pending.                                                                                          |
| Free-threaded CPython 3.14.8t | Separate `cp314t` ABI target is selected by CI; fresh wheel, runtime, and GIL evidence after the Contract binding change is pending.                                                          |
| Browser feature               | The Maturin configuration requests the Rust feature; current wheel startup and browser execution have not been verified. A regular Chrome or Chromium executable remains an external install. |
| Search providers              | Built-in routes remain previews. Local examples do not certify live providers.                                                                                                                |

Wheel support still depends on operating system, architecture, and platform
tags. The current CI matrix does not establish that a release has published a
wheel for every such target.

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
