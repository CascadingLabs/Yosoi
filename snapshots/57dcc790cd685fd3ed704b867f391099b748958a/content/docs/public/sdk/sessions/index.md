---
title: 'Sessions'
description: 'Keep browser state and borrow exclusive tab control.'
order: 0
---

# Sessions

Use an explicit Session when several operations must share browser state. Work gives one caller exclusive authority over its selected tab.

For a short standalone task, prefer [managed Flow invocation](../flows.md).

## Example: retain a Session

### Rust

```rust
use std::error::Error;
use yosoi::{action, flow, session};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let browser = session::new().acquire().await?;
    let result: Result<(), Box<dyn Error>> = async {
        let work = browser.work().await?;
        let recipe = flow::new([action::navigate("https://example.org/")]);
        let attempt = recipe.with_lease(&work).invoke().await;
        let released = work.release().await;
        if let Err(error) = &released {
            eprintln!("Work cleanup: {error}");
        }
        let outcome = attempt?;
        released?;
        outcome.require_completed()?;
        Ok(())
    }.await;
    let closed = browser.close().await;
    if let Err(error) = &closed {
        eprintln!("Session cleanup: {error}");
    }
    result?;
    closed?;
    Ok(())
}
```

`acquire` creates the Session. `work` obtains tab control. `with_lease` borrows that authority for a recipe. Work release and Session close are attempted even when invocation fails; cleanup errors are reported before propagating the operation result.

### Python

```python
import asyncio
import yosoi as ys

async def main():
    recipe = ys.flow([ys.navigate("https://example.org/")])
    async with ys.session() as session:
        async with session.work() as work:
            outcome = await recipe.invoke(work)
            outcome.require_completed()

asyncio.run(main())
```

The outer context owns the Session and the inner context owns Work. Passing Work to `invoke` borrows it. Context exit releases owned resources, including when the task raises an exception. Cleanup failures preserve the original operation error.

## Lifetime and capacity

Releasing Work allows another caller to obtain control. It does not close the Session or erase its state. Closing the Session ends the resources it owns.

Execution concurrency is a separate bound on controller operations. A supported condition wait can keep tab control while yielding execution capacity. Do not describe that as releasing the tab.

## Rust and Python boundaries

Rust exposes `new_tab()` and `watch()` in addition to the initial tab. Watchers receive bounded receipts without control authority.

The current Python bridge exposes the initial tab and borrowed Work, without explicit tab creation, Watcher streams or remote attachment. Session remote endpoints are not supported by the current implementation.

## Cancellation and effects

Cancellation does not undo an already-dispatched action. A timeout after dispatch can leave its effect unknown. Keep receipts and check domain state before repeating a potentially irreversible action.

See [ownership concepts](../../concepts/sessions-and-ownership.md) and [outcomes](../../concepts/outcomes.md).
