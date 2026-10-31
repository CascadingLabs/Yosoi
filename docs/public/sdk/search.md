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

Bing can return an HTTP response whose visible titles, snippets, and destination
host/path do not confirm the requested topic or intent. URL query and fragment
text is excluded because it can echo the authored query. In that case Search keeps the hits,
marks web coverage partial, and adds `query_relevance_unknown`. This means the
captured result text was insufficient to verify the query; it does not prove
that a destination page is irrelevant. Quoted or operator queries are not
automatically rewritten.

Current built-in provider routes are previews pending certification.

## Configure the provider

## Example: search provider candidates

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
    Ok(())
}
```

Read the per-operation result before using its discovered URLs. This excerpt uses the public facade and explicit Policy.

### Python

```python
import asyncio
import yosoi as ys
from yosoi.policy import Policy, ProviderSelection, Search

async def main():
    policy = Policy(search=Search(providers=[ProviderSelection(provider="bing")]))
    request = ys.search.new("rust sdk").bind(policy)
    request.check()
    response = await request.send()
    for provider in response.providers:
        print(provider.provider, provider.outcome)

asyncio.run(main())
```

The Python variant uses the same provider or discovery choices. Keep attempt and termination information alongside selected URLs.

## Walk through the result

The example uses an async application entry point.
Provider failures remain typed outcomes; preparation and initialization failures
are returned as errors.

Try [CLI Search](../cli/search.md) for a terminal example. Exact Rust signatures belong in the generated API reference.

## Continue with a candidate URL

Use [Requests](requests.md) to acquire a chosen destination and
[Contracts](contracts.md) to extract a typed Rust record. Search does not fetch
its result URLs automatically. The [Python SDK](python.md) has a runnable Search
review example and a Pydantic Contract surface. Python locates and groups
evidence through the native SDK, then validates Contract records through
Pydantic. The [Python parity report](../python/parity.md) keeps those typed
record rules separate from Rust `RuntimeContract` conformance.
