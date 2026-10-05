---
title: Python SDK
description: Author documents, locators, Contracts, and operations with Pydantic while Rust owns processing.
order: 2
---

# Python SDK

The `yosoi` package provides Pydantic authoring models and typed outcomes over
the public Rust SDK. Its current surface includes immutable documents, locator
plans, typed Contracts, Policy, asynchronous Requests, Map, Search, and caller
cancellation. Python describes inputs and views results; Rust owns parsing,
locator compilation and evaluation, Contract extraction and validation,
acquisition, discovery, and policy validation.

Start with the [Python SDK overview](../python/index.md), then follow the
[installation guide](../python/installation.md). The topic pages cover
[documents and locators](../python/documents-and-locators.md),
[Contracts](../python/contracts.md),
[workflows](../python/workflows.md), and
[errors and limits](../python/errors-and-limits.md).

```python
import yosoi as ys

class Greeting(ys.Contract):
    """One page greeting."""

    title: str = ys.Field("Page title", locator=ys.css("h1"))

document = ys.Document.html("page", "<h1>Hello</h1>")
outcome = ys.extract(document, Greeting).validate()
```

Contracts expose named Pydantic fields while Rust decides field cardinality,
conversion, and outcome semantics. The supported scalar and collection shapes
are intentionally bounded; see [Contracts](../python/contracts.md).

## Interpreter and native capabilities

The package declares `>=3.12,<3.15`. Its configured interpreter targets are
normal CPython 3.12, 3.13, 3.14.8, and free-threaded CPython 3.14.8t. The
extension uses separate `cp312`, `cp313`, `cp314`, and `cp314t` ABI wheels;
artifact availability still depends on release and platform.

The browser Rust feature is compiled into a wheel when enabled by its build
configuration. Install a compatible regular Chrome or Chromium executable
separately; the Python package does not bundle the browser. Search provider
routes remain previews. The machine-readable parity report distinguishes
mapped symbols from items verified against the current compiler inventory.
See [compatibility](../python/compatibility.md) and
[parity](../python/parity.md) for current evidence boundaries.

From a repository checkout, `python/examples/review.py contracts` inspects the
Contract pipeline and `python/examples/review.py local` exercises Requests,
Map, and cancellation against a loopback server. Fresh wheel checks for this
Contract integration are tracked separately from the earlier local matrix.
