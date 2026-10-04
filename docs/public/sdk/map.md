---
title: Map
description: Discover a bounded inventory of URLs and inspect how each one was found.
order: 14
---

# Map

Map starts with a seed URL and builds an inventory from links, robots and sitemap documents, redirects, and optional passive host sources. Its result records both discoveries and unfinished work.

## Basic usage

```rust
use std::error::Error;
use yosoi_sdk::prelude as ys;
use ys::policy::{Budget, Robots};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let mut policy = ys::Policy::default();
    policy.map.robots = Robots::Respect;
    policy.map.limits.max_requests = Budget::new(20)?;
    policy.map.limits.max_concurrency = Budget::new(2)?;
    let outcome = ys::map::new("https://example.org/")
        .bind(&policy)
        .send()
        .await?;

    println!("Stopped: {:?}", outcome.termination());
    for page in outcome.pages() {
        println!("{}: {:?}", page.url, page.exploration);
    }
    Ok(())
}
```

Creating or binding a Map request performs no network I/O. Map clones the bound Policy and validates it when sending. `send()` consumes the request; create another request for another run.

## Scope

The default scope is the seed host and the seed path subtree. A seed such as `https://example.org/docs/` focuses discovery under `/docs/`.

```rust
use std::error::Error;
use yosoi_sdk::prelude as ys;
use ys::policy::{HostScope, PathScope, Subdomains};

fn main() -> Result<(), Box<dyn Error>> {
    let mut policy = ys::Policy::default();
    policy.map.scope.hosts = HostScope::RegistrableDomain;
    policy.map.scope.paths = PathScope::EntireOrigin;
    policy.map.subdomains = Subdomains::Passive;
    policy.validate()?;
    Ok(())
}
```

Passive subdomain discovery requires `HostScope::RegistrableDomain`. It adds observations from bounded public sources; it does not certify that a host is reachable or that all subdomains were found. `HostVerification::Unverified` and `HttpObserved` preserve that distinction. Wildcard names are reported separately from concrete hosts.

## Page exploration and robots

`PageDiscovery::Explore` is the default. Map inspects pages and support documents within its budgets. `PageDiscovery::Disabled` disables page exploration and the robots/sitemap discovery path; it can be useful for passive host discovery.

Robots handling defaults to `Robots::Ignore`. Set `Robots::Respect` explicitly, as the first example does, to apply discovered rules to page exploration. If usable rules cannot be obtained, page exploration for that origin stays blocked. A robots response of 404 or 410 is treated as having no rules. A robots exclusion is recorded as a skip or omission.

## Exclude URL patterns

```rust
use std::error::Error;
use yosoi_sdk::prelude as ys;

fn main() -> Result<(), Box<dyn Error>> {
    let mut policy = ys::Policy::default();
    policy.map.filters.excluded_query_keys = vec!["session".into()];
    policy.map.filters.excluded_path_prefixes = vec!["/account".into()];
    policy.validate()?;
    Ok(())
}
```

These filters omit matching URLs from the inventory. A query-key filter removes the URL when the key is present; it does not strip the parameter and keep a rewritten URL. Each list allows up to 128 strings, each at most 1,024 UTF-8 bytes. Path prefixes must be nonempty.

## Interpret results

| Accessor              | What it tells you                                                       |
| --------------------- | ----------------------------------------------------------------------- |
| `pages()`             | URLs, minimum observed link depth, observations, and exploration state  |
| `hosts()`             | Host observations and verification state                                |
| `relationships()`     | Link, redirect, and canonical relationships                             |
| `tree()`              | A deterministic discovery forest; unknown parent or depth stays unknown |
| `frontier()`          | URLs left pending, at a depth boundary, or awaiting a probe             |
| `sources()`           | Per-source completion, failure, truncation, or disabled state           |
| `support_documents()` | Robots, sitemap, and sitemap-index results                              |
| `wildcards()`         | Wildcard patterns with their source observations                        |
| `wildcard_names()`    | The observed wildcard strings                                           |
| `request_trace()`     | Admitted requests and their observed outcomes                           |
| `omissions()`         | Reasons and counts for omitted work or evidence                         |
| `summary()`           | Requests, bytes, observations, retention, and concurrency counts        |
| `policy_snapshot()`   | The validated settings used for this run                                |

A page can be inventoried, pending, inspected, skipped, or failed. Being present in `pages()` does not mean it was fetched successfully. `SourceStatus::Sampled`, `Truncated`, `Failed`, and `NotStarted` also affect what you can conclude about coverage.

## Know why Map stopped

`termination()` is one of:

| Value          | Meaning                                        |
| -------------- | ---------------------------------------------- |
| `Exhausted`    | No more eligible queued work under this Policy |
| `Limit(limit)` | A named resource budget stopped discovery      |
| `Deadline`     | The operation's time budget expired            |
| `Cancelled`    | The caller cancelled the operation             |

An exhausted run is not proof that the site inventory is complete. Scope, link depth, unreachable pages, source failures, and unobserved links can all limit coverage.

Use `send_cancellable(&token)` with the same `CancellationToken` type as Requests. Await it and inspect the returned termination and frontier.

## Reuse retained documents

Map normally discards captured documents after inspection. Set `policy.map.documents = DiscoveryDocuments::RetainWithinBudget` to keep responses within `max_retained_document_bytes`.

`outcome.captures()` then yields borrowed captures. Each has `url()` and `response()`. Reuse that response's documents to extract data without fetching the same URL again. Retention is bounded, so a discovered page may have no retained capture. The [discovery recipe](../cookbook/discover-and-fetch.md) shows the full workflow.

See [Limits](limits.md) for the default discovery budgets and [CLI Map](../cli/map.md) for terminal use.
