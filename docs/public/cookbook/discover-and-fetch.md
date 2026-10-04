---
title: Discover and fetch
description: Discover candidate pages, fetch a few, or reuse retained Map responses.
order: 2
---

# Discover and fetch

Map gives you a bounded inventory. Choose the URLs your application needs, then acquire them through Requests.

## Discover, then fetch

```rust
use std::error::Error;
use yosoi_sdk::prelude as ys;
use ys::policy::{Budget, Robots};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let mut policy = ys::Policy::default();
    policy.map.robots = Robots::Respect;
    policy.map.limits.max_requests = Budget::new(10)?;
    let inventory = ys::map::new("https://example.org/")
        .bind(&policy)
        .send()
        .await?;

    println!("Map stopped: {:?}", inventory.termination());
    for page in inventory.pages().iter().filter(|page| {
        matches!(page.exploration, ys::map::Exploration::Inspected)
    }).take(3) {
        let response = ys::request::new(page.url.as_str())
            .bind(&policy)
            .send()
            .await?;
        for attempt in response.attempts() {
            println!("{}: {:?}", page.url, attempt.state());
        }
    }
    Ok(())
}
```

This example fetches at most three pages sequentially and only chooses pages Map inspected. The extra requests are separate operations; they are not counted against the finished Map run's request budget. Requests also do not inherit Map's robots filtering, so apply your application's URL-admission rules to any different selection.

## Reuse Map's captures

If Map already captured the document you need, retaining it can avoid the second request:

```rust
use std::error::Error;
use yosoi_sdk::prelude as ys;
use ys::documents::DocumentClass;
use ys::policy::{Budget, DiscoveryDocuments, Robots};
use ys::request::DocumentOutcome;

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let mut policy = ys::Policy::default();
    policy.map.robots = Robots::Respect;
    policy.map.documents = DiscoveryDocuments::RetainWithinBudget;
    policy.map.limits.max_requests = Budget::new(10)?;
    let inventory = ys::map::new("https://example.org/")
        .bind(&policy)
        .send()
        .await?;
    let plan = ys::Plan::new([ys::output("title", ys::css("h1")?.text())?])?;

    for capture in inventory.captures() {
        for attempt in capture.response().attempts() {
            for selected in attempt.documents() {
                if let DocumentOutcome::Produced(document) = selected.outcome()
                    && document.class() == DocumentClass::SourceHtml
                {
                    println!("{}: {:?}", capture.url(), document.locate(&plan));
                }
            }
        }
    }
    println!("Omissions: {:?}", inventory.omissions());
    Ok(())
}
```

Captures can include support documents and are bounded by the retention budget. The example filters for produced source HTML. Keep the inventory alive while using its borrowed responses, or call `to_owned()` on a document you need to retain longer.

Read [Map](../sdk/map.md) for scope and coverage semantics, or [CLI Map](../cli/map.md) for terminal use.
