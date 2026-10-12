---
title: 'Observe browser work'
description: 'Read bounded Rust operation receipts without taking tab control.'
order: 0
---

# Observe browser work

A Watcher receives supported operation receipts. It does not gain authority to control a tab.

## Subscribe before work begins

The Session owner creates the subscription with `session.watch()` before submitting the operation to observe. Pass that Watcher to this helper while the producer task runs.

```rust
use yosoi::session::{SessionError, Watcher};

// Read one future receipt from a subscription created by the Session owner.
async fn print_next_receipt(watcher: &mut Watcher) -> Result<(), SessionError> {
    let receipt = watcher.next().await?;
    println!("Observed operation status: {:?}", receipt.status);
    Ok(())
}
```

The helper uses the real bounded Watcher API. Its wait can return a deadline, cancellation, closed-stream or lag error. Preserve those distinctions when an observation cannot be obtained.

## Lifetime

1. Acquire and retain the owning Session.
2. Subscribe before the relevant operation is emitted.
3. Run the producer through Work with the authority it needs.
4. Read and inspect the supported receipts.
5. Drop or close the subscription when observation ends.
6. Let the Session owner decide when to close browser resources.

Closing a Watcher closes the subscription. It does not close or cancel the owning Session.

## Python boundary

The current Python bridge exposes the initial tab and borrowed Work, but not Rust's Watcher stream. Inspect the receipts returned in a Python Flow outcome after invocation. Do not substitute that completed result for a concurrent subscription.

See [Sessions](../sdk/sessions/index.md) for ownership code and [Outcomes](../concepts/outcomes.md) for interpreting effects and uncertainty.
