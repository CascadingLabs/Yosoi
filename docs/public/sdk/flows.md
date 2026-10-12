---
title: 'Actions and Flows'
description: 'Author, invoke and inspect an ordered browser recipe.'
order: 0
---

# Actions and Flows

A Flow collects Actions into an ordered recipe. Creating it performs no browser I/O. Invocation validates the recipe, runs it and returns step receipts.

## Requirements

Enable the Rust `browser` feature and add Tokio as described in [Installation](installation.md). Python needs a browser-enabled wheel. Both need compatible regular Chrome or Chromium with sandboxing and site isolation enabled.

## Example: run a managed task

### Rust

```rust
use std::error::Error;
use yosoi::{action, flow};
use yosoi::policy::{Continuation, StopScope};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let recipe = flow::new([
        action::navigate("https://example.org/"),
        action::assert(flow::Condition::Exists {
            selector: "h1".into(),
        }).into(),
    ]).on_failure(Continuation::Stop(StopScope::Invocation));

    recipe.validate()?;
    let outcome = recipe.invoke().await?;
    outcome.require_completed()?;
    Ok(())
}
```

`navigate` acquires the page and the assertion checks its heading. `on_failure` stops dependent steps after a failed prerequisite. `validate` checks the recipe before I/O. `invoke` owns resource acquisition and cleanup; `require_completed` checks the returned status.

### Python

```python
import asyncio
import yosoi as ys

async def main():
    recipe = ys.flow([
        ys.navigate("https://example.org/"),
        ys.assert_that(ys.exists("h1")),
    ], on_failure=ys.policy.Stop(scope="invocation"))
    recipe.to_json()
    outcome = await recipe.invoke()
    outcome.require_completed()

asyncio.run(main())
```

`flow` describes the same steps. `to_json` validates its wire representation through Rust without launching the browser. `invoke` manages ownership. `require_completed` rejects failed, uncertain or incomplete execution.

## Walk through the recipe

1. Navigate to the demonstration page.
2. Check that its heading exists.
3. Stop the invocation if that prerequisite fails.
4. Inspect the final outcome and receipts.
5. Close the resources owned by the managed invocation.

The `h1` selector is a concrete binding for this demonstration site. It is not automatic element discovery. An immediate assertion can fail if its evidence has not arrived; use a supported Until check when the task needs a bounded wait.

## Continue or stop

The default can continue after recoverable failures. Such a run can return `completed_with_issues`, which `require_completed()` rejects. Configure stop behavior when later steps depend on earlier success.

A terminal success proves the checks you authored. For a checkout, add typed checks of the cart and final order confirmation. A click alone does not prove an order.

## Keep state between tasks

Use [Sessions](sessions/index.md) and borrowed Work when tasks need the same tab state. Managed invocation owns temporary resources; borrowed invocation leaves ownership and cleanup with the caller.

See [Assertions](assertions.md), [Concepts](../concepts/actions-and-flows.md), and the [checkout recipe](../cookbook/qscrape-checkout.md).
