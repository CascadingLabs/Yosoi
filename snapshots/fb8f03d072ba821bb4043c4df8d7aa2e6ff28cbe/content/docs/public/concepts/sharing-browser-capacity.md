---
title: 'Sharing browser capacity'
description: 'Separate exclusive tab Work from bounded controller capacity and observe receipts without control.'
order: 13
---

# Sharing browser capacity

A Session can hold more than one tab. Each tab needs its own exclusive Work when a caller operates it. Separately, execution settings bound how many controller operations run and how many wait in the queue.

We'll read two products in separate tabs while limiting controller operations to one slot. This example introduces tab identities and the execution settings. The next lesson demonstrates what happens when a wait yields that slot.

## Example: two tab identities, one execution slot

Rust exposes explicit tab creation. This complete program reads the lamp and mug in separate tabs and receives a passive operation receipt. It uses one controller execution slot.

### Rust

```rust
use std::error::Error;
use yosoi::prelude as ys;

async fn read_name(work: ys::Work, url: &str) -> Result<(), Box<dyn Error>> {
    let recipe = ys::flow::new([
        ys::action::navigate(url),
        ys::action::wait_until(
            ys::flow::Condition::Exists {
                selector: "h1".into(),
            },
            5_000,
        ),
    ]);
    let attempt = recipe.with_lease(&work).invoke().await;
    let released = work.release().await;
    if let Err(error) = &released {
        eprintln!("Work cleanup: {error}");
    }

    let outcome = attempt?;
    released?;
    outcome.require_completed()?;

    let html = outcome
        .steps
        .last()
        .and_then(|s| s.receipt.observation.as_ref())
        .and_then(|o| o.html.as_ref());
    if let Some(html) = html {
        let document = ys::Document::html("tab-page", html.as_bytes().to_vec())?;
        let plan = ys::Plan::new([ys::output("name", ys::css("h1")?.text())?])?;
        println!("{:#?}", document.locate(&plan));
    }

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
    let mut watcher = browser.watch();
    let result: Result<(), Box<dyn Error>> = async {
        read_name(
            browser.work().await?,
            "https://qscrape.dev/eshop/html/product/obj-001/",
        )
        .await?;
        let second = browser.new_tab().await?;
        read_name(
            second.work().await?,
            "https://qscrape.dev/eshop/html/product/obj-002/",
        )
        .await?;
        let receipt = watcher.next().await?;
        println!("Watched: {}", receipt.kind);
        second.close().await?;
        Ok(())
    }
    .await;
    watcher.close();
    let closed = browser.close().await;
    if let Err(error) = &closed {
        eprintln!("Session cleanup: {error}");
    }
    result?;
    closed?;

    Ok(())
}
```

The initial tab reads the lamp; `new_tab()` creates another identity for the mug. Each operation uses that tab's Work. The example reads them sequentially so the output is easy to inspect. The configuration allows one active controller operation and up to four queued operations, independent of the two retained tabs.

The Watcher receives bounded receipts without authority to navigate or click. Run `cargo run`: the findings contain the lamp and mug names, and the watched receipt identifies an operation. A slow Watcher can report lag rather than silently claim it saw every receipt.

### Python

The current Python bridge exposes the initial tab and its Work, but not explicit tab creation or Watcher streams. It supports the same execution settings. This complete example applies them to a retained initial tab.

```python
import asyncio
import yosoi as ys


async def main():
    settings = ys.SessionPolicy(
        maximum_tabs=1,
        execution_concurrency=1,
        maximum_queued_operations=4,
        yield_on_wait=True,
    )
    async with ys.session(settings=settings) as browser:
        async with browser.work() as work:
            recipe = ys.flow(
                [
                    ys.navigate("https://qscrape.dev/eshop/html/product/obj-001/"),
                    ys.wait_until(ys.exists("h1"), timeout_ms=5_000),
                ]
            )
            outcome = await recipe.invoke(work)
            outcome.require_completed()
            observation = outcome.steps[-1].receipt.observation
            if observation is not None and observation.html is not None:
                document = ys.Document.html("tab-page", observation.html)
                plan = ys.Plan(outputs=[ys.output("name", ys.css("h1").text())])
                print(document.locate(plan).values())


asyncio.run(main())
```

The configuration allows one active controller operation and up to four queued operations. The inner context retains exclusive tab control until it exits. Run `uv run python main.py`: it prints `['Arc desk lamp']`.

The bridge's single-tab surface does not gain tab creation or receipt streaming by increasing a numeric capacity setting. Those require public interfaces that this variant does not expose.

## Capacity is not a general job scheduler

Execution capacity bounds controller work. The application still owns its tasks and decides which recipes to start. A queued operation can be rejected when the queue is full; a wait can retain Work while parking outside active execution capacity.

Holding two tabs does not imply two operations run simultaneously. Conversely, a parked wait does not release its tab for another caller to mutate. Keep those boundaries explicit when introducing concurrent application tasks.

## Execution environments

The same browser task can run elsewhere when its environment supplies a compatible regular browser and preserves its sandbox and isolation. Headful execution also needs a working display; headless execution still runs a browser. A container image must provide those requirements rather than changing the recipe's meaning.

Measure startup time, task duration, and resource use for the actual workload before choosing a mode or capacity setting. A visible window alone does not supply a cost estimate.

## Next

[Yielding while waiting](yielding-while-waiting.md) shows another tab making progress while a condition wait keeps its Work.
