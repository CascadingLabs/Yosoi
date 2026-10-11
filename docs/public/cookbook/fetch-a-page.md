---
title: 'Fetch a page'
description: 'Acquire a known URL and inspect the attempts returned by the Request.'
order: 0
---

# Fetch a page

Use a Request when your application already knows the URL. Start with the default direct HTTP acquisition, then choose another representation when the task needs it.

## Run the task

1. Add Yosoi to the application. Rust's async entry point also needs Tokio with its macros and runtime features.
2. Create the Request and bind the intended Policy.
3. Check configuration without network I/O when an early validation step is useful.
4. Send the Request and inspect every attempt.

## Example: requests

### Rust

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

`validate` checks configuration before I/O. `send` acquires the target. Inspect each attempt's state even when the Response itself was returned successfully.

### Python

```python
import asyncio
import yosoi as ys

async def main():
    policy = ys.Policy()
    request = ys.request.new("https://example.org/").bind(policy)
    request.check()
    response = await request.send()
    print("Target:", response.requested_target)
    for attempt in response.attempts:
        print(attempt.acquisition, attempt.state)

asyncio.run(main())
```

`check` validates the authored request without I/O. The request is asynchronous. The Policy is captured when bound. Each returned attempt exposes its acquisition and state as fields.

## Use the acquired evidence

A returned Response can contain unsuccessful attempts. Inspect each requested representation before locating or extracting from it. The [Response helpers](../sdk/responses.md) demonstrate that inspection in both languages.

The program uses a public demonstration URL. For an application task, supply its known URL. If the result needs content produced by JavaScript, choose [browser acquisition](../sdk/browser.md).

## Cancellation

Give the application ownership of its cancellation token. Signal it from the task that decides the operation should stop, await the Request, and inspect its recorded termination. The [Request cancellation helper](../sdk/requests.md#cancel-a-request) shows the public API.

Continue with [Choose a locator](choose-a-locator.md) or [Extract structured data](extract-structured-data.md).
