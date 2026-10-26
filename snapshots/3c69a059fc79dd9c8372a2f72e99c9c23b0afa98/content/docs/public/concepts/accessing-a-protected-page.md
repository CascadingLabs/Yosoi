---
title: 'Accessing a protected page'
description: 'Follow the Turnstile access workflow and retain the result when verification does not finish.'
order: 10
---

# Accessing a protected page

[Turnstile eShop](https://qscrape.dev/eshop/turnstile/) puts an access check before the same catalog. Opening its URL is only the beginning of that workflow.

The page runs the Turnstile widget. If it obtains a token, it enables **Continue to shop**. That button submits the token to the site's catalog endpoint. The server verifies it with Cloudflare, including the expected action and hostname, before returning the catalog.

Our recipe can follow the site's controls and observe whether the product arrives. It cannot promise that every browser or environment will complete a live challenge.

## Example: follow the access gate

These complete programs use a visible browser and bounded waits. They do not interact with the challenge widget itself. If the check requires a person or cannot finish, the first wait ends and the recipe stops.

### Rust

```rust
use std::error::Error;
use yosoi::prelude as ys;
use ys::policy::{Acquisition, BrowserMode, Continuation, Page, StopScope};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let mut policy = ys::Policy::default();
    policy.page = Page::new(vec![Acquisition::Browser(BrowserMode::Headful)])?;

    let recipe = ys::flow::new([
        ys::action::navigate("https://qscrape.dev/eshop/turnstile/"),
        // callout: This live-browser selector waits for the site's Continue button to be enabled.
        ys::action::wait_until(
            ys::flow::Condition::Exists {
                selector: "button.shop-add-button:not([disabled])".into(),
            },
            8_000,
        ),
        ys::action::click("button.shop-add-button"),
        ys::action::wait_until(
            ys::flow::Condition::Exists {
                selector: r#"article[data-product-id="obj-001"]"#.into(),
            },
            8_000,
        ),
    ])
    .on_failure(Continuation::Stop(StopScope::Invocation));

    let outcome = recipe.bind(&policy).invoke().await?;
    println!("Access recipe: {:?}", outcome.terminal);
    println!("Skipped steps: {}", outcome.skipped_steps.len());

    Ok(())
}
```

The Policy chooses headful execution. The first wait observes the enabled site control; the second observes the lamp after the verified catalog response. The live-browser condition uses browser CSS syntax. It is separate from the smaller CSS subset used to evaluate a retained Document.

Run `cargo run` with a compatible browser and display. Completion means the recipe reached the lamp. A stopped recipe retains its receipts and skipped steps, so an unresolved access check is visible rather than reported as an empty catalog.

### Python

```python
import asyncio
import yosoi as ys
from yosoi.policy import Acquisition, Page, Policy


async def main():
    policy = Policy(page=Page(acquisitions=[Acquisition.browser("headful")]))

    recipe = ys.flow(
        [
            ys.navigate("https://qscrape.dev/eshop/turnstile/"),
            # callout: This live-browser selector waits for the site's Continue button to be enabled.
            ys.wait_until(
                ys.exists("button.shop-add-button:not([disabled])"), timeout_ms=8_000
            ),
            ys.click("button.shop-add-button"),
            ys.wait_until(
                ys.exists('article[data-product-id="obj-001"]'), timeout_ms=8_000
            ),
        ],
        on_failure=ys.policy.Stop(scope="invocation"),
    )

    outcome = await recipe.bind(policy).invoke()
    print("Access recipe:", outcome.terminal)
    print("Skipped steps:", len(outcome.skipped_steps))


asyncio.run(main())
```

The Policy chooses headful execution. The first wait observes the enabled site control; the second observes the lamp after the verified catalog response. The live-browser condition uses browser CSS syntax. It is separate from the smaller CSS subset used to evaluate a retained Document.

Run `uv run python main.py` with a compatible browser and display. Completion means the recipe reached the lamp. A stopped recipe retains its receipts and skipped steps, so an unresolved access check is visible rather than reported as an empty catalog.

## Understand the boundary

A visible window can help us inspect what the site is asking for. It does not establish that verification will succeed. Browser mode, site configuration, and the observed challenge outcome are separate facts.

This shop also has ordinary HTML and JavaScript versions with public product data. The Turnstile version is a controlled example of an access workflow. Choosing another available representation is different from completing that workflow.

A Session can retain browser state across dependent steps, but this site's full-page navigation starts a new access check. Keep the sequence together when it depends on the verified catalog currently displayed.

## Next

[Finding more pages](finding-more-pages.md) moves from a known URL to a bounded inventory and search candidates.
