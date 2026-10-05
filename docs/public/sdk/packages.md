---
title: Packages and capabilities
description: Choose the Rust SDK, Python SDK, or CLI without importing implementation crates.
order: 1
---

# Packages and capabilities

Yosoi has one public Rust SDK, a Python package, and a CLI. The Rust SDK owns
processing and domain validation. Python uses Pydantic for authoring and
inspecting values, then delegates operations to the same Rust SDK. Python
Contracts are now bound to Rust; item-level parity is tracked separately, and
the package does not claim complete verified parity.

| Package            | Use it for                                                                               |
| ------------------ | ---------------------------------------------------------------------------------------- |
| `yosoi`            | Integrating Yosoi into a Rust application                                                |
| `yosoi` for Python | Integrating documents, locators, Contracts, Policy, Requests, Map, or Search from Python |
| `yosoi-cli`        | Running Yosoi from a terminal or shell pipeline                                          |

The CLI and Python bindings consume the public Rust SDK. Implementation crates
divide ownership of documents, policy, contracts, acquisition, and discovery.
Applications do not need to import those crates to use the SDK. The
[Python Contracts guide](../python/contracts.md) covers the supported
Pydantic annotations and Rust outcome model. The
[machine-readable parity report](../python/parity.md) distinguishes a
declared mapping from snapshot-matched conformance evidence.

## Optional capabilities

The Rust SDK's `browser` feature enables browser acquisition. Direct HTTP and
local document processing remain available without that feature. A browser
operation also needs a compatible regular Chrome or Chromium installation.

Rust features choose which native capabilities are compiled into a build.
A Python wheel has a fixed compiled capability set; Python extras do not
recompile its extension. Browser support does not require a Python browser
automation package.

## Python versions

The package declares CPython `>=3.12,<3.15`. Its configured interpreter
targets are normal CPython 3.12, 3.13, and 3.14.8, plus free-threaded CPython
3.14.8t. The native extension uses separate `cp312`, `cp313`, `cp314`, and
`cp314t` ABI wheels. Python 3.15 is outside the declared range.

Pydantic 2 is the only declared Python runtime dependency. The native extension
ships in the package. Build, lint, type-check, and test tools are development
dependencies. Source installation requires the Rust toolchain and native build
prerequisites. A release may not publish a wheel for every platform, so check
the release artifacts for the target you plan to install. Earlier local wheel
checks used 3.14.3t and predate Contract authoring; see the separate
[compatibility status](../python/compatibility.md).
