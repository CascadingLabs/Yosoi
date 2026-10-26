---
title: 'Following the data'
description: 'Read the catalog as JSON and use XML and text Documents when the input calls for them.'
order: 7
---

# Following the data

The JavaScript shop gets its products from [a JSON endpoint](https://qscrape.dev/api/eshop/products/). The browser uses that response to build the cards we've been reading.

When the data we need is available directly, we can request that representation. We still create a Plan and locate values. The query and projection now need to match JSON rather than HTML.

## Example: read the catalog response

### Rust

```rust
use std::error::Error;
use yosoi::prelude as ys;

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let plan = ys::Plan::new([
        ys::output("name", ys::json_pointer("/data/0/name")?.value())?,
        ys::output("price", ys::json_pointer("/data/0/price")?.value())?,
        ys::output("names", ys::json_path("$.data[*].name")?.value())?,
    ])?;
    let response = ys::request::new("https://qscrape.dev/api/eshop/products/")
        .send()
        .await?;
    for document in response
        .attempts()
        .flat_map(|a| a.documents())
        .filter_map(|d| d.outcome().document())
    {
        println!("{:#?}", document.locate(&plan));
    }

    Ok(())
}
```

JSON Pointer selects a known path. `/data/0/price` identifies the first product's price. JSONPath's `[*]` selects every array item, so `$.data[*].name` reads all the product names.

`.value()` preserves JSON values. The lamp's price is the number `6800`, and the response declares that prices are USD cents. It is not the HTML text `$68.00`. Run `cargo run` and inspect the name, numeric price, and six name findings.

### Python

```python
import asyncio
import yosoi as ys


async def main():
    plan = ys.Plan(
        outputs=[
            ys.output("name", ys.json_pointer("/data/0/name").value()),
            ys.output("price", ys.json_pointer("/data/0/price").value()),
            ys.output("names", ys.json_path("$.data[*].name").value()),
        ]
    )
    response = await ys.request.new("https://qscrape.dev/api/eshop/products/").send()
    for document in response.documents:
        print(document.locate(plan).values())


asyncio.run(main())
```

JSON Pointer selects a known path. `/data/0/price` identifies the first product's price. JSONPath's `[*]` selects every array item, so `$.data[*].name` reads all the product names.

`.value()` preserves JSON values. The lamp's price is the integer `6800`, and the response declares that prices are USD cents. Run `uv run python main.py`: the printed values contain `Arc desk lamp`, `6800`, and the six catalog names.

## Choose the query for the representation

A CSS query selects tree elements. A JSON Pointer selects a value at a JSON path. They share the Plan vocabulary, but a Plan's queries and projections must be compatible with its Document.

Reading a numeric price does not perform currency conversion. Our earlier Contract retained the HTML price text. An application consuming this JSON should use the declared units when constructing its own price values.

## XML has names and namespaces

An XML input can look similar to HTML while following different parsing and naming rules. Here is a small controlled sitemap-style input pointing to the same lamp. The namespace URI identifies the vocabulary used by its elements.

## Example: read an XML link

These complete programs run offline.

### Rust

```rust
use std::error::Error;
use yosoi::prelude as ys;

fn main() -> Result<(), Box<dyn Error>> {
    let document = ys::Document::xml(
        "product-links",
        br#"
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://qscrape.dev/eshop/html/product/obj-001/</loc></url>
</urlset>
"#
        .to_vec(),
    )?;
    let links = ys::xpath("/s:urlset/s:url/s:loc")?
        .with_namespace("s", "http://www.sitemaps.org/schemas/sitemap/0.9")?;

    let plan = ys::Plan::new([ys::output("href", links.text())?])?;
    println!("{:#?}", document.locate(&plan));

    Ok(())
}
```

The query binds `s` to the namespace URI. That prefix belongs to the query; the document uses a default namespace. The finding contains the lamp's full URL. XML parsing is strict, so malformed XML reports a parsing failure rather than receiving HTML-style repair.

### Python

```python
import yosoi as ys

document = ys.Document.xml(
    "product-links",
    b"""
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://qscrape.dev/eshop/html/product/obj-001/</loc></url>
</urlset>
""",
)
links = ys.xpath("/s:urlset/s:url/s:loc").with_namespace(
    "s",
    "http://www.sitemaps.org/schemas/sitemap/0.9",
)
plan = ys.Plan(outputs=[ys.output("href", links.text())])
print(document.locate(plan).values())
```

The query binds `s` to the namespace URI. That prefix belongs to the query; the document uses a default namespace. The output is a list containing the lamp's full URL. XML parsing is strict, so malformed XML reports a parsing failure rather than receiving HTML-style repair.

## Plain text has no elements

Our application can also retain a cart summary as plain text. Literal and regex queries work on that decoded text, without an HTML tree.

## Example: read a text summary

These complete programs use a controlled summary of the cart we built earlier.

### Rust

```rust
use std::error::Error;
use yosoi::prelude as ys;

fn main() -> Result<(), Box<dyn Error>> {
    let document = ys::Document::text(
        "cart-summary",
        b"Arc desk lamp\nQuantity: 1\nTotal: $68.00".to_vec(),
    )?;

    let plan = ys::Plan::new([
        ys::output("name", ys::text_literal("Arc desk lamp")?.text())?,
        ys::output(
            "quantity",
            ys::regex(r"Quantity: (?P<quantity>\d+)")?.captures(["quantity"])?,
        )?,
    ])?;
    println!("{:#?}", document.locate(&plan));

    Ok(())
}
```

The literal query finds the product name. The regex retains `Quantity: 1` and a named capture containing `1`. Text findings preserve positions in the retained text, so the values remain connected to their source.

### Python

```python
import yosoi as ys

document = ys.Document.text(
    "cart-summary", b"Arc desk lamp\nQuantity: 1\nTotal: $68.00"
)
plan = ys.Plan(
    outputs=[
        ys.output("name", ys.text_literal("Arc desk lamp").text()),
        ys.output(
            "quantity", ys.regex(r"Quantity: (?P<quantity>\d+)").captures("quantity")
        ),
    ]
)
outcome = document.locate(plan)
print(outcome.values())
```

The literal query finds the product name. The regex retains `Quantity: 1` and a named capture containing `1`. The printed values are `['Arc desk lamp', 'Quantity: 1']`; the finding also keeps the named capture and source positions.

## Observe a response during browser work

Fetching a JSON URL directly and observing a browser's network response are different tasks. A browser Until expectation can wait for a particular response URL, method, status, and supported JSON fields. We'll use it when an interaction depends on that response.

The current SDK does not project `NetworkTree` into a usable Document. Use the supported response expectations and JSON Documents for these tasks.

## Next

[Building reusable browser recipes](actions-and-flows.md) combines the steps we already know and introduces scripts when a recipe needs them.
