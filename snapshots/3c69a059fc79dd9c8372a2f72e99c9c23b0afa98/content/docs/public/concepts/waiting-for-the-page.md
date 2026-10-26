---
title: 'Waiting for the page'
description: 'Wait for the lamp to arrive before reading the browser page.'
order: 4
---

# Waiting for the page

Our browser Request could capture JavaScript eShop while it was still loading. We knew which product we wanted, but we hadn't told Yosoi when the page was ready to read.

Now we'll wait for the lamp's card. When it appears, we'll read the same name and link as before.

## Describe the sequence

A **Flow** is an ordered recipe of browser operations. This one has two steps: navigate to the shop, then wait for an element with the lamp's product ID.

The wait has a five-second limit. It can finish as soon as the card exists. We're waiting for evidence of readiness, rather than choosing a delay and hoping the page has finished loading.

If navigation or the wait fails, this recipe stops. Its later work depends on reaching the product.

## Example: wait and read

These programs use the browser-enabled Yosoi installation and Tokio or asyncio from [Using a browser](using-a-browser.md).

### Rust

```rust
use std::error::Error;
use yosoi::prelude as ys;
use ys::policy::{Continuation, StopScope};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let product_link = ys::css(r#"article[data-product-id="obj-001"] h2 a"#)?;

    let plan = ys::Plan::new([
        ys::output("name", product_link.clone().text())?,
        ys::output("href", product_link.attribute("href")?)?,
    ])?;

    let recipe = ys::flow::new([
        ys::action::navigate("https://qscrape.dev/eshop/javascript/"),
        // callout: Wait up to five seconds for the lamp's card to exist.
        ys::action::wait_until(
            ys::flow::Condition::Exists {
                selector: r#"article[data-product-id="obj-001"]"#.into(),
            },
            5_000,
        ),
    ])
    .on_failure(Continuation::Stop(StopScope::Invocation));

    let outcome = recipe.invoke().await?;
    outcome.require_completed()?;

    let html = outcome
        .steps
        .last()
        .and_then(|step| step.receipt.observation.as_ref())
        .and_then(|observation| observation.html.as_ref());
    if let Some(html) = html {
        let document = ys::Document::html("ready-shop", html.as_bytes().to_vec())?;
        println!("{:#?}", document.locate(&plan));
    }
    println!("Flow: {:?}", outcome.terminal);

    Ok(())
}
```

`flow::new` describes the sequence; `invoke` runs it. The invocation manages the temporary browser resources. `require_completed()` reports an error if the recipe did not complete successfully, including its required wait.

Each executed step has a **receipt** describing what Yosoi observed. The final wait's receipt can retain HTML from the ready page. We construct a local Document from that markup and apply our Plan. The optional access handles a receipt that does not carry HTML.

Run `cargo run`. The findings contain `Arc desk lamp` and `/eshop/javascript/product/obj-001/`, followed by the completed Flow state.

### Python

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

    recipe = ys.flow(
        [
            ys.navigate("https://qscrape.dev/eshop/javascript/"),
            # callout: Wait up to five seconds for the lamp's card to exist.
            ys.wait_until(
                ys.exists('article[data-product-id="obj-001"]'), timeout_ms=5_000
            ),
        ],
        on_failure=ys.policy.Stop(scope="invocation"),
    )

    outcome = await recipe.invoke()
    outcome.require_completed()

    observation = outcome.steps[-1].receipt.observation
    if observation is not None and observation.html is not None:
        document = ys.Document.html("ready-shop", observation.html)
        print(document.locate(plan).values())
    print("Flow:", outcome.terminal)


asyncio.run(main())
```

`ys.flow` describes the sequence; `invoke` runs it. The invocation manages the temporary browser resources. `require_completed()` raises if the recipe did not complete successfully, including its required wait.

Each executed step has a **receipt** describing what Yosoi observed. The final wait's receipt can retain HTML from the ready page. We construct a local Document from that markup and apply our Plan. The condition handles a receipt that does not carry HTML.

Run `uv run python main.py`. It prints `['Arc desk lamp', '/eshop/javascript/product/obj-001/']` and `Flow: completed`.

## Readiness belongs to the task

This wait establishes that the lamp's card exists. It doesn't establish that every image has loaded or that the whole shop has finished all its background work. We chose the condition needed to read this product.

The retained HTML is a snapshot of the observed page. Re-evaluating it creates coordinates within that saved markup. We'll use browser operations when we need to interact with the live page.

## Next

[Building a product record](contracts-and-validation.md) turns the name and price into values our application can use.
