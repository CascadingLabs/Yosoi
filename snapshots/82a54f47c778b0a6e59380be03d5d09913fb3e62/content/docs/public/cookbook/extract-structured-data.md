---
title: Extract structured data
description: Turn a controlled product document into checked typed records.
order: 1
---

# Extract structured data

A catalog task needs a product name, a USD price and an optional link. Start with controlled local HTML so the record and its evidence are easy to inspect.

1. Define one typed record for each product region.
2. Locate the evidence for its fields.
3. Extract candidates without discarding their provenance.
4. Validate cardinality and conversion.
5. Require accepted records, or keep records and issues together for partial acceptance.

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
    #[ys(description = "Price in USD", locator = ys::locator::css(".price").text())]
    price: ys::Money,
    #[ys(description = "Optional product link", locator = ys::locator::css("a").attribute("href"))]
    href: Option<String>,
}

fn main() -> Result<(), Box<dyn Error>> {
    let document = ys::Document::html(
        "catalog.html",
        b"<article><h2>Tea</h2><span class='price'>$4.50</span></article>".to_vec(),
    )?;
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
    price: ys.Money = ys.Field("Price in USD", locator=ys.css(".price"))
    href: str | None = ys.Field("Optional product link", locator=ys.css("a").attribute("href"))

document = ys.Document.html(
    "catalog.html",
    "<article><h2>Tea</h2><span class='price'>$4.50</span></article>",
)
products = ys.extract(document, Product).validate().require_all()
for product in products:
    assert product.name == "Tea"
    assert product.price.minor_units == 450
    assert product.href is None
    print(f"{product.name} costs {product.price}")
```

The model defines the same fields and cardinality. Rust validates the candidates, then Python exposes typed records. The checks show a 450-cent price and an absent optional link.

## Adapt the task

The selectors describe the controlled fixture above. On another site, bind a supported Plan to the actual evidence. Natural-language descriptions explain fields but do not automatically discover elements.

The missing link is valid because the field is optional. A required field that is missing or cannot convert produces an issue. Keep the outcome when you need accepted records and rejected candidates together.

See [Contracts](../sdk/contracts.md), [Validation](../sdk/validation.md), and [Choose a locator](choose-a-locator.md).
