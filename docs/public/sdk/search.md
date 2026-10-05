---
title: Search
description: Find candidate URLs through provider-backed search.
order: 18
---

# Search

Search combines query intent, provider routing, and per-provider outcomes in one operation.

## Workflow

1. Choose providers and limits through Policy.
2. Submit a query.
3. Inspect each provider outcome.
4. Fetch selected URLs through Requests.

Search returns candidates; fetching their destination pages is a separate step.

## Handling partial results

One provider can succeed while another is challenged or unavailable. Preserve those outcomes so your application can explain what it found.

Current built-in provider routes are previews pending certification.

## Rust SDK

```rust
use yosoi::prelude as ys;
use ys::policy::search::{Provider, Search};

let policy = ys::Policy {
    search: Search::new([Provider::Bing])?,
    ..ys::Policy::default()
};
let request = ys::search::new("rust sdk")?.bind(&policy);
request.validate()?; // Does not contact a provider.
let response = request.send().await?;
for provider in response.providers() {
    match provider.outcome() {
        ys::search::ProviderOutcome::Results(page) => {
            for hit in page.hits() {
                println!("{}", hit.url());
            }
        }
        outcome => println!("{outcome:?}"),
    }
}
```

This example belongs inside an async function returning a compatible error.
Provider failures remain typed outcomes; preparation and initialization failures
are returned as errors.

Try [CLI Search](../cli/search.md) for a terminal example. Exact Rust signatures belong in the generated API reference.

## Continue with a candidate URL

Use [Requests](requests.md) to acquire a chosen destination and
[Contracts](contracts.md) to extract a typed Rust record. Search does not fetch
its result URLs automatically. The [Python SDK](python.md) has a runnable Search
review example and a Pydantic Contract surface. Python Contracts delegate
extraction and validation to Rust; their per-item parity evidence is tracked in
the [Python parity report](../python/parity.md).
