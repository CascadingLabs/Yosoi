---
title: Browser
description: Acquire response, rendered-DOM, and accessibility documents with Chrome or Chromium.
order: 15
---

# Browser

Use browser acquisition when you need evidence from a page after JavaScript runs. It returns immutable documents that you can inspect with the same locator API.

## Enable the feature

Replace the SDK dependency in your application's `Cargo.toml` with:

```toml
yosoi = { path = "../Yosoi/crates/yosoi", features = ["browser"] }
```

Install regular Chrome or Chromium Stable. Testing-only browser distributions are outside the project's supported baseline. The browser must be able to run with its sandbox and site/process isolation enabled. Headful mode also needs a working display.

## Request a rendered DOM

```rust
use std::error::Error;
use yosoi::prelude as ys;
use ys::policy::{Acquisition, BrowserMode, DocumentRequest, Page};
use ys::request::DocumentOutcome;

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let mut policy = ys::Policy::default();
    policy.page = Page::new(vec![
        Acquisition::Browser(BrowserMode::Headless)
            .documents([DocumentRequest::RenderedDom]),
    ])?;
    let response = ys::request::new("https://example.org/")
        .bind(&policy)
        .send()
        .await?;
    let plan = ys::Plan::new([ys::output("title", ys::css("h1")?.text())?])?;

    for attempt in response.attempts() {
        for selected in attempt.documents() {
            match selected.outcome() {
                DocumentOutcome::Produced(document) => {
                    println!("{:?}", document.locate(&plan));
                }
                other => eprintln!("{other:?}"),
            }
        }
    }
    Ok(())
}
```

Choose `BrowserMode::Headful` for a visible browser. Request `AccessibilityTree` to query roles, names, text, and states. Add `ResponseDocument` when you also need the source response.

## Capture timing

The standard adapter uses `DomContentLoaded` when a browser acquisition does not request `ResponseDocument`. When it does, it uses controller completion. Additional settlement is disabled in the standard adapter.

Neither choice guarantees that every asynchronous application update has finished. The facade does not expose a custom wait-for-selector, navigation script, or settlement builder. Inspect what was captured and handle missing evidence through the returned outcomes.

## Snapshot boundaries

Rendered DOM and accessibility documents carry a document epoch. Their coordinates describe that captured generation. CSS node references and accessibility node references are not live handles for clicking or typing.

`NetworkTree` currently yields `Unprojectable(NetworkTreeSchemaUnavailable)`. Browser instrumentation may collect other evidence internally, but that does not make it a public SDK document.

## Failures and limits

Without the Cargo feature, a browser request fails during standard execution setup. With the feature enabled, startup or acquisition failures are still possible; inspect attempts and document outcomes rather than assuming `send().await?` produced the desired representation.

`Policy.request.browser` bounds snapshot bytes, events, resources, and accessibility nodes. `Policy.documents` and `Policy.locators` separately bound parsing and evaluation. See [Limits](limits.md) and [Responses](responses.md).
