---
title: 'Bounding the work'
description: 'Set limits where work happens and keep failures, cancellation, and uncertain effects visible.'
order: 12
---

# Bounding the work

We've used Policy to choose an acquisition and bound Map's requests. Limits also apply when we parse a Document, locate values, validate records, or run a browser action.

A small input makes the difference visible. We'll retain some HTML successfully, then give its evaluation a byte budget too small to read it.

## Example: an input limit

These complete programs run offline.

### Rust

```rust
use std::error::Error;
use yosoi::prelude as ys;
use ys::policy::AddressableByteLimit;

fn main() -> Result<(), Box<dyn Error>> {
    let document = ys::Document::html(
        "lamp",
        b"<h1>Arc desk lamp</h1><p class='price'>$68.00</p>".to_vec(),
    )?;

    let plan = ys::Plan::new([ys::output("name", ys::css("h1")?.text())?])?;
    let mut policy = ys::Policy::default();
    policy.documents.max_input_bytes = AddressableByteLimit::try_from(16)?;
    println!("{:#?}", document.bind(&policy).locate(&plan));

    Ok(())
}
```

Construction retains the input. Evaluation under this Policy reports an exhausted input limit. A locator's match budget or a Request's elapsed budget would constrain different work; changing one does not raise the others.

### Python

```python
import yosoi as ys
from yosoi.policy import Documents, Policy

document = ys.Document.html(
    "lamp", b"<h1>Arc desk lamp</h1><p class='price'>$68.00</p>"
)
plan = ys.Plan(outputs=[ys.output("name", ys.css("h1").text())])
policy = Policy(documents=Documents(max_input_bytes=16))
outcome = document.bind(policy).locate(plan)
print(outcome)
```

Construction retains the input. Evaluation under this Policy reports an exhausted input limit. A locator's match budget or a Request's elapsed budget would constrain different work; changing one does not raise the others.

## Stop dependent work after a failure

A cart click depends on reaching the intended product. The following recipe deliberately waits for a nonexistent card. Its stop policy keeps the click from running.

## Example: a failed prerequisite

These complete programs use the browser installation from earlier lessons. The nonexistent selector is controlled input for this failure demonstration.

### Rust

```rust
use std::error::Error;
use yosoi::prelude as ys;
use ys::policy::{Continuation, StopScope};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let recipe = ys::flow::new([
        ys::action::navigate("https://qscrape.dev/eshop/html/product/obj-001/"),
        ys::action::wait_until(
            ys::flow::Condition::Exists {
                selector: "#missing-product".into(),
            },
            200,
        ),
        ys::action::click("button.shop-add-button"),
    ])
    .on_failure(Continuation::Stop(StopScope::Invocation));

    let outcome = recipe.invoke().await?;
    println!(
        "Stopped: {:?}, skipped: {}",
        outcome.terminal,
        outcome.skipped_steps.len()
    );

    Ok(())
}
```

The wait fails and the click is skipped. We inspect the deliberately unsuccessful outcome rather than calling `require_completed()`. The receipts explain the attempted steps; skipped steps explain what never started.

### Python

```python
import asyncio
import yosoi as ys


async def main():
    recipe = ys.flow(
        [
            ys.navigate("https://qscrape.dev/eshop/html/product/obj-001/"),
            ys.wait_until(ys.exists("#missing-product"), timeout_ms=200),
            ys.click("button.shop-add-button"),
        ],
        on_failure=ys.policy.Stop(scope="invocation"),
    )

    outcome = await recipe.invoke()
    print("Stopped:", outcome.terminal, "skipped:", len(outcome.skipped_steps))


asyncio.run(main())
```

The wait fails and the click is skipped. We inspect the deliberately unsuccessful outcome rather than calling `require_completed()`. The receipts explain the attempted steps; skipped steps explain what never started.

## Cancel work explicitly

A cancellation token lets the caller stop work it no longer needs. This small example cancels before sending, so it demonstrates the terminal state without depending on a network race.

## Example: cancel before acquisition

### Rust

```rust
use std::error::Error;
use yosoi::prelude as ys;

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let cancel = ys::request::CancellationToken::new();
    cancel.cancel();
    let response = ys::request::new("https://qscrape.dev/eshop/html/")
        .send_cancellable(&cancel)
        .await?;
    println!("Termination: {:?}", response.termination());

    Ok(())
}
```

The response records cancellation. A real caller can share the token with another task and cancel it when circumstances change. Await the operation so its retained outcomes and cleanup remain available.

### Python

```python
import asyncio
import yosoi as ys


async def main():
    cancel = ys.CancellationToken()
    cancel.cancel()
    response = await ys.request.new("https://qscrape.dev/eshop/html/").send(
        cancellation=cancel
    )
    print("Termination:", response.termination)


asyncio.run(main())
```

The response records cancellation. A real caller can share the token with another task and cancel it when circumstances change. Await the operation so its retained outcomes and cleanup remain available.

## Choose the result your task requires

An operation can finish while retaining a partial Document, a rejected record, or an unsuccessful attempt. Missing values, incomplete evidence, and failed work need different decisions.

Browser effects add another boundary. Cancellation does not undo a dispatched click. A timeout can leave its effect unknown, so another attempt may repeat something that already happened. Inspect domain evidence such as the cart before deciding to retry.

Use units explicitly. Request elapsed settings use microseconds; the browser wait inputs above use milliseconds. Nested Flow timeouts supply scoped action defaults. The result's Policy snapshot records the acquisition choices used for that run.

## Next

[Sharing browser capacity](sharing-browser-capacity.md) separates tab ownership from the number of controller operations allowed to run.
