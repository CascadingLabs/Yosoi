---
title: 'Assert and wait for evidence'
description: 'Choose an immediate assertion or a bounded Until observation.'
order: 0
---

# Assert and wait for evidence

Use an immediate assertion when the evidence should already be present. Use Until when the task needs to observe a supported condition becoming true.

## Requirements

Rust needs the browser feature and Tokio's async entry point support. Python needs a browser-enabled wheel. Both need compatible regular Chrome or Chromium with sandboxing and site isolation enabled.

## Example: wait for the heading

### Rust

```rust
use std::error::Error;
use yosoi::{action, flow};
use yosoi::policy::{Continuation, StopScope};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let recipe = flow::new([
        action::navigate("https://example.org/"),
        // Observe the current page until a heading exists, within five seconds.
        action::assert(flow::Condition::Exists { selector: "h1".into() })
            .timeout(5_000)
            .until(),
    ]).on_failure(Continuation::Stop(StopScope::Invocation));
    let outcome = recipe.invoke().await?;
    outcome.require_completed()?;
    Ok(())
}
```

The assertion becomes an Until step. Its local timeout is expressed in milliseconds and bounds the observation. The invocation stops if the prerequisite fails.

### Python

```python
import asyncio
import yosoi as ys

async def main():
    recipe = ys.flow([
        ys.navigate("https://example.org/"),
        # Bound the observation step to five seconds instead of sleeping.
        ys.timed(ys.exists("h1").until(), 5_000),
    ], on_failure=ys.policy.Stop(scope="invocation"))
    outcome = await recipe.invoke()
    outcome.require_completed()

asyncio.run(main())
```

The Condition expectation's `until` method declares the observation. `timed` applies the same millisecond bound. It does not start a second independent delay.

## Read the outcome

A sleep waits for time to pass. This program observes whether the supported evidence exists. The selector is a concrete binding for the demonstration page.

1. Navigate to acquire the current page.
2. Observe the heading condition until it passes or its budget ends.
3. Inspect the resulting step receipt and terminal state.
4. Continue only when the prerequisite required by the task passed.

Immediate Contract assertions inspect one validated observation. A bounded Until check can continue observing supported evidence. Keep partial and unknown results visible when the condition cannot be established.

See [Assertions](../sdk/assertions.md) for local checks and [Flows](../sdk/flows.md) for failure scopes.
