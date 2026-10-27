---
title: 'Fetching our first page'
description: 'Fetch QScrape eShop over HTTP and read the lamp with the same locator Plan.'
order: 2
---

# Fetching our first page

We've been supplying HTML directly. Now let's get it from the website.

In [Making sense of HTML](documents-and-evidence.md), we selected the lamp's heading link and read its name and destination. The [eShop catalog](https://qscrape.dev/eshop/html/) puts those elements in its HTML response, so we can use the same Plan on the downloaded page.

This lesson makes a real network request. Yosoi's default Request uses **Direct HTTP**: it fetches the response without opening a browser or running the page's JavaScript.

## From a URL to a Document

A **Request** describes the page we want. Creating one does not contact the website. Sending it does.

Sending returns a **Response**. It keeps the acquisition attempts and the Documents they produced. Our default request makes one HTTP acquisition and asks for the response Document. Later, a browser request can produce other representations of the same page.

This is the same kind of Document we constructed from bytes earlier. The difference is where its input comes from: the HTTP response supplies it now.

## Example: fetch and read the lamp

### Rust

This program replaces `src/main.rs`. It uses Tokio to run the asynchronous request. If your project doesn't already have Tokio, add it with `cargo add tokio --features macros,rt`.

```rust
use std::error::Error;
use yosoi::prelude as ys;

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let product_link = ys::css(r#"article[data-product-id="obj-001"] h2 a"#)?;

    let plan = ys::Plan::new([
        ys::output("name", product_link.clone().text())?,
        ys::output("href", product_link.attribute("href")?)?,
    ])?;

    // callout: Creating a Request describes the URL. No network work happens yet.
    let request = ys::request::new("https://qscrape.dev/eshop/html/");
    // callout: send runs the HTTP acquisition and returns its Response.
    let response = request.send().await?;

    // callout: Collect the Documents retained across the response's acquisition attempts.
    let documents = response
        .attempts()
        .flat_map(|attempt| attempt.documents())
        .filter_map(|selected| selected.outcome().document());

    for document in documents {
        // callout: The Plan from our offline example now reads the downloaded Document.
        println!("{:#?}", document.locate(&plan));
    }

    Ok(())
}
```

The selector and the two outputs are unchanged. They still describe the lamp's name and `href`. `request.send().await` is the new work: it waits for Yosoi to acquire the page.

The `#[tokio::main]` attribute supplies the runtime that drives that asynchronous work. We use its single-threaded runtime for this example. The `?` propagates a request error if Yosoi cannot return a Response; problems during acquisition can also appear within a returned Response.

`flat_map` collects the document entries across the attempts, and `filter_map` keeps the retained Documents. The loop then applies our Plan and prints the findings. The Response still keeps the attempts, HTTP status, and document outcomes when we need to inspect how acquisition went.

Run `cargo run`. In the printed findings, `name` contains `Arc desk lamp`, and `href` contains `/eshop/html/product/obj-001/`.

### Python

This program replaces `main.py`. Python's standard `asyncio` module runs the asynchronous request.

```python
import asyncio
import yosoi as ys


async def main():
    product_link = ys.css('article[data-product-id="obj-001"] h2 a')

    plan = ys.Plan(
        outputs=[
            ys.output("name", product_link.text()),
            ys.output("href", product_link.attribute("href")),
        ]
    )

    # callout: Creating a Request describes the URL. No network work happens yet.
    request = ys.request.new("https://qscrape.dev/eshop/html/")
    # callout: send runs the HTTP acquisition and returns its Response.
    response = await request.send()

    for document in response.documents:
        # callout: The Plan from our offline example now reads the downloaded Document.
        print(document.locate(plan).values())


asyncio.run(main())
```

The selector and the two outputs are unchanged. They still describe the lamp's name and `href`. `await request.send()` is the new work: it waits for Yosoi to acquire the page.

`asyncio.run(main())` supplies the event loop that drives that asynchronous work. A preparation problem can raise an error before acquisition starts; problems during acquisition can also appear in the returned Response.

`response.documents` collects the Documents retained by the request. We apply the Plan to each one, and `.values()` collects the resulting values for printing. The Response still keeps the attempts, HTTP status, and document outcomes when we need to inspect how acquisition went.

Run `uv run python main.py`. The program prints `['Arc desk lamp', '/eshop/html/product/obj-001/']`: the name and link requested by our Plan.

## What arrived?

The Response keeps the HTTP status and acquisition details. Here, we print the findings to answer our immediate question: does the returned HTML contain the lamp's name and link?

The Document contains the page's HTML, including elements we didn't select. The Plan picks out the two values we asked for. Reading the lamp's `href` preserves its relative path.

A Response can retain a partial Document, and both examples include one when available. Its document outcome keeps the reasons for that incompleteness. A returned Response or an available Document alone does not establish that we obtained all the evidence our task needs.

## Where HTTP reaches its limit

The static catalog includes product data in its response. In [JavaScript eShop](https://qscrape.dev/eshop/javascript/), the initial HTML contains a loading shell. The browser runs JavaScript and loads the catalog afterward.

A successful HTTP request to that shop can therefore return HTML without the product values we're looking for. Next, [Using a browser](using-a-browser.md) introduces rendered Documents and compares running with and without a visible browser window.
