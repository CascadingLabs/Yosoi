---
title: 'Finding more pages'
description: 'Discover candidate URLs with Map and Search, then choose what to acquire.'
order: 11
---

# Finding more pages

We've known the lamp's URL throughout this series. A larger task may start with a site and need to discover its product pages.

**Map** explores a bounded frontier of URLs. **Search** asks selected search providers for candidates. Both help us choose where to go next; acquiring and validating a product remains separate work.

## Example: inventory a small part of eShop

These complete programs respect robots rules, allow eight requests, and use one concurrent acquisition. The budget makes the example small; it does not promise a complete site inventory.

### Rust

```rust
use std::error::Error;
use yosoi::prelude as ys;
use ys::policy::{Budget, DiscoveryDocuments, Robots};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let mut policy = ys::Policy::default();
    policy.map.robots = Robots::Respect;
    policy.map.limits.max_requests = Budget::new(8)?;
    policy.map.limits.max_concurrency = Budget::new(1)?;
    // callout: Retain captures within the memory budget so later extraction can reuse them.
    policy.map.documents = DiscoveryDocuments::RetainWithinBudget;

    let outcome = ys::map::new("https://qscrape.dev/eshop/html/")
        .bind(&policy)
        .send()
        .await?;
    println!("Stopped: {:?}", outcome.termination());
    for page in outcome.pages() {
        println!("{}: {:?}", page.url, page.exploration);
    }
    println!("Retained captures: {}", outcome.captures().len());

    Ok(())
}
```

The inventory retains discovered URLs and each page's exploration state. Some entries can remain unexplored when the budget ends. Retained captures contain their Responses, so later Plans can read available Documents without another fetch.

Run `cargo run` and inspect the URLs and stop reason. The number of discovered URLs can exceed the request budget because finding a link is different from requesting its target.

### Python

```python
import asyncio
import yosoi as ys
from yosoi.policy import Map, MapLimits, Policy


async def main():
    policy = Policy(
        map=Map(
            robots="respect",
            documents="retain_within_budget",
            limits=MapLimits(max_requests=8, max_concurrency=1),
        )
    )

    outcome = await ys.map.new("https://qscrape.dev/eshop/html/").bind(policy).send()
    print("Stopped:", outcome.termination)
    for page in outcome.pages:
        print(page.url, page.exploration)
    print("Retained captures:", len(outcome.captures))


asyncio.run(main())
```

The inventory retains discovered URLs and each page's exploration state. Some entries can remain unexplored when the budget ends. Retained captures contain their Responses, so later Plans can read available Documents without another fetch.

Run `uv run python main.py` and inspect the URLs and stop reason. The number of discovered URLs can exceed the request budget because finding a link is different from requesting its target.

## When robots rules stop exploration

QScrape's current robots file excludes the shop paths. With respect enabled, Map can inventory sitemap URLs while leaving shop pages skipped and retaining no captures. Those page states explain why discovery and acquisition are separate.

For this controlled playground that we maintain for scraper practice, the following variant explicitly ignores those rules. It keeps the same eight-request bound and single worker. These lines replace the robots setting before binding the Request.

## Example: explore the controlled playground

### Rust

```rust
policy.map.robots = Robots::Ignore;
```

The rest of the preceding Map program is unchanged. Its retained Responses can supply Documents for the Plans we already know. An application should choose its own admission rules for other sites.

### Python

```python
policy.map.robots = "ignore"
```

The rest of the preceding Map program is unchanged. Its retained Responses can supply Documents for the Plans we already know. An application should choose its own admission rules for other sites.

## Ask a search provider

Search is useful when a task begins with a query rather than a site's links. We'll ask Bing for QScrape's lamp. A newly published page may not be indexed, and a provider can reject or challenge an automated request. Those are outcomes to inspect, not reasons to invent a result.

## Example: obtain search candidates

These complete programs use the browser-enabled installation for the provider's standard route.

### Rust

```rust
use std::error::Error;
use yosoi::prelude as ys;
use ys::policy::search::{Provider, Search};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let policy = ys::Policy {
        search: Search::new([Provider::Bing])?,
        ..ys::Policy::default()
    };
    let response = ys::search::new("site:qscrape.dev Arc desk lamp")?
        .bind(&policy)
        .send()
        .await?;
    for provider in response.providers() {
        match provider.outcome() {
            ys::search::ProviderOutcome::Results(page) => {
                for hit in page.hits() {
                    println!("{}", hit.url());
                }
            }
            other => println!("Provider outcome: {other:?}"),
        }
    }

    Ok(())
}
```

The provider outcome distinguishes candidate results from a challenged or unsuccessful search. A returned URL can become a Request target; its destination has not been acquired by this search.

### Python

```python
import asyncio
import yosoi as ys
from yosoi.policy import Policy, ProviderSelection, Search


async def main():
    policy = Policy(search=Search(providers=[ProviderSelection(provider="bing")]))
    response = await ys.search.new("site:qscrape.dev Arc desk lamp").bind(policy).send()
    for provider in response.providers:
        print(provider.provider, provider.outcome)


asyncio.run(main())
```

The provider outcome distinguishes candidate results from a challenged or unsuccessful search. A returned URL can become a Request target; its destination has not been acquired by this search.

## Preserve discovery context

Keep Map's scope, stop reason, and unfinished frontier with its inventory. Keep Search's per-provider outcomes with its candidates. A provider can return irrelevant URLs even for a site-specific query; the application still checks the destination and the product evidence. Neither result proves that every useful page has been found.

Robots choices apply to Map's exploration. A later Request is another operation, so the application still decides which discovered URLs it should acquire.

## Next

[Bounding the work](policy-and-budgets.md) explains what happens when a limit, failure, or cancellation interrupts the task.
