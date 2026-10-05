---
title: Python SDK
description: Author documents, locators, and typed Contracts with Pydantic and run them in Rust.
order: 0
---

# Python SDK

The `yosoi` package gives Python applications a Pydantic authoring surface over
the public Rust SDK. Python models describe documents, locator plans, policies,
Contracts, and requests. The native extension passes those declarations to
Rust, which parses, locates, extracts, converts, validates, fetches, and
discovers within the same bounded runtime used by the Rust SDK.

Use `import yosoi as ys` for the package-level authoring surface. For example,
a Contract is a Pydantic model whose annotations define Rust cardinality:

```python
import yosoi as ys

class Product(ys.Contract):
    """One catalog product."""

    root = ys.css("article.product")
    name: str = ys.Field("Product name", locator=ys.css("h2"))
    price: ys.Money = ys.Field("USD price", locator=ys.css(".price"))

document = ys.Document.html(
    "catalog",
    "<article class='product'><h2>Tea</h2><span class='price'>$4.50</span></article>",
)
outcome = ys.extract(document, Product).validate()
```

Rust owns the Contract schema identity, candidate grouping, field conversion,
semantic validation, evidence retention, and `require_all()` decision. Python
models provide named fields and inspectable typed views; they do not re-run
Pydantic validators or defaults to change a Rust-validated record.

## Pages

| I want to…                                             | Read                                                                     |
| ------------------------------------------------------ | ------------------------------------------------------------------------ |
| Install the Python package for a supported interpreter | [Installation](installation.md)                                          |
| Create documents, plans, and inspect locator evidence  | [Documents and locators](documents-and-locators.md)                      |
| Define a Pydantic Contract and handle its outcomes     | [Contracts](contracts.md)                                                |
| Bind Policy and run Requests, Map, or Search           | [Workflows](workflows.md)                                                |
| Understand errors, absence, and resource limits        | [Errors and limits](errors-and-limits.md)                                |
| Review interpreter, browser, and parity evidence       | [Compatibility and parity](compatibility.md), [parity report](parity.md) |

The interpreter range is `>=3.12,<3.15`. Normal CPython 3.12, 3.13, and
3.14 use separate ABI wheels; free-threaded CPython 3.14.8 uses the `cp314t`
ABI. Wheel availability remains specific to the release, operating system, and
architecture. See [installation](installation.md) before selecting an
artifact.

The browser capability is a Rust build feature. A wheel built with that
feature still needs a regular Chrome or Chromium executable installed on the
machine. The Python package does not ship the browser executable.

## Review examples

From a source checkout, use the current script to inspect Contracts or a
loopback Requests/Map workflow:

```sh
uv run --no-sync python python/examples/review.py contracts
uv run --no-sync python python/examples/review.py local
```

These commands describe the current review surface. Fresh native-wheel and
Contract runtime results are still pending; the recorded wheel matrix covers
an earlier Python SDK snapshot. See [compatibility](compatibility.md) for the
evidence boundary.
