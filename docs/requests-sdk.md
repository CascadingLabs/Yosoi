# Requests SDK

## Plain English

A request names one target. Its policy says which acquisition methods to run and which documents each method should return. Yosoi runs those acquisitions in order and gives back one response containing a separate result for every attempt.

## Default and bound requests

Unbound requests use the package's current defaults. A caller supplies a complete policy with `.bind(&policy)` only when it wants explicit behavior; binding does not merge with or modify the defaults.

```rust
use std::error::Error;
use yosoi::prelude as ys;

async fn current_request() -> Result<(), Box<dyn Error>> {
    let response = ys::request::new("https://example.org/").send().await?;
    let _attempts = response.attempts();
    Ok(())
}
```

Bare `DirectHttp` and `Browser(mode)` acquisitions use `Current` document selection. Today, `Current` resolves to `ResponseDocument`; its runtime representation is classified as HTML, XML, JSON, or text.

Use `.documents([...])` for `Exact` selection. It replaces the current document set, including when the list is empty. An exact selection that resolves to the same documents as `Current` returns the same documents while retaining the authored selection mode in its attempt facts.

```rust
use std::error::Error;
use yosoi::prelude as ys;
use ys::policy::prelude::*;

async fn ordered_request() -> Result<(), Box<dyn Error>> {
    let mut policy = ys::Policy::default();
    policy.page = Page::new(vec![
        DirectHttp,
        Browser(Headless),
        Browser(Headful),
    ])?;

    let response = ys::request::new("https://example.org/")
        .bind(&policy)
        .send()
        .await?;
    let _attempts_in_policy_order = response.attempts();
    Ok(())
}
```

The order in `Page::new` is the execution order: Direct HTTP, then Headless, then Headful. Requests executes serially through the existing adapters; it does not create a parallel scheduler.

The default attempt deadline is 10 seconds. Standard browser execution is
document-aware: response-document capture waits for the main response to finish,
while exact DOM/AX-only capture snapshots at the event-driven
`DOMContentLoaded` checkpoint. It does not wait for network idle or a quiet
period.

For example, `Browser(Headless).documents([DocumentRequest::RenderedDom])` is `Exact`: it replaces the current documents for that acquisition. `Browser(Headless)` alone is `Current`. An exact `ResponseDocument` selection and `Current` currently resolve to the same document, while preserving the authored selection mode in the attempt facts.

## Outcomes and cancellation

`Response` contains ordered `AttemptOutcome` values. Each attempt is `Completed`, `Failed`, or `NotStarted`, and keeps its planned or actual capture identity. Completed attempts retain the terminal receipt; failures retain bounded terminal facts when the adapter observed them; a `NotStarted` attempt has no fabricated receipt. A completed attempt reports each requested document as `Produced`, `Partial`, `Unavailable`, or `Unprojectable`; one document's failure does not erase its siblings. An HTTP status such as 404 is a received response, distinct from a transport failure.

Cancellation is forwarded to the active adapter. Use `send_cancellable(&token)` for standard package contexts or `send_with(&executor, &token)` for caller-supplied contexts. Once observed, Requests does not start later attempts; those attempts appear as `NotStarted`, and outcomes already collected remain in the response.

## Empty selections and NetworkTree

An explicit policy with no acquisitions produces a response with zero attempts. An acquisition with `.documents([])` still runs that attempt but requests zero documents.

`NetworkTree` is not part of the certified Document matrix because its public document schema is not available. Browser projection reports it as unprojectable and does not collect an unusable network payload; Direct HTTP does not support it as a requested document.

## Advanced execution context

The standard `send()` builds only the package contexts needed for the selected acquisitions and uses the existing adapters. `send_cancellable(&cancellation)` uses those same standard contexts with caller-controlled cancellation. The advanced `send_with(&executor, &cancellation)` boundary accepts a reusable `RequestExecutor` plus a cancellation token; its browser inputs include capability certification and must currently select `FreshTopLevel`. Existing runtime browser/frame references are rejected rather than silently executed in another context. It does not accept a `CaptureBundle` or put provider handles in `Response`. Use `send_with` when an embedding owns the explicit inputs.

Browser acquisitions require the `yosoi` crate's `browser` feature. Without that feature, standard `send()` returns the typed `BrowserFeatureDisabled` setup error before any acquisition begins; it does not partially execute earlier attempts.

## Validation boundary

These snippets use the current `send()`, `send_with`, and policy-authoring surfaces. Browser behavior remains environment-sensitive: a September 2026 single-pass live evaluation exercised 50 public sites with Direct HTTP and exact DOM/AX browser capture. That evidence is a QA sample, not a stable performance or anti-bot-bypass guarantee.
