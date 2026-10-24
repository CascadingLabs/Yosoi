---
title: 'Keeping the browser open'
description: 'Share browser state across separate recipes with a Session and exclusive Work.'
order: 9
---

# Keeping the browser open

Our managed Flow opened the shop, changed the cart, and closed the resources it owned. Sometimes separate operations need to share that state.

A **Session** owns the browser lifetime. **Work** gives one caller exclusive control of a tab. We can finish one recipe, release its Work, and acquire Work again while the Session keeps the cart state alive.

## Example: add now, inspect later

These complete programs run two separate recipes in one Session. The first adds the lamp. The second opens the cart and reads its name. They use the browser-enabled installation from earlier lessons.

### Rust

```rust
use std::error::Error;
use yosoi::prelude as ys;
use ys::policy::{Continuation, StopScope};

async fn run_recipe(
    browser: &ys::Session,
    recipe: &ys::Flow,
) -> Result<ys::flow::FlowOutcome, Box<dyn Error>> {
    let work = browser.work().await?;
    let attempt = recipe.with_lease(&work).invoke().await;
    let released = work.release().await;
    if let Err(error) = &released {
        eprintln!("Work cleanup: {error}");
    }

    let outcome = attempt?;
    released?;
    outcome.require_completed()?;
    Ok(outcome)
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let add = ys::flow::new([
        ys::action::navigate("https://qscrape.dev/eshop/javascript/"),
        ys::action::wait_until(
            ys::flow::Condition::Exists {
                selector: r#"article[data-product-id="obj-001"]"#.into(),
            },
            5_000,
        ),
        ys::action::click(r#"article[data-product-id="obj-001"] button"#),
    ])
    .on_failure(Continuation::Stop(StopScope::Invocation));
    let inspect = ys::flow::new([
        ys::action::navigate("https://qscrape.dev/eshop/javascript/cart/"),
        ys::action::wait_until(
            ys::flow::Condition::Exists {
                selector: r#"[data-shop-part="cart-line"][data-product-id="obj-001"]"#
                    .into(),
            },
            5_000,
        ),
    ])
    .on_failure(Continuation::Stop(StopScope::Invocation));

    let browser = ys::session::new().acquire().await?;
    let result: Result<(), Box<dyn Error>> = async {
        run_recipe(&browser, &add).await?;
        // callout: The first Work was released, but the Session still owns the cart state.
        let outcome = run_recipe(&browser, &inspect).await?;
        let html = outcome
            .steps
            .last()
            .and_then(|s| s.receipt.observation.as_ref())
            .and_then(|o| o.html.as_ref());
        if let Some(html) = html {
            let document =
                ys::Document::html("retained-cart", html.as_bytes().to_vec())?;
            let plan = ys::Plan::new([ys::output(
                "name",
                ys::css(".shop-cart-item-name")?.text(),
            )?])?;
            println!("{:#?}", document.locate(&plan));
        }
        Ok(())
    }
    .await;
    let closed = browser.close().await;
    if let Err(error) = &closed {
        eprintln!("Session cleanup: {error}");
    }
    result?;
    closed?;

    Ok(())
}
```

The local `run_recipe` helper acquires Work, lends it to the recipe, and attempts release before propagating an invocation error. The main function attempts Session close even when its dependent work fails.

The second recipe sees the lamp left by the first. Run `cargo run`: the printed findings contain `Arc desk lamp`. Releasing Work ended control of the tab; closing the Session ends the browser lifetime owned by this program.

### Python

```python
import asyncio
import yosoi as ys


async def main():
    add = ys.flow(
        [
            ys.navigate("https://qscrape.dev/eshop/javascript/"),
            ys.wait_until(
                ys.exists('article[data-product-id="obj-001"]'), timeout_ms=5_000
            ),
            ys.click('article[data-product-id="obj-001"] button'),
        ],
        on_failure=ys.policy.Stop(scope="invocation"),
    )
    inspect = ys.flow(
        [
            ys.navigate("https://qscrape.dev/eshop/javascript/cart/"),
            ys.wait_until(
                ys.exists('[data-shop-part="cart-line"][data-product-id="obj-001"]'),
                timeout_ms=5_000,
            ),
        ],
        on_failure=ys.policy.Stop(scope="invocation"),
    )

    async with ys.session() as browser:
        async with browser.work() as work:
            (await add.invoke(work)).require_completed()
        # callout: The first Work was released, but the Session still owns the cart state.
        async with browser.work() as work:
            outcome = await inspect.invoke(work)
            outcome.require_completed()
            observation = outcome.steps[-1].receipt.observation
            if observation is not None and observation.html is not None:
                document = ys.Document.html("retained-cart", observation.html)
                plan = ys.Plan(
                    outputs=[ys.output("name", ys.css(".shop-cart-item-name").text())]
                )
                print(document.locate(plan).values())


asyncio.run(main())
```

The outer context owns the Session. Each inner context acquires and releases Work. Passing Work to `invoke` lends the existing tab control to that recipe. Context exit attempts cleanup even if the body raises.

The second recipe sees the lamp left by the first. Run `uv run python main.py`: it prints `['Arc desk lamp']`. Releasing Work ended control of the tab; closing the Session ends the browser lifetime owned by this program.

## Choose the lifetime the task needs

A managed invocation is convenient for a standalone task. An explicit Session makes the longer lifetime visible when several operations depend on shared state.

A Session's lifetime, tab identity, and execution capacity are separate concerns. Holding Work gives authority over its tab. It doesn't reserve every browser operation slot. We'll return to that distinction when several tasks share browser capacity.

## Next

[Accessing a protected page](accessing-a-protected-page.md) uses the same ideas for eShop's Turnstile access gate.
