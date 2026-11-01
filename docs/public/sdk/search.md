---
title: Search
description: Find candidate URLs through provider-backed search.
order: 18
---

# Search

Search combines query intent, provider routing, and per-provider outcomes in one operation. By default, Auto chooses one eligible provider from Google, DuckDuckGo, Bing and Brave, in that rotation order. It never switches engines after that provider starts, even if the result is empty, challenged or unsuccessful.

Rotation is shared through the standard JSONL Registry file. Supply a Registry handle to isolate a workload or share the same file across SDK and CLI callers. A successful selection advances the cursor; a cancelled search after that commit does not refund the turn. With no authored Respectfulness policy, traffic controls remain disabled.

## Workflow

1. Choose Auto candidates or an explicit provider plan through Policy.
2. Submit a query.
3. Inspect each provider outcome.
4. Fetch selected URLs through Requests.

Search returns candidates; fetching their destination pages is a separate step.

## Handling partial results

Inspect `selected_provider` to identify Auto's concrete choice. Candidate slots remain in policy order: `not_selected` means another candidate was chosen, and a constraint or capability rejection explains why a candidate could not start. If none is eligible, no provider executes. Respectfulness events retain rejection reasons and the next eligibility time when known.

With explicit All routing, one provider can succeed while another is challenged or unavailable. Preserve those outcomes so your application can explain what it found.

Bing can return an HTTP response whose visible titles, snippets, and destination
host/path do not confirm the requested topic or intent. URL query and fragment
text is excluded because it can echo the authored query. In that case Search keeps the hits,
marks web coverage partial, and adds `query_relevance_unknown`. This means the
captured result text was insufficient to verify the query; it does not prove
that a destination page is irrelevant. Quoted or operator queries are not
automatically rewritten.

Current built-in provider routes are previews pending certification.

## Example: search provider candidates

### Rust

```rust
use std::error::Error;
use yosoi::prelude as ys;
use ys::policy::search::{Provider, Search};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let policy = ys::Policy {
        search: Search::auto([Provider::Bing, Provider::Brave])?.per_provider_limit(3)?,
        ..ys::Policy::default()
    };
    let request = ys::search::new("photosynthesis")?.bind(&policy);
    request.validate()?; // Does not contact a provider.
    let response = request.send().await?;
    println!("Selected: {:?}", response.selected_provider());
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
    policy = Policy(
        search=Search(
            providers=[ProviderSelection(provider="bing"), ProviderSelection(provider="brave")],
            max_results_per_provider=3,
            max_total_results=3,
        )
    )
    request = ys.search.new("photosynthesis").bind(policy)
    request.check()
    response = await request.send()
    print("Selected:", response.selected_provider)
    print("Operation:", response.termination)
    for provider in response.providers:
        if isinstance(provider.outcome, ys.search.Results):
            print(provider.provider, provider.outcome.value.coverage)
            for hit in provider.hits:
                print(hit.organic_rank, hit.title, hit.url)
        else:
            print(provider.provider, provider.outcome)


asyncio.run(main())
```

The Python binding uses the same provider choice. Inspect the typed outcome
before reading hits; keep attempt and termination information alongside the
selected URLs.

## Walk through the result

The example uses an async application entry point.
Provider failures remain typed outcomes; preparation and initialization failures
are returned as errors.

`check()` in Python and `validate()` in Rust perform preflight without contacting
a provider. `send()` contacts the selected provider. A completed operation can
still contain a failed or partial provider outcome. Zero accepted hits alone
does not establish a genuine empty result page.

Rust selects `Provider::Bing`, `Provider::Brave`, `Provider::DuckDuckGo`, or
`Provider::Google`. Python uses `bing`, `brave`, `duck_duck_go`, and `google`.
Google is included in the default Auto candidate list. Browser-backed
routes require a compatible installed browser and, in Rust, the browser feature.

Auto accepts a nonempty ordered candidate list, with no duplicates. `Search::auto([...])` in Rust and `Search.auto([...])` in Python create that routing choice. The default list contains four currently supported providers; the routing algorithm uses the supplied list rather than a fixed number of slots.

Use `Search::new([...])` in Rust or `Search.new([...])` in Python for explicit All routing. This executes each listed provider. A one-provider plan always stays with that provider. Concurrency limits control simultaneous work; they do not change the routing mode.

When a Respectfulness policy is present, Auto evaluates its groups and commits the chosen provider's first reservation together with cursor advancement. The first Request consumes that reservation without charging a second start. Redirects, retries and recovery receive fresh admission. Registry failures abort selection, and a revision conflict requires reevaluation.

Browser traffic currently cannot enforce per-request Respectfulness. Auto marks those candidates unsupported and can select a supported Direct HTTP route, such as the current Bing profile. Explicit browser requests still fail before unchecked work. See [Respectfulness](respectfulness.md) for the supported boundaries.

A provider operation can include more than one Request. Bing can make bounded
same-provider recovery requests; Google can resolve provider-owned redirect
links without fetching the external destination. Inspect attempts, coverage,
and issues rather than equating one Search operation with one HTTP request.

Try [CLI Search](../cli/search.md) for a terminal example. Exact Rust signatures belong in the generated API reference.

For a provider failure you want to investigate, use [capture and replay](search-diagnostics.md)
to retain bounded evidence and repeat the single-document parser decision offline.

## Continue with a candidate URL

Use [Requests](requests.md) to acquire a chosen destination and
[Contracts](contracts.md) to extract a typed Rust record. Search does not fetch
its result URLs automatically. The [Python SDK](python.md) has a runnable Search
review example and a Pydantic Contract surface. Python locates and groups
evidence through the native SDK, then validates Contract records through
Pydantic. The [Python parity report](../python/parity.md) keeps those typed
record rules separate from Rust `RuntimeContract` conformance.
