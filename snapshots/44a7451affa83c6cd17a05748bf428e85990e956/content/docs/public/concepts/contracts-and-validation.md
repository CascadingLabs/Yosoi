---
title: 'Building a product record'
description: 'Turn product evidence into typed records and inspect rejected candidates.'
order: 5
---

# Building a product record

We can read a name and a price from HTML. Our application now needs a product, with a name it can display and a price it can use without parsing a string every time.

A **Contract** describes that record: its fields, their types, and the evidence that supplies them. We'll start with the same lamp HTML, so the record's shape is easy to see. These examples run offline.

## Example: one typed product

### Rust

```rust
use std::error::Error;
use yosoi::prelude as ys;

#[derive(Debug, ys::Contract)]
#[ys(id = "product", description = "A shop product")]
struct Product {
    #[ys(description = "Product name", locator = ys::locator::css("h1").text())]
    name: String,
    #[ys(description = "Price text", locator = ys::locator::css(".shop-detail-price").text())]
    price: String,
}

fn main() -> Result<(), Box<dyn Error>> {
    let document = ys::Document::html(
        "lamp",
        br#"
<h1>Arc desk lamp</h1>
<p class="shop-detail-price">$68.00</p>
"#
        .to_vec(),
    )?;
    let located = Product::locate(&document)?;
    // callout: Extract candidates, validate their values, then require every candidate to be accepted.
    let products = Product::extract(&located).validate().require_all()?;
    for product in products {
        println!(
            "{}: {}", product.name, product.price
        );
    }

    Ok(())
}
```

The derived Contract connects its field names to a locator Plan. Rust locates the evidence, extracts candidates, validates them, and then applies `require_all()` to obtain accepted values.

`Product` is a Rust type, but the incoming HTML is still external data. Runtime validation establishes that the located fields have the required shape and can become the declared values. Here, the price remains the source text `$68.00`.

Run `cargo run`. It prints `Arc desk lamp: $68.00`.

### Python

```python
import yosoi as ys


class Product(ys.Contract):
    """A shop product."""

    name: str = ys.Field("Product name", locator=ys.css("h1"))
    price: str = ys.Field("Price text", locator=ys.css(".shop-detail-price"))


document = ys.Document.html(
    "lamp",
    b"""
<h1>Arc desk lamp</h1>
<p class="shop-detail-price">$68.00</p>
""",
)
# callout: Python extracts and constructs validated Pydantic models in this call.
products = Product.extract(document)
for product in products:
    print(f"{product.name}: {product.price}")
```

The Contract is a Pydantic model. `Product.extract(document)` locates the evidence and constructs validated Product instances automatically. The price remains the source text `$68.00`.

Annotations give the record a readable shape and help static tools check how our code uses it. Pydantic performs the runtime construction and validation of the external values. An annotation on its own would not validate downloaded data.

Run `uv run python main.py`. It prints `Arc desk lamp: $68.00`.

## Keep each product together

A catalog contains repeated cards. Each name and price must stay attached to its own card. A Contract's `root` selects one region per record, and its field queries run inside that region.

We'll use two shortened eShop cards. The optional link shows how to describe a value that may be absent.

## Example: a small catalog

### Rust

```rust
use std::error::Error;
use yosoi::prelude as ys;

#[derive(Debug, ys::Contract)]
#[ys(id = "product", description = "A catalog product", root = ys::locator::css("article"))]
struct Product {
    #[ys(description = "Name", locator = ys::locator::css("h2").text())]
    name: String,
    #[ys(description = "Price text", locator = ys::locator::css(".shop-price").text())]
    price: String,
    #[ys(description = "Optional link", locator = ys::locator::css("h2 a").attribute("href"))]
    href: Option<String>,
}

fn main() -> Result<(), Box<dyn Error>> {
    let document = ys::Document::html(
        "catalog",
        br#"
<article><h2><a href="/eshop/html/product/obj-001/">Arc desk lamp</a></h2>
<span class="shop-price">$68.00</span></article>
<article><h2>Loop ceramic mug</h2><span class="shop-price">$24.00</span></article>
"#
        .to_vec(),
    )?;
    let products = Product::extract(&Product::locate(&document)?)
        .validate()
        .require_all()?;
    for product in products {
        println!(
            "{}: {}, link {:?}",
            product.name, product.price, product.href
        );
    }

    Ok(())
}
```

Each `article` supplies one candidate. Both `String` fields require one value each; `Option<String>` accepts an absent link. The mug's name remains attached to its own $24.00 price even though it has no link in this controlled input.

