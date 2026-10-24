---
title: Python SDK
description: Author Python Contract models and run evidence collection through the native SDK.
order: 0
---

# Python SDK

The `yosoi` package gives Python applications Pydantic models for documents,
locator plans, policies, Contracts, and requests. The native extension uses
Rust to parse documents, compile and evaluate locators, group raw Contract
evidence, acquire URLs, discover candidates, and validate Policies. Python
Contract records are then constructed and checked by Pydantic.

Use `import yosoi as ys` for the package-level authoring surface. For example,
a Contract is a Pydantic model whose fields bind names to explicit locators:

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
products = ys.extract(document, Product)
assert len(products) == 1
assert products[0].name == "Tea"
assert products[0].price.minor_units == 450
```

Ordinary extraction returns `list[Product]`. Pydantic applies the model's field
types, constraints, aliases, defaults, validators, and serializers. Use
`ys.extract_report(document, Product)` when you need rejected candidates,
validation errors, or the source evidence retained beside each record.

> [!NOTE]
> **Python**
>
> A Python Contract's identity covers its native transport schema, not its
> Pydantic types or validators. Use `RuntimeContract` when the Rust-owned
> string and Money conversion rules and portable Rust archive format are needed.

## Pages

For managed recipes, borrowed browser leases, typed assertions and explicit
JavaScript permission, see [Python browser workflows](browser-workflows.md).

| I want to…                                             | Read                                                                     |
| ------------------------------------------------------ | ------------------------------------------------------------------------ |
| Install the Python package for a supported interpreter | [Installation](installation.md)                                          |
| Create documents, plans, and inspect locator evidence  | [Documents and locators](documents-and-locators.md)                      |
| Define a Pydantic Contract and handle its outcomes     | [Contracts](contracts.md)                                                |
| Bind Policy and run Requests, Map, or Search           | [Workflows](workflows.md)                                                |
| Understand errors, absence, and resource limits        | [Errors and limits](errors-and-limits.md)                                |
| Review interpreter, browser, and parity evidence       | [Compatibility and parity](compatibility.md), [parity report](parity.md) |

The interpreter range is `>=3.12,<3.16`. Normal CPython 3.12–3.15 use
separate ABI wheels; free-threaded CPython 3.14.8 and 3.15.0 use the `cp314t`
and `cp315t` ABIs. Wheel availability remains specific to the release, operating system, and
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

These commands describe the source-checkout review surface. The recorded wheel
matrix applies to named earlier SDK snapshots. See [compatibility](compatibility.md)
for that historical evidence boundary and [Install](../getting-started/install.md) for
the shared current learning path.
