---
title: 'Run browser JavaScript'
description: 'Authorize a real browser expression and verify its visible effect.'
order: 0
---

# Run browser JavaScript

Use browser JavaScript when the supported task needs it. Permission is explicit. The program below marks the demonstration page and checks the resulting attribute.

## Requirements

Rust needs the browser feature and Tokio. Python needs a browser-enabled wheel.
Both need compatible regular Chrome or Chromium with sandboxing and site isolation
enabled. See [Installation](../sdk/installation.md).

## Example: mark and verify the page

### Rust

```rust
use std::error::Error;
use yosoi::{action, flow, policy};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let policy = policy::Policy::default();
    let recipe = flow::new([
        action::navigate("https://example.org/"),
        // Execute this expression in the browser's document context.
        action::evaluate("(() => { document.body.dataset.reviewed = 'yes'; return { reviewed: true }; })()"),
        action::assert(flow::Condition::Exists {
            selector: "body[data-reviewed='yes']".into(),
        }).into(),
    ]).on_failure(policy::Continuation::Stop(policy::StopScope::Invocation));

    // Permission is explicit for the Session owned by this managed invocation.
    let outcome = recipe.bind(&policy).allow_javascript().invoke().await?;
    outcome.require_completed()?;
    Ok(())
}
```

The expression runs on the acquired page and returns a JSON object. The following assertion verifies its DOM effect. `allow_javascript` applies to the resources owned by managed invocation.

### Python

```python
import asyncio
import yosoi as ys

async def main():
    recipe = ys.flow([
        ys.navigate("https://example.org/"),
        # The expression runs in the browser, where document is available.
        ys.evaluate("(() => { document.body.dataset.reviewed = 'yes'; return { reviewed: true }; })()"),
        ys.assert_that(ys.exists("body[data-reviewed='yes']")),
    ], on_failure=ys.policy.Stop(scope="invocation"))

    # Permit JavaScript explicitly for the managed Session.
    outcome = await recipe.allow_javascript().invoke()
    outcome.require_completed()

asyncio.run(main())
```

The browser supplies `document` to the expression. The Flow explicitly permits evaluation and checks the same effect through a supported condition.

## Ownership and permission

The code uses managed invocation. A borrowed Work lease keeps its existing Session's permissions. An invocation cannot elevate that caller-owned authority.

Use short, bounded expressions. Preserve returned receipts when evaluation fails, times out after dispatch, or exceeds a result bound.

## Local files and modules

The public APIs also support immutable local JavaScript snapshots through `evaluate_file` and supported local module bundles through `run_module`. They read and validate sources before execution; later file edits do not change an already captured step.

Relative local imports stay within the declared bundle root. Bare, remote, computed and escaping imports are rejected during bundle construction. Selected module exports are read rather than invoked.

The code above needs no external script file. Use the source snapshot APIs when a task needs maintained JavaScript files instead of an inline expression.

See [Session ownership](../sdk/sessions/index.md) and the Action reference for those snapshot constructors.
