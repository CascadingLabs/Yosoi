---
title: Contracts
description: Turn located evidence into typed records with a derived Contract.
order: 12
---

# Contracts

A Contract describes the record you want: fields, types and evidence bindings. Locate, extract and validate to produce records or inspect rejected candidates.

> [!NOTE]
> **Python**
> Python Contracts use Pydantic for model construction, custom field types and validators. `Product.extract(document)` validates automatically. Rust keeps its explicit locate, extract, validate and acceptance stages.

## Example: contracts

### Rust

```rust
use std::error::Error;
use yosoi::prelude as ys;

#[derive(Debug, ys::Contract)]
#[ys(id = "product", description = "A product for sale", root = ys::locator::css("article"))]
struct Product {
    #[ys(description = "Product name", locator = ys::locator::css("h2").text())]
    name: String,
    #[ys(description = "Price text", locator = ys::locator::css(".price").text())]
    price: String,
    #[ys(description = "Optional product link", locator = ys::locator::css("a").attribute("href"))]
    href: Option<String>,
}

fn main() -> Result<(), Box<dyn Error>> {
    let document = ys::Document::html(
        "catalog.html",
        b"<article><h2>Tea</h2><span class='price'>$4.50</span></article>".to_vec(),
    )?;
    // callout: Rust locates first, then extracts and validates explicitly.
    let located = Product::locate(&document)?;
    let products = Product::extract(&located).validate().require_all()?;

    for product in products {
        println!("{} costs {}", product.name, product.price);
    }
    Ok(())
}
```

The struct defines required name and price fields plus an optional link. `locate`, `extract`, `validate` and `require_all` turn evidence into accepted records or report issues.

### Python

```python
import yosoi as ys

class Product(ys.Contract):
    """A product for sale."""

    root = ys.css("article")
    name: str = ys.Field("Product name", locator=ys.css("h2"))
    price: str = ys.Field("Price text", locator=ys.css(".price"))
    href: str | None = ys.Field("Optional product link", locator=ys.css("a").attribute("href"), default=None)

document = ys.Document.html(
    "catalog.html",
    "<article><h2>Tea</h2><span class='price'>$4.50</span></article>",
)
# callout: Python constructs the Product through Pydantic and runs its validators automatically.
products = Product.extract(document)
for product in products:
    assert product.name == "Tea"
    assert product.price == "$4.50"
    assert product.href is None
    print(f"{product.name} costs {product.price}")
```

The model defines the same fields and cardinality. Python constructs and validates each Product through Pydantic automatically. The checks show the original `$4.50` price text and an absent optional link.

## Walk through the result

This prints `Tea costs $4.50`. The missing link becomes `None`.

## Page or repeated record

A Contract without `root` describes a page-level record. A Contract with `root` describes one record per matching region. In the example, each `article` is a separate product and field queries run within it.

There are no separate `page` or `repeated` attributes. Scope follows from whether a root is present. Nested repeated records are not supported.

## Field cardinality

| Rust field  | Python annotation | Accepted evidence   |
| ----------- | ----------------- | ------------------- |
| `String`    | `str`             | Exactly one value   |
| `Option<T>` | `T \| None`       | Zero or one value   |
| `Vec<T>`    | `list[T]`         | Zero or more values |

Missing required values and multiple values for a scalar are field issues. Rust does not support nested wrappers such as `Option<Vec<String>>`. Python supports Pydantic-compatible field types; a list collects one projected value per finding. A nullable Python scalar still needs an explicit `default=None` when complete absence should be accepted.

Rust runtime conversion supports `String`, accepting text, text-with-captures, and attribute values. Application code owns domain parsing and validation. Python supports Pydantic-compatible custom field types and validators without extending the Rust converter registry.

## Rust static locators

Contract attributes use `ys::locator::css(...)` and `ys::locator::text_literal(...)`. These create static declarations, so they do not use `?`. They support `.text()` and `.attribute(...)` where compatible. The regular `ys::css(...)` and other dynamic query constructors are used when authoring a Plan yourself.

Pin every field or omit every field locator. Partly pinned Contracts are rejected. The derive supports named, nongeneric structs; enums, generic structs, duplicate metadata, and empty IDs or descriptions are rejected.

The default field ID is its Rust name. Add `#[ys(id = "external_name", description = "...")]` to choose a different identity. That ID must match the Plan's output name.

## Use your own plan

Omit locators when selectors need to be chosen at runtime:

```rust
use std::error::Error;
use yosoi::prelude as ys;

#[derive(ys::Contract)]
#[ys(id = "heading", description = "The page heading")]
struct Heading {
    #[ys(description = "Heading text")]
    title: String,
}

fn main() -> Result<(), Box<dyn Error>> {
    let document = ys::Document::html("page.html", b"<h1>Hello</h1>".to_vec())?;
    let plan = ys::Plan::new([ys::output("title", ys::css("h1")?.text())?])?;
    let headings = Heading::extract(&document.locate(&plan))
        .validate()
        .require_all()?;
    for heading in headings {
        println!("{}", heading.title);
    }
    Ok(())
}
```

For a repeated Contract with a manually authored Plan, give the region the Contract's ID. Output IDs must match its field IDs. This preserves the association between a field and its record.

## Use a custom Policy

For pinned Contracts, evaluate `MyContract::plan()?` through `document.bind(&policy).locate(...)`, then pass that outcome to `MyContract::extract(...)`. The generated `MyContract::locate(&document)` convenience method uses the default document Policy.

## Rust schema and candidates

`MyContract::schema()?` exposes its ID, description, scope, and field metadata. `schema.identity()?` describes the schema's structure; changing descriptions alone does not change that identity. It does not fingerprint the selector plan. `MyContract::root_locator()` returns the static root declaration, or `None` for a page-level Contract. When every field is pinned, `plan()` returns the cached Plan and `locate()` provides the document convenience method.

The derive also generates a candidate companion, such as `ProductCandidate`. Before validation, `extracted.candidates()` exposes raw fields and `extracted.diagnostics()` reports extraction issues. Each `CandidateField` provides `values()`, `evidence()`, `len()`, and `is_absent()`.

`extract_with_limit(&located, maximum)` applies one bound to scanned regions and findings, matching findings, candidate records, per-field values, retained evidence, and diagnostics. It rejects excess work rather than returning the first `maximum` records. Extraction and validation have separate defaults; changing a locator limit does not automatically raise those later budgets.

Continue with [Validation](validation.md) to handle mixed valid and invalid records.

Use [Immediate Rust assertions](assertions.md) to check an existing Contract
observation inside a Flow with anonymous predicates.
