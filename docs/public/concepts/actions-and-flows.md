---
title: 'Building reusable browser recipes'
description: 'Compose nested Flows and add scripts or screenshots when the task needs them.'
order: 8
---

# Building reusable browser recipes

Our cart task has a useful opening sequence: navigate to the shop and wait for the lamp. Other tasks can use that sequence too.

A Flow can contain another Flow. The child keeps its own settings, while the parent decides what happens next. This lets us compose a recipe from parts with recognizable jobs.

## Example: reuse the shop opening

These complete programs use the browser installation from the earlier lessons and modify eShop's sample cart.

### Rust

```rust
use std::error::Error;
use yosoi::prelude as ys;
use ys::policy::{Continuation, StopScope};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let open_shop = ys::flow::new([
        ys::action::navigate("https://qscrape.dev/eshop/javascript/"),
        ys::action::wait_until(
            ys::flow::Condition::Exists {
                selector: r#"article[data-product-id="obj-001"]"#.into(),
            },
            5_000,
        ),
    ])
    .timeout(5_000);

    let recipe = ys::flow::new([
        // callout: A child Flow becomes one part of this larger recipe.
        open_shop.into(),
        ys::action::click(r#"article[data-product-id="obj-001"] button"#),
        ys::action::navigate("https://qscrape.dev/eshop/javascript/cart/"),
        ys::action::wait_until(
            ys::flow::Condition::Exists {
                selector: r#"[data-shop-part="cart-line"][data-product-id="obj-001"]"#
                    .into(),
            },
            5_000,
        ),
        ys::action::screenshot(),
    ])
    .timeout(10_000)
    .on_failure(Continuation::Stop(StopScope::Invocation));

    let outcome = recipe.invoke().await?;
    outcome.require_completed()?;

    let screenshot = outcome
        .steps
        .last()
        .and_then(|step| step.receipt.observation.as_ref())
        .and_then(|observation| observation.screenshot.as_ref());
    println!("Screenshot bytes: {}", screenshot.map_or(0, Vec::len));

    Ok(())
}
```

`open_shop.into()` inserts the child recipe. Its five-second timeout supplies a fallback for its actions; the explicit wait has its own five-second bound. The parent supplies a ten-second fallback for its other unannotated actions. These are action scopes, not one total duration for the whole recipe.

The screenshot step captures evidence of the final cart page. Run `cargo run`: the positive byte count confirms that screenshot bytes were retained. The preceding cart wait is still the task's readiness check; an image alone would not validate the product's quantity or total.

### Python

```python
import asyncio
import yosoi as ys
from yosoi.browser import NestedFlow


async def main():
    open_shop = ys.flow(
        [
            ys.navigate("https://qscrape.dev/eshop/javascript/"),
            ys.wait_until(
                ys.exists('article[data-product-id="obj-001"]'), timeout_ms=5_000
            ),
        ]
    ).with_timeout_ms(5_000)

    recipe = ys.flow(
        [
            # callout: A child Flow becomes one part of this larger recipe.
            NestedFlow(flow=open_shop),
            ys.click('article[data-product-id="obj-001"] button'),
            ys.navigate("https://qscrape.dev/eshop/javascript/cart/"),
            ys.wait_until(
                ys.exists('[data-shop-part="cart-line"][data-product-id="obj-001"]'),
                timeout_ms=5_000,
            ),
            ys.screenshot(),
        ],
        on_failure=ys.policy.Stop(scope="invocation"),
    ).with_timeout_ms(10_000)

    outcome = await recipe.invoke()
    outcome.require_completed()

    observation = outcome.steps[-1].receipt.observation
    if observation is not None:
        print("Screenshot bytes:", len(observation.screenshot or b""))


asyncio.run(main())
```

`NestedFlow` inserts the child recipe. Its five-second timeout supplies a fallback for its actions; the explicit wait has its own five-second bound. The parent supplies a ten-second fallback for its other unannotated actions. These are action scopes, not one total duration for the whole recipe.

The screenshot step captures evidence of the final cart page. Run `uv run python main.py`: the positive byte count confirms that screenshot bytes were retained. The preceding cart wait is still the task's readiness check; an image alone would not validate the product's quantity or total.

## Run a small script

Sometimes the task needs a browser value that a supported locator or action doesn't provide. An Evaluate action runs an explicitly permitted script in the page.

We'll read the lamp page's title. This is our own read-only code. Enabling script evaluation is separate from allowing the website's ordinary JavaScript to run.

## Example: read the page title

### Rust

```rust
use std::error::Error;
use yosoi::prelude as ys;

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let recipe = ys::flow::new([
        ys::action::navigate("https://qscrape.dev/eshop/html/product/obj-001/"),
        ys::action::evaluate("document.title"),
    ]);
    let policy = ys::Policy::default();
    // callout: This managed invocation explicitly permits our Evaluate action.
    let outcome = recipe.bind(&policy).allow_javascript().invoke().await?;
    outcome.require_completed()?;
    if let Some(value) = outcome
        .steps
        .last()
        .and_then(|step| step.receipt.result.as_ref())
    {
        println!("{value}");
    }

    Ok(())
}
```

