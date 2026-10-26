---
title: 'Using a browser'
description: 'Acquire a rendered Document and choose headless or headful execution.'
order: 3
---

# Using a browser

In [Fetching our first page](discovery-and-acquisition.md), an HTTP request gave us the catalog's HTML. That worked because the static shop included its products in the response.

[JavaScript eShop](https://qscrape.dev/eshop/javascript/) loads its catalog in the browser. Its initial HTML contains a loading shell. The browser runs the page's JavaScript, requests the product data, and adds the product cards to the page.

We need to read the page the browser builds. We also need to distinguish opening that page from waiting for its products to arrive.

## Source HTML and the DOM

The **DOM** is the browser's tree of the page's elements and text. The browser builds it from HTML, and JavaScript can change it afterward.

The source response and the current DOM can therefore contain different information. A product card added by JavaScript appears in the DOM even though it wasn't in the original HTML response.

Yosoi can capture that tree as a **rendered DOM Document**. Like our earlier Documents, it is a retained snapshot. The browser can continue changing the page; the captured Document keeps the evidence from its own capture.

Our CSS selector still has the same job: find the lamp's heading link. The Plan still asks for its name and `href`. We're changing how we obtain the Document.

## Example: request a rendered Document

Both examples need compatible regular Chrome or Chromium Stable installed. If several browsers are installed, the `CHROME` environment variable can select the executable to use. The first run uses headless mode, which does not open a visible browser window.

### Rust

This program replaces `src/main.rs`. Enable Yosoi's `browser` feature in your existing project with `cargo add yosoi --features browser`. It also uses Tokio with the `macros` and `rt` features from the previous lesson.

```rust
use std::error::Error;
use yosoi::prelude as ys;
use ys::policy::{Acquisition, BrowserMode, DocumentRequest, Page};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let product_link = ys::css(r#"article[data-product-id="obj-001"] h2 a"#)?;

    let plan = ys::Plan::new([
        ys::output("name", product_link.clone().text())?,
        ys::output("href", product_link.attribute("href")?)?,
    ])?;

    let mut policy = ys::Policy::default();
    // callout: Choose browser execution and explicitly ask for its rendered DOM.
    policy.page = Page::new(vec![
        Acquisition::Browser(BrowserMode::Headless)
            .documents([DocumentRequest::RenderedDom]),
    ])?;

    let response = ys::request::new("https://qscrape.dev/eshop/javascript/")
        .bind(&policy)
        .send()
        .await?;

    let documents = response
        .attempts()
        .flat_map(|attempt| attempt.documents())
        .filter_map(|selected| selected.outcome().document());
    for document in documents {
        println!("{:#?}", document.locate(&plan));
    }

    Ok(())
}
```

A **Policy** describes how Yosoi should perform the request. Here, its page configuration selects one headless browser acquisition. `.documents([DocumentRequest::RenderedDom])` asks for the rendered tree. Choosing a browser alone would use its default response Document, so the representation is an explicit choice.

`.bind(&policy)` attaches those choices to the Request before `.send()` runs it. We then apply the same Plan to the retained Documents, just as we did for HTTP.

Run `cargo run`. The output shows the locator outcome for the captured DOM. If the capture contains the lamp, its findings contain the name and link. If the catalog hasn't arrived yet, there can be no product findings. We'll explain that timing below.

### Python

This program replaces `main.py`. The Python package includes browser support; regular Chrome or Chromium is a separate installation.

```python
import asyncio
import yosoi as ys
from yosoi.policy import Acquisition, Page, Policy


async def main():
    product_link = ys.css('article[data-product-id="obj-001"] h2 a')

    plan = ys.Plan(
        outputs=[
            ys.output("name", product_link.text()),
            ys.output("href", product_link.attribute("href")),
        ]
    )

    # callout: Choose browser execution and explicitly ask for its rendered DOM.
    policy = Policy(
        page=Page(
            acquisitions=[
                Acquisition.browser("headless").with_documents(["rendered_dom"]),
            ]
        )
    )
    response = (
        await ys.request.new("https://qscrape.dev/eshop/javascript/")
        .bind(policy)
        .send()
    )

    for document in response.documents:
        print(document.locate(plan).values())


asyncio.run(main())
```

A **Policy** describes how Yosoi should perform the request. Here, its page configuration selects one headless browser acquisition. `.with_documents(["rendered_dom"])` asks for the rendered tree. Choosing a browser alone would use its default response Document, so the representation is an explicit choice.

`.bind(policy)` attaches those choices to the Request before `send()` runs it. We then apply the same Plan to the retained Documents, just as we did for HTTP.

Run `uv run python main.py`. If the capture contains the lamp, the output is `['Arc desk lamp', '/eshop/javascript/product/obj-001/']`. If the catalog hasn't arrived yet, the retained DOM can produce `[]` for this Plan. We'll explain that timing below.

## Headless and headful

Both modes run a browser and can execute the page's JavaScript. The difference is whether there is a visible browser window.

| Mode     | Window            | Useful when                                                        |
| -------- | ----------------- | ------------------------------------------------------------------ |
| Headless | No visible window | Running unattended work or on a machine without a desktop          |
| Headful  | Visible window    | Watching the page, debugging an interaction, or involving a person |

Headful execution needs a working display. Headless execution still needs a browser; it isn't an HTTP-only request.

## Example: show the browser window

These declarations replace the Policy configuration in the preceding program, before sending the Request. The Plan, URL, and requested Document stay the same.

### Rust

```rust
policy.page = Page::new(vec![
    Acquisition::Browser(BrowserMode::Headful)
        .documents([DocumentRequest::RenderedDom]),
])?;
```

`BrowserMode::Headful` asks for a visible window. The Request manages its browser resources and closes them when acquisition finishes, so this example's window may be brief.

### Python

```python
policy = Policy(
    page=Page(
        acquisitions=[
            Acquisition.browser("headful").with_documents(["rendered_dom"]),
        ]
    )
)
```

`"headful"` asks for a visible window. The Request manages its browser resources and closes them when acquisition finishes, so this example's window may be brief.

## A browser can capture too early

The JavaScript shop has several steps between opening the page and showing the lamp: JavaScript starts, the catalog request finishes, and the shop updates its DOM.

For the rendered-DOM request above, the standard adapter captures after the browser's `DOMContentLoaded` event. That event does not establish that the catalog request or the shop's update has finished. A capture can therefore contain the loading shell while the product cards are still on their way. The Plan then has no product values to return.

Headful mode changes whether we can see the browser. It does not add a wait for the catalog. We need to express what evidence makes the page ready for our task.

## Next

Next, [Waiting for the page](waiting-for-the-page.md) introduces our first browser Flow: navigate, wait for the lamp's card, and inspect the result.