Run `cargo run`. It produces the lamp and mug, with a link for the lamp and `None` for the mug. Rust's native Contract conversion currently supports String values; richer scalar types need a separately supported conversion path.

### Python

```python
import yosoi as ys


class Product(ys.Contract):
    """A catalog product."""

    root = ys.css("article")
    name: str = ys.Field("Name", locator=ys.css("h2"))
    price: str = ys.Field("Price text", locator=ys.css(".shop-price"))
    href: str | None = ys.Field(
        "Optional link", locator=ys.css("h2 a").attribute("href"), default=None
    )


document = ys.Document.html(
    "catalog",
    b"""
<article><h2><a href="/eshop/html/product/obj-001/">Arc desk lamp</a></h2>
<span class="shop-price">$68.00</span></article>
<article><h2>Loop ceramic mug</h2><span class="shop-price">$24.00</span></article>
""",
)
products = Product.extract(document)
for product in products:
    print(f"{product.name}: {product.price}, link {product.href}")
```

Each `article` supplies one candidate. The name and price are required. `default=None` allows an absent optional link; the nullable annotation describes the value that can be returned.

Run `uv run python main.py`. It produces the lamp and mug, with a link for the lamp and `None` for the mug. Python also supports Pydantic-compatible custom field types and validators when the record needs application-specific rules.

## Inspect a rejected record

A missing required price is different from an absent optional link. The next input deliberately removes the mug's price. This modified fixture demonstrates rejection without depending on a broken live page.

## Example: keep accepted and rejected candidates

### Rust

These lines use the catalog program's Product type. They replace the body of `main` before its final `Ok(())`.

```rust
let document = ys::Document::html(
    "catalog-with-missing-price",
    br#"
<article><h2>Arc desk lamp</h2><span class="shop-price">$68.00</span></article>
<article><h2>Loop ceramic mug</h2></article>
"#
    .to_vec(),
)?;
let located = Product::locate(&document)?;
let report = Product::extract(&located).validate();
println!("{report:#?}");
```

The printed summary has `record_count: 1` and `issue_count: 1`. The report retains the accepted lamp record and the rejected mug's candidate evidence. Calling `require_all()` would return an error for this mixed result.

### Python

These lines use the Product class from the catalog program and replace the code after its definition.

```python
document = ys.Document.html(
    "catalog-with-missing-price",
    b"""
<article><h2>Arc desk lamp</h2><span class="shop-price">$68.00</span></article>
<article><h2>Loop ceramic mug</h2></article>
""",
)
report = Product.extract_report(document)
print("Accepted:", [record.value.name for record in report.records])
print("Rejected:", len(report.issues))
```

The report retains an accepted lamp model and an issue for the mug's missing price. It prints `Accepted: ['Arc desk lamp']` and `Rejected: 1`. Ordinary `Product.extract(document)` uses strict acceptance by default and raises for rejected candidates.

## Decide what the task accepts

A valid record establishes its declared field requirements. Our application still decides whether a missing optional link is useful, whether it accepts part of a catalog, and whether it needs at least one record.

Rust's `require_all()` accepts a complete empty result. Python's extraction policy also defaults to a minimum of zero records; `ExtractionPolicy(minimum_records=1)` expresses a task that needs a product. Keep record validity separate from the count your task requires.

## Example: check a minimum count

These short variations reuse the catalog's Product type and supply an empty catalog.

### Rust

Add these lines inside the catalog program's `main`, before `Ok(())`.

```rust
let empty = ys::Document::html("empty-catalog", b"<main></main>".to_vec())?;
let products = Product::extract(&Product::locate(&empty)?)
    .validate()
    .require_all()?;
println!("Minimum met: {}", products.len() >= 1);
```

This prints `Minimum met: false`. `require_all()` accepts the empty result because no candidate was rejected. The length comparison expresses the application's minimum; use that condition to stop dependent work when the task requires a product.

### Python

Replace the code after the catalog program's Product definition with these lines.

```python
from yosoi.contracts import ExtractionPolicy

empty = ys.Document.html("empty-catalog", b"<main></main>")
report = Product.extract_report(empty, policy=ExtractionPolicy(minimum_records=1))
print("Minimum met:", report.meets_minimum_records)
```

This prints `Minimum met: False`. The report retains the unmet minimum without raising. Calling `report.require_all()`, or using `Product.extract(empty, policy=ExtractionPolicy(minimum_records=1))`, would raise instead of returning an empty list.

## Next

We'll use these records when [adding a product to the cart](adding-to-the-cart.md), so the interaction has a result we can check.