The recipe retains the script source. `allow_javascript()` permits evaluation when this invocation manages its Session. The receipt retains the returned value, which contains the lamp page's title. A borrowed invocation must use the permissions its existing Session already has.

### Python

```python
import asyncio
import yosoi as ys


async def main():
    recipe = ys.flow(
        [
            ys.navigate("https://qscrape.dev/eshop/html/product/obj-001/"),
            ys.evaluate("document.title"),
        ]
    )
    # callout: This managed invocation explicitly permits our Evaluate action.

    outcome = await recipe.allow_javascript().invoke()
    outcome.require_completed()
    print(outcome.steps[-1].receipt.result)


asyncio.run(main())
```

The recipe retains the script source. `allow_javascript()` permits evaluation when this invocation manages its Session. The receipt retains the returned value, which contains the lamp page's title. A borrowed invocation must use the permissions its existing Session already has.

## Keep scripts in files

A longer script can live beside the application. For the same title task, `read-title.js` contains:

```javascript
document.title;
```

The file factory reads and retains its source when we construct the recipe. The following expressions replace the inline Evaluate step in the preceding program.

## Example: retain a script file

### Rust

```rust
ys::action::evaluate_file("read-title.js")?
```

This expression runs inside the preceding `main`, whose Result propagates file and source-validation errors. Invocation uses the retained source even if the file changes afterward.

### Python

```python
ys.evaluate_file("read-title.js")
```

This expression runs inside the preceding Flow construction. File and source-validation errors are raised during construction. Invocation uses the retained source even if the file changes afterward.

## Use a module when the code needs one

A module can export a value computed in the page. `read-title.mjs` contains:

```javascript
export const title = document.title;
```

These expressions replace the Evaluate step in the same title program. The module factory retains a bounded graph of supported local imports at construction time.

## Example: retain a module

### Rust

```rust
ys::action::run_module_with_export("read-title.mjs", "title")?
```

The module is evaluated in the browser and its `title` export is read as JSON. Exported functions are not invoked by this factory. `run_module` evaluates a module without selecting a returned export. The graph must stay within its allowed local source root.

### Python

```python
ys.run_module_with_export("read-title.mjs", "title")
```

The module is evaluated in the browser and its `title` export is read as JSON. Exported functions are not invoked by this factory. `run_module` evaluates a module without selecting a returned export. The graph must stay within its allowed local source root.

## Observe the response caused by a script

A response expectation can observe the network work caused by a one-shot action. We register the observation before the action runs so a fast response is not missed.

Here, our read-only script requests the public catalog endpoint. The Until step requires GET, status 200, and a JSON count of six. It observes the browser's response; it does not construct a NetworkTree Document.

## Example: wait for a catalog response

### Rust

```rust
use std::error::Error;
use yosoi::prelude as ys;

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let recipe = ys::flow::new([
        ys::action::navigate("https://qscrape.dev/eshop/html/"),
        ys::action::evaluate("fetch('/api/eshop/products/').then(r => r.json()).then(data => data.count)")
            .until(ys::expect::response("https://qscrape.dev/api/eshop/products/")
                .method("GET").status(200).json("/count", 6)),
    ]);
    let policy = ys::Policy::default();

    let outcome = recipe.bind(&policy).allow_javascript().invoke().await?;
    outcome.require_completed()?;
    println!("Catalog response: {:?}", outcome.terminal);

    Ok(())
}
```

The Evaluate action is the trigger. Until registers its response observation before dispatch and waits for the declared fields. `require_completed()` establishes that this authored check succeeded. It does not validate every product field in the JSON.

### Python

```python
import asyncio
import yosoi as ys
from yosoi.browser import JsonMatch


async def main():
    recipe = ys.flow(
        [
            ys.navigate("https://qscrape.dev/eshop/html/"),
            ys.evaluate(
                "fetch('/api/eshop/products/').then(r => r.json()).then(data => data.count)"
            ).until(
                ys.response(
                    "https://qscrape.dev/api/eshop/products/",
                    method="GET",
                    status=200,
                    json_matches=[JsonMatch(pointer="/count", value=6)],
                ),
            ),
        ]
    )

    outcome = await recipe.allow_javascript().invoke()
    outcome.require_completed()
    print("Catalog response:", outcome.terminal)


asyncio.run(main())
```

The Evaluate action is the trigger. Until registers its response observation before dispatch and waits for the declared fields. `require_completed()` establishes that this authored check succeeded. It does not validate every product field in the JSON.

## Checks and waits

An immediate check reads current evidence once. Until observes supported evidence within a bounded scope. [Waiting for the page](waiting-for-the-page.md) introduced this distinction through the lamp's readiness condition. Dependent actions should stop when a required check fails.

## Next

[Keeping the browser open](sessions-and-ownership.md) runs separate recipes against retained browser state.
