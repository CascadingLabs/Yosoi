---
title: 'Yielding while waiting'
description: 'Keep control of a waiting tab while another tab uses browser execution capacity.'
order: 14
---

# Yielding while waiting

A tab can be waiting for an element while another tab has work to do. If our Session allows only one active controller operation, should that wait occupy the slot until it finishes?

With `yield_on_wait` enabled, eligible condition waits release execution capacity while they wait for browser events. They keep their Work, so another caller cannot take control of the waiting tab. When the wait needs another controller operation, it reacquires capacity.

This is different from releasing Work. Yielding lets another tab use the shared slot; releasing Work lets another caller operate the same tab.

## Why it matters under load

Yielding is most useful when a larger job has many concurrent tasks competing for limited browser capacity. Several tabs may be waiting on page events while others are ready to navigate or inspect data. Letting those waits give up their execution slots can reduce the time ready work spends queued.

A small example cannot easily reproduce that workload, its resource pressure, or its performance gains. The example below shows the mechanism with two tabs. It is not a large-scale benchmark; judge the benefit by measuring your own workload under load.

## Example: let another tab make progress

We'll deliberately wait for a marker that does not exist on the lamp page. That gives us a bounded wait whose behavior we can inspect. The wait will be rejected when its limit ends; that rejection is expected in this example.

Rust exposes the two tabs and execution counters needed to observe another tab making progress. Python exposes the setting and wait receipt, but not tab creation or those counters. Its variant demonstrates the wait's reported yielding decision on one tab.

### Rust

This complete program uses Yosoi's browser feature and Tokio with `macros`, `rt`, and `time`. Add the timer feature to your existing dependency with `cargo add tokio --features macros,rt,time`.

```rust
use std::error::Error;
use std::time::Duration;
use yosoi::prelude as ys;

async fn experiment(browser: &ys::Session) -> Result<(), Box<dyn Error>> {
    let second = browser.new_tab().await?;
    let lamp = browser.work().await?;
    let mug = second.work().await?;
    lamp.navigate("https://qscrape.dev/eshop/html/product/obj-001/")
        .await?;

    let condition = ys::flow::Condition::Exists {
        selector: "#yield-demo".into(),
    };
    let waiting = lamp.wait_until(&condition, 8_000);
    let reading = async {
        // callout: Observe an actually parked wait before starting work on the other tab.
        tokio::time::timeout(Duration::from_secs(3), async {
            while browser.execution_snapshot().parked == 0 {
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        })
        .await?;

        let receipt = mug
            .navigate("https://qscrape.dev/eshop/html/product/obj-002/")
            .await?;
        println!("Other tab: {:?}", receipt.status);
        println!("Still parked: {}", browser.execution_snapshot().parked);
        Ok::<_, Box<dyn Error>>(())
    };
    let (waited, read) = tokio::join!(waiting, reading);

    let lamp_released = lamp.release().await;
    let mug_released = mug.release().await;
    let tab_closed = second.close().await;
    lamp_released?;
    mug_released?;
    tab_closed?;
    read?;
    println!("Missing marker: {:?}", waited?.status);
    Ok(())
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let settings = ys::SessionPolicy {
        maximum_tabs: 2,
        execution_concurrency: 1,
        maximum_queued_operations: 4,
        yield_on_wait: true,
        ..ys::SessionPolicy::default()
    };
    let browser = ys::session::new().configure(settings).acquire().await?;
    let result = experiment(&browser).await;
    let closed = browser.close().await;
    if let Err(error) = &closed {
        eprintln!("Session cleanup: {error}");
    }
    result?;
    closed?;
    Ok(())
}
```

The first Work belongs to the lamp's tab; the second belongs to the mug's tab. `tokio::join!` polls both tasks concurrently. The mug task waits until the Session reports a parked condition wait, then navigates its own tab.

The short timer loop observes scheduler counters. It is not a delay intended to make a web page ready. Its three-second bound reports an error if the expected parked state never appears.

Run `cargo run`. On a successful mug navigation during the lamp's wait, the output is:

- `Other tab: Observed`
- `Still parked: 1`
- `Missing marker: Rejected`

The mug operation finished while the lamp still had a parked wait, despite the single execution slot. Both Works remain held until the tasks settle, then the program releases them and closes the second tab and Session. Network failures can change the receipt or interrupt the experiment.

### Python

This complete program uses the same yielding setting and deliberately absent marker. Its shorter wait keeps the single-tab demonstration small.

```python
import asyncio
import yosoi as ys


async def main():
    settings = ys.SessionPolicy(
        execution_concurrency=1,
        maximum_queued_operations=4,
        yield_on_wait=True,
    )
    async with ys.session(settings=settings) as browser:
        async with browser.work() as work:
            recipe = ys.flow(
                [
                    ys.navigate("https://qscrape.dev/eshop/html/product/obj-001/"),
                    ys.wait_until(ys.exists("#yield-demo"), timeout_ms=200),
                ]
            )
            outcome = await recipe.invoke(work)
            receipt = outcome.steps[-1].receipt
            print("Yielded:", receipt.result["yielded"])
            print("Missing marker:", receipt.status)


asyncio.run(main())
```

Run `uv run python main.py`. It prints `Yielded: True` and `Missing marker: rejected`. The receipt's `yielded` field records that the wait used the yielding path. It does not independently show another tab making progress; Python's current public interface cannot reproduce the Rust experiment.

The inner context keeps Work until the recipe finishes. A rejected condition does not release the tab's control early. The outer context closes the Session afterward.

## What yielding changes

Execution capacity is available to other admitted work while an eligible wait is parked. The waiting tab remains reserved for its current caller, and its condition is still being observed in the browser.

Setting `yield_on_wait` to false makes these waits retain their execution slot. Other tab operations may queue until a slot becomes available. Yielding does not add tabs, raise the concurrency limit, or make an unfinished condition pass.

The application still decides which tasks run concurrently. Two sequential recipes gain no overlap merely because yielding is enabled. These counters describe controller operations, not the browser's total CPU or memory use.

## Next

[Keeping browser windows in Docker](browser-windows-in-docker.md) gives the browser its own display and execution environment.
