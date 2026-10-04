---
title: Requests
description: Fetch a URL with a shared Policy and inspect each acquisition.
order: 2
---

# Requests

A request describes a URL to acquire. Creating it performs no I/O. Sending it validates the target and Policy, then runs the selected acquisitions.

```rust
use std::error::Error;
use yosoi::prelude as ys;

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let policy = ys::Policy::default();
    let request = ys::request::new("https://example.org/").bind(&policy);
    request.validate()?;

    let response = request.send().await?;
    println!("Target: {}", response.requested_target());
    for attempt in response.attempts() {
        println!("{:?}: {:?}", attempt.acquisition(), attempt.state());
    }
    Ok(())
}
```

`validate()` is useful for checking configuration before work begins. `send()` performs preparation too, so a separate validation call is optional.

## Use a Policy

`request.bind(&policy)` consumes the authored request and borrows your Policy. Reuse the same Policy across requests to keep their behavior consistent. Calling `send()` on an unbound request uses `Policy::default()`.

The default is one Direct HTTP acquisition requesting the response document. [Browser acquisition](browser.md) is an explicit choice.

## Choose acquisitions and documents

`Policy.page.acquisitions` is an ordered list of acquisitions. It is not a fallback list: each authored acquisition runs, subject to cancellation and failures during setup. A successful Direct HTTP attempt does not suppress a later browser attempt.

Use `Acquisition::documents(...)` to replace an acquisition's requested document set. For example, a browser can request both its rendered DOM and accessibility tree. See [Policy](policy.md) for a complete example.

## Read the response

An `Ok(Response)` tells you that execution returned a response object. Individual acquisitions can still fail. Check `attempt.state()`, the optional HTTP status, and each [document outcome](responses.md).

Both `PageRequest` and `BoundPageRequest` expose `id()`, `target()`, `validate()`, `send()`, and `send_cancellable()`. The bound request also exposes `policy()`. The authored target remains available through `target()`; the response reports its canonical requested target.

## Cancel a request

Pass a `CancellationToken` owned by your application:

```rust
use yosoi::prelude as ys;
use ys::request::{CancellationToken, RequestSendError, Response};

async fn fetch(cancel: &CancellationToken) -> Result<Response, RequestSendError> {
    ys::request::new("https://example.org/")
        .send_cancellable(cancel)
        .await
}
```

Another task can call `cancel()` on a clone of that token. Await the operation to receive its recorded outcomes, then inspect `response.termination()`. Cancellation is separate from an ordinary failed attempt. [Limits](limits.md) explains time and resource bounds.

## Current request surface

The facade provides URL-based page acquisition through standard adapters. It does not expose a general HTTP client builder for custom methods, request bodies, headers, shared cookie sessions, or custom executors.

Use [Responses](responses.md) to pass the acquired document into a locator plan.
