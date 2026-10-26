---
title: Python SDK
description: Author Python Contract models while the native SDK gathers their evidence.
order: 2
---

# Python SDK

The `yosoi` package provides Pydantic models and operations over the public Rust
SDK. Its current surface includes immutable documents, locator plans, typed
Contracts, Policy, asynchronous Requests, Map, Search, and caller cancellation.
Rust parses and locates documents, groups raw Contract evidence, acquires and
discovers URLs, and validates Policy. Python constructs Contract records and
runs their normal Pydantic validation.

Start with the [Python SDK overview](../python/index.md), then follow the
[installation guide](../python/installation.md). The topic pages cover
[documents and locators](../python/documents-and-locators.md),
[Contracts](../python/contracts.md),
[workflows](../python/workflows.md), and
[errors and limits](../python/errors-and-limits.md).

The 0.2.0 browser surface adds managed and borrowed Flow invocation, typed
assertions, scoped Until, local JavaScript snapshots and structured outcomes.
See [Python browser workflows](../python/browser-workflows.md) for ownership,
permissions and cancellation.

```python
import yosoi as ys

class Greeting(ys.Contract):
    """One page greeting."""

    title: str = ys.Field("Page title", locator=ys.css("h1"))

document = ys.Document.html("page", "<h1>Hello</h1>")
greetings = ys.extract(document, Greeting)
assert greetings[0].title == "Hello"
```

`ys.extract` returns validated Python models. Use
`ys.extract_report(document, Greeting)` to retain candidates, accepted records,
and Pydantic validation issues. See [Python Contracts](../python/contracts.md)
for the report and the separate native `RuntimeContract` API.

> [!NOTE]
> **Python**
>
> Pydantic validators and defaults affect Python Contract records. They are not
> part of `Contract.identity()`, which describes the native transport schema.

## Interpreter and native capabilities

The package declares `>=3.12,<3.16` and requires Pydantic `>=2.14,<3`.
Its configured interpreter targets are normal CPython 3.12–3.15, and
free-threaded CPython 3.14.8t and 3.15.0t. The extension uses separate
`cp312`, `cp313`, `cp314`, `cp314t`, `cp315`, and `cp315t` ABI wheels;
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
