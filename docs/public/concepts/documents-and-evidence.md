---
title: 'Making sense of HTML'
description: 'Read product names, prices, and links from HTML bytes with Yosoi.'
order: 1
---

# Making sense of HTML

You have some HTML. Somewhere inside it is a product name and a price. Let's read them.

We'll use [QScrape's eShop](https://qscrape.dev/eshop/), a website we maintain for practicing scraping and browser automation. Its shops present the same products through static HTML, JavaScript, and browser verification. We'll follow one product through those versions as we learn Yosoi.

For now, all we need is a small piece of HTML from the [Arc desk lamp page](https://qscrape.dev/eshop/html/product/obj-001/):

```html
<h1 id="product-title">Arc desk lamp</h1>
<p class="shop-detail-price">$68.00</p>
```

The `h1` element contains the product name. The `p` element contains its price, and the `shop-detail-price` class identifies that paragraph. A full page has navigation, images, and other elements too. This excerpt keeps the two values we want in view.

We assume you already have Yosoi installed in your project. If you need it, start with [Install](../getting-started/install.md). This lesson runs entirely offline.

## Start with bytes

HTML is text encoded as bytes. Those bytes contain the tags, attributes, and text shown above. We can supply them directly in our program.

A Yosoi **Document** keeps the bytes together with a name and their format. Here, we tell Yosoi to interpret the bytes as HTML and name the Document `lamp`.

Once we have a Document, we need to tell Yosoi what to read. A **Plan** names the values we want and gives each one a locator:

- Select `h1`, read its text, and call the output `name`.
- Select `.shop-detail-price`, read its text, and call the output `price`.

These are CSS selectors. `h1` selects elements by their tag. The leading dot in `.shop-detail-price` selects elements by their class.

## Example: read the product

### Rust

Put this program in `src/main.rs` in your existing Rust application.

```rust
use std::error::Error;
use yosoi::prelude as ys;

fn main() -> Result<(), Box<dyn Error>> {
    let html = br#"
<h1 id="product-title">Arc desk lamp</h1>
<p class="shop-detail-price">$68.00</p>
"#;

    // callout: Name the Document so its findings can identify their source.
    let document = ys::Document::html("lamp", html.to_vec())?;

    // callout: Describe the outputs once so the Plan can be reused on compatible Documents.
    let plan = ys::Plan::new([
        ys::output("name", ys::css("h1")?.text())?,
        ys::output("price", ys::css(".shop-detail-price")?.text())?,
    ])?;

    // callout: Apply the Plan to this Document to produce findings.
    let outcome = document.locate(&plan);
    println!("{outcome:#?}");

    Ok(())
}
```

The `br#"…"#` literal holds the HTML bytes and lets us keep the quotation marks in the attributes. `Document::html` retains those bytes as source HTML.

The Plan describes what we want: the text inside `h1` as `name`, and the text inside `.shop-detail-price` as `price`. `.text()` asks for the element's text content, including text inside its children.

`css(...)` and `Plan::new(...)` describe the work. `document.locate(&plan)` runs it against these HTML bytes. That separation lets us keep the Plan and change the Document, for example when we fetch another product page.

`println!` uses Rust's debug formatting to show the outcome and its findings.

Run `cargo run`. In the output's `findings`, look for the output IDs `name` and `price`, with the text values `Arc desk lamp` and `$68.00`. The other fields describe where those values came from.

### Python

Save this program as `main.py` in your existing Python project.

```python
import yosoi as ys

html = b"""
<h1 id="product-title">Arc desk lamp</h1>
<p class="shop-detail-price">$68.00</p>
"""

# callout: Name the Document so its findings can identify their source.
document = ys.Document.html("lamp", html)

# callout: Describe the outputs once so the Plan can be reused on compatible Documents.
plan = ys.Plan(
    outputs=[
        ys.output("name", ys.css("h1").text()),
        ys.output("price", ys.css(".shop-detail-price").text()),
    ]
)

# callout: Apply the Plan to this Document to produce findings.
outcome = document.locate(plan)

for finding in outcome.findings:
    print(f"{finding.output_id}: {finding.value}")
```

The `b"""…"""` literal holds the HTML as bytes. `Document.html` retains that input as source HTML.

The Plan describes what we want: the text inside `h1` as `name`, and the text inside `.shop-detail-price` as `price`. `.text()` asks for the element's text content, including text inside its children.

`ys.css(...)` and `ys.Plan(...)` describe the work. `document.locate(plan)` runs it against these HTML bytes. That separation lets us keep the Plan and change the Document, for example when we fetch another product page.

Each finding carries an output name and a value. The loop prints them together.

Run `uv run python main.py`. The program prints `name: Arc desk lamp` and `price: $68.00`.

## Example: same Plan, different HTML

Here, we reuse the first example's Plan on two new Documents: one with a different price, and one without a price paragraph.

### Rust

These lines continue the first program, inside `main` before `Ok(())`.

```rust
let updated = ys::Document::html(
    "lamp-new-price",
    br#"<h1 id="product-title">Arc desk lamp</h1>
<p class="shop-detail-price">$70.00</p>"#
        .to_vec(),
)?;
// callout: This is where the Plan earns its keep: reuse the same selectors and output names on new HTML.
println!("Updated price:\n{:#?}", updated.locate(&plan));

let without_price = ys::Document::html(
    "lamp-no-price",
    br#"<h1 id="product-title">Arc desk lamp</h1>"#.to_vec(),
)?;
println!("Missing price:\n{:#?}", without_price.locate(&plan));
```

The first outcome contains the same name and the new price, `$70.00`. The second contains only the name finding because its HTML has no price paragraph.

### Python

These lines continue the first program after its printing loop.

```python
updated = ys.Document.html(
    "lamp-new-price",
    b"""<h1 id="product-title">Arc desk lamp</h1>
<p class="shop-detail-price">$70.00</p>""",
)
print("Updated price:")
# callout: This is where the Plan earns its keep: reuse the same selectors and output names on new HTML.
for finding in updated.locate(plan).findings:
    print(f"{finding.output_id}: {finding.value}")

without_price = ys.Document.html(
    "lamp-no-price",
    b'<h1 id="product-title">Arc desk lamp</h1>',
)
print("Missing price:")
for finding in without_price.locate(plan).findings:
    print(f"{finding.output_id}: {finding.value}")
```

Under `Updated price:`, the output is `name: Arc desk lamp` and `price: $70.00`. Under `Missing price:`, it contains only `name: Arc desk lamp` because that HTML has no price paragraph.

## Read a product link

So far, we've read text from a product page. The [eShop catalog](https://qscrape.dev/eshop/html/) contains several product cards, each with a name that links to its product page. Here's an excerpt with the lamp and a mug:

```html
<article data-product-id="obj-001">
  <h2 class="shop-product-name">
    <a href="/eshop/html/product/obj-001/">Arc desk lamp</a>
  </h2>
</article>
<article data-product-id="obj-002">
  <h2 class="shop-product-name">
    <a href="/eshop/html/product/obj-002/">Loop ceramic mug</a>
  </h2>
</article>
```

The name is text inside the `a` element. Its destination is the value of the `href` attribute. We can select that element once and ask for both values.

The selector `article[data-product-id="obj-001"] h2 a` starts with the lamp's card, identified by its `data-product-id`. It then selects links inside an `h2` within that card. The mug also has a heading and link, but its card has a different product ID.

## Example: read the name and destination

### Rust

This is a complete program. It replaces `src/main.rs` and still runs entirely offline.

```rust
use std::error::Error;
use yosoi::prelude as ys;

fn main() -> Result<(), Box<dyn Error>> {
    let html = br#"
<article data-product-id="obj-001">
    <h2 class="shop-product-name">
        <a href="/eshop/html/product/obj-001/">Arc desk lamp</a>
    </h2>
</article>
<article data-product-id="obj-002">
    <h2 class="shop-product-name">
        <a href="/eshop/html/product/obj-002/">Loop ceramic mug</a>
    </h2>
</article>
"#;

    let document = ys::Document::html("catalog", html.to_vec())?;
    // callout: Select the lamp's heading link, leaving the mug's link out.
    let product_link = ys::css(r#"article[data-product-id="obj-001"] h2 a"#)?;

    let plan = ys::Plan::new([
        ys::output("name", product_link.clone().text())?,
        // callout: The same selected element supplies a different value: its href attribute.
        ys::output("href", product_link.attribute("href")?)?,
    ])?;

    let outcome = document.locate(&plan);
    println!("{outcome:#?}");

    Ok(())
}
```

`product_link` describes which element to select. The two outputs reuse that selection: `.text()` asks for its text content, and `.attribute("href")` asks for its destination. Rust's `clone()` copies the query declaration so each output can use it; it does not copy the Document.

The Plan holds those choices until `document.locate(&plan)` evaluates them against the catalog bytes. Another catalog with the same structure can use this Plan too.

Run `cargo run`. In the findings, `name` contains `Arc desk lamp`, and `href` contains `/eshop/html/product/obj-001/`. The href finding also records the attribute name. The mug produces no findings because the selector identifies the lamp's card.

### Python

This is a complete program. It replaces `main.py` and still runs entirely offline.

```python
import yosoi as ys

html = b"""
<article data-product-id="obj-001">
    <h2 class="shop-product-name">
        <a href="/eshop/html/product/obj-001/">Arc desk lamp</a>
    </h2>
</article>
<article data-product-id="obj-002">
    <h2 class="shop-product-name">
        <a href="/eshop/html/product/obj-002/">Loop ceramic mug</a>
    </h2>
</article>
"""

document = ys.Document.html("catalog", html)
# callout: Select the lamp's heading link, leaving the mug's link out.
product_link = ys.css('article[data-product-id="obj-001"] h2 a')
plan = ys.Plan(
    outputs=[
        ys.output("name", product_link.text()),
        # callout: The same selected element supplies a different value: its href attribute.
        ys.output("href", product_link.attribute("href")),
    ]
)

outcome = document.locate(plan)
for finding in outcome.findings:
    print(f"{finding.output_id}: {finding.value}")
```

`product_link` describes which element to select. The two outputs reuse that selection: `.text()` asks for its text content, and `.attribute("href")` asks for its destination. Both create declarations from the same query.

The Plan holds those choices until `document.locate(plan)` evaluates them against the catalog bytes. Another catalog with the same structure can use this Plan too.

Run `uv run python main.py`. The program prints `name: Arc desk lamp` and `href: /eshop/html/product/obj-001/`. The mug produces no findings because the selector identifies the lamp's card.

## Keep the source with the value

A finding keeps more than the value we asked for. It also identifies the Document, the named output, and the location of the evidence within the Document. The Rust debug output shows those details. Python's printing loop above shows only the output name and value, but the finding retains its source too.

The `href` we read is a relative path. On this site, it points to `https://qscrape.dev/eshop/html/product/obj-001/`. Reading the attribute preserves its value; it doesn't visit that page.

## Next

Next, [Fetching our first page](discovery-and-acquisition.md) replaces the embedded HTML with an HTTP response and reuses our Plan.
