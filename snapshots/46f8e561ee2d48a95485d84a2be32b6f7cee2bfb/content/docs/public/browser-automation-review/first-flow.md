---
title: 'A complete task in one Flow'
description: '0.2.0 concept review. Rust examples describe the local spike; Python examples are proposals.'
order: 1
---

# A complete task in one Flow

A Flow is a list of steps. They execute in order. Failure and local cancellation
default to continuing when safe; [scoped continuation overrides](continuation.md)
can stop the current Flow or invocation. Unknown dispatch always stops unsafe
execution.

The spike's test page has an Advance button, a query input, a status label and
12 rows. Clicking Advance changes the status to ready.

## Choose browser acquisition

These Rust excerpts belong inside an async function that returns a Result.
Build with the `browser` feature. `url` is the address of the page.

```rust
use yosoi::{action, flow};
use yosoi::flow::{Condition, Continuation::Stop, FailureCapturePolicy, StopScope::Invocation};
use yosoi::policy::{
    Acquisition, BrowserMode, DocumentRequest, Page, Policy,
};

let mut browser_policy = Policy::default();
browser_policy.page = Page::new(vec![
    Acquisition::Browser(BrowserMode::Headless)
        .documents([DocumentRequest::RenderedDom]),
])?;
```

Ordinary Requests still default to HTTP. This policy explicitly chooses a
browser and asks for the rendered DOM.

## Describe and run the task

```rust
let steps = flow::new([
    action::navigate(url),
    action::click("#advance"),
    action::enter_text("#query", "hello"),
    action::wait_until(
        Condition::Visible { selector: "#status.ready".into() },
        5_000,
    ),
    action::assert(Condition::CountAtLeast {
        selector: ".row".into(),
        count: 12,
    })
    .into(),
    action::screenshot(),
])
.on_failure(Stop(Invocation))
.with_failure_capture(FailureCapturePolicy::Screenshot);

let outcome = steps.bind(&browser_policy).invoke().await?;

println!("{:?}", outcome.terminal);
```

Yosoi acquires a Session and Work, navigates to the URL, runs the steps, then
releases Work and closes the Session. Captured evidence stays in the outcome.

The wait allows up to five seconds for a visible ready status. The row check
runs once. The screenshot is retained evidence; this call does not save a PNG
to an arbitrary filesystem path.

## What failure looks like

On the fixture's `?variant=drift` page, there are only four rows. The row check
fails. This recipe explicitly stops the invocation on failure, so the normal
screenshot step is skipped, and the failure-capture policy
separately attempts a screenshot. A capture failure does not erase the original
failure.

`invoke().await?` is not proof that the task succeeded. Check `outcome.terminal`
and the step receipts. The runner does not automatically retry actions.

## Invoke the recipe

`action` constructs individual operations; `flow::new` collects them into a
recipe. Call `steps.with_lease(&lease).invoke().await?` to run on a caller-owned tab, or
`steps.bind(&browser_policy).invoke().await?` to acquire and close resources
automatically. Navigation is an explicit action in either form.

The agreed Rust spelling is `steps.invoke().await?` for automatic ownership,
`steps.bind(&policy).invoke().await?` for an explicit policy, and
`steps.with_lease(&lease).invoke().await?` for an existing lease.
