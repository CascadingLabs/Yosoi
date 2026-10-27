---
title: 'What is Yosoi?'
description: 'A unified toolkit for web scraping and browser automation.'
order: 0
---

# What is Yosoi?

## Overview

Yosoi is a unified toolkit for web scraping and browser automation.

Find pages, collect content, interact with websites, and extract structured data. Use it via the terminal, Rust, or Python.

> The name stands for You Only Scrape Once (Iteratively).

## Rationale

Web scraping often means stringing tools together for fetching pages, controlling browsers, extracting data, and checking results.

Yosoi brings those tasks together through one consistent interface. Start with a document, fetch a page when you need one, and use browser automation when a task requires interaction.

For your first project, see [Install](install.md). Continue with [Concepts](../concepts/index.md).

## Motivation

At first we (the CL team) didn't want to make a web scraping and automation framework, we just wanted a way to get structured and validated data from the public internet. However, without large wallets and incomplete solutions we started Yosoi.

The web is a messy place. We hope that yosoi can make it less so.

## Example

Extract a typed product from a small HTML document. The Contract defines its name and price, then validates the extracted values. This example uses local content, so it needs no browser or network connection.

### Rust

```rust
use std::error::Error;
use yosoi::prelude as ys;

// callout: Define a struct shaped data contract, descriptions are optional
#[derive(ys::Contract)]
#[ys(id = "product", description = "A product for sale")]
struct Product {
    #[ys(description = "Product name", locator = ys::locator::css("h1").text())]
    name: String,
    #[ys(description = "Price text", locator = ys::locator::css(".price").text())]
    price: String,
}

fn main() -> Result<(), Box<dyn Error>> {
    let document = ys::Document::html( // callout: using a HTML document for offline showcase, a document is returned from a ys::Request in future online examples.
        "product.html",
        b"<h1>Desk lamp</h1><p class='price'>$29.00</p>".to_vec(),
    )?;
    let located = Product::locate(&document)?;
    let products = Product::extract(&located).validate().require_all()?;

    assert_eq!(products.len(), 1);
    for product in products {
        assert_eq!(product.name, "Desk lamp");
        assert_eq!(product.price, "$29.00");
        println!("{} costs {}", product.name, product.price);
    }
    Ok(())
}
```

The Contract requires one name and one price field. `locate` finds the evidence from the HTML `document`, `extract` converts it into fields, and `validate` checks the record against the type and any constraints. `require_all` returns the products or reports the validation issues. The price remains the source text `$29.00`; application code owns numeric and currency interpretation.

### Python

```python
from typing import Any
from pydantic import field_validator
import yosoi as ys

# callout: Define a data contract to validate extracted documents
class Product(ys.Contract):
    """A product for sale."""
    # callout: a root matches article supplies one product's field scope
    root = ys.css("article.product")
    name: str = ys.Field("Product name", locator=ys.css("h2"), min_length=1)
    price: str = ys.Field("Advertised price", locator=ys.css(".price"))

    # callout: This validator inspects the extracted price before string validation
    @field_validator("price", mode="before")
    @classmethod
    def prepare_price(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            if value.startswith(("-$", "$-")):
                # raise ValueError("Product price must not be negative")
                print(f"{value} is negative!!!")
        return value

document = ys.Document.html(
    "product.html",
    b"""
    <main>
        <h1>Products</h1>
        <article class="product">
            <h2>Desk lamp</h2>
            <p class="price">$29.00</p>
        </article>
        <article class="product">
            <h2>Notebook</h2>
            <p class="price">-$7.50</p>
        </article>
    </main>
    """,
)
# callout: Python returns validated Product models automatically. Errors are explicit at runtime.
products = Product.extract(document)

for product in products:
    print(f"{product.name} costs {product.price}")

```

The Python Contract is a Pydantic model. Each article supplies one product, and `Product.extract(document)` runs validation automatically. Here the price stays a string. The validator prints a diagnostic for the notebook's negative price and still accepts it; raising `ValueError` instead would reject that record. The program then prints both products and their advertised prices.

These selectors match the HTML supplied in the example. Field descriptions explain the record; they do not automatically discover selectors. See [Contracts](../sdk/contracts.md) for optional fields and repeated records.
