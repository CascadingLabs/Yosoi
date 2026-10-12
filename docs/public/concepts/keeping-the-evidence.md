---
title: 'Keeping the evidence'
description: 'Save Documents and Plans, then retain browser receipts and captured evidence for later inspection.'
order: 16
---

# Keeping the evidence

A browser Session eventually closes. The evidence we read can remain useful: we may want to inspect a rejection, repeat a Plan against the same input, or explain what a recipe observed.

We'll return to the lamp's HTML bytes first. Preserving a Document means keeping its identity, representation profile, and bytes. We'll save the Plan alongside them so the selection choices are retained too.

## Example: save and restore a Document

These complete programs run offline and write `lamp-snapshot.json` in the current project.

### Rust

This example uses `serde` with its `derive` feature and `serde_json` in the application. Add them to an existing project with `cargo add serde --features derive` and `cargo add serde_json` if needed.

```rust
use std::error::Error;
use yosoi::prelude as ys;

#[derive(serde::Serialize, serde::Deserialize)]
struct SavedInput {
    id: ys::DocumentId,
    profile: ys::DocumentProfile,
    bytes: Vec<u8>,
    plan: ys::Plan,
}

fn main() -> Result<(), Box<dyn Error>> {
    let document = ys::Document::html("lamp", b"<h1>Arc desk lamp</h1>".to_vec())?;
    let saved = SavedInput {
        id: document.id().clone(),
        profile: document.profile(),
        bytes: document.bytes().to_vec(),
        plan: ys::Plan::new([ys::output("name", ys::css("h1")?.text())?])?,
    };
    std::fs::write("lamp-snapshot.json", serde_json::to_vec_pretty(&saved)?)?;

    let restored: SavedInput =
        serde_json::from_slice(&std::fs::read("lamp-snapshot.json")?)?;

    let document =
        ys::Document::from_profile(restored.id, restored.profile, restored.bytes)?;
    let parsed = document.parse()?;
    println!("{:#?}", parsed.locate(&restored.plan));

    Ok(())
}
```

The saved struct retains the interpretation profile and the Plan. Deserializing the Plan validates its compiled requirements. `parse()` makes the retained parsed representation explicit; several Plans can evaluate it without rebuilding the tree. Run `cargo run`: the restored Document produces the lamp name without a network request or browser.

### Python

```python
import json
from pathlib import Path
import yosoi as ys
from yosoi.documents import DocumentProfile

document = ys.Document.html("lamp", b"<h1>Arc desk lamp</h1>")
plan = ys.Plan(outputs=[ys.output("name", ys.css("h1").text())])
path = Path("lamp-snapshot.json")
path.write_text(
    json.dumps(
        {
            "id": document.id,
            "profile": document.profile.model_dump(mode="json"),
            "bytes": list(document.data),
            "plan": plan.compiled(),
        }
    ),
    encoding="utf-8",
)

saved = json.loads(path.read_text(encoding="utf-8"))
document = ys.Document.from_profile(
    saved["id"],
    DocumentProfile.model_validate(saved["profile"]),
    bytes(saved["bytes"]),
)
plan = ys.Plan.from_compiled(saved["plan"])
parsed = document.parse()
print(parsed.locate(plan).values())
```

The saved object retains the interpretation profile and the portable compiled Plan. Restoring it validates the compiled representation through the native engine. `parse()` makes the retained parsed representation explicit; several Plans can evaluate it without rebuilding the tree. Run `uv run python main.py`: it prints `['Arc desk lamp']` without a network request or browser.

## Retain the context the task needs

Saving bytes gives us repeatable input. A Policy, acquisition diagnostics, and browser receipts provide other context. Keep them when a later reader needs to explain limits, partial evidence, or an action's uncertainty.

A fresh request can observe a changed page. Evaluating saved bytes reads the retained evidence. Neither operation recreates the old live browser state.

## Keep the browser receipts too

We can retain both the operations and what they observed. Rust exposes AutomationRecord, Archive, and View for this task. Python can serialize its Flow outcome, including receipts and captured HTML, into an application-owned file. Neither restores a live Session.

## Example: save and inspect browser evidence

Both programs visit the lamp page, retain the browser evidence, and read it back after the managed Session closes.

### Rust

This example uses the browser feature and Tokio. The current Archive backend requires a supported Unix platform. It creates a local `lamp-evidence` archive directory.

```rust
use std::error::Error;
use yosoi::prelude as ys;
use yosoi::automation_record::AutomationRecord;
use ys::view::View;

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let recipe = ys::flow::new([
        ys::action::navigate("https://qscrape.dev/eshop/html/product/obj-001/"),
        ys::action::wait_until(
            ys::flow::Condition::Exists {
                selector: "h1".into(),
            },
            5_000,
        ),
    ]);

    let outcome = recipe.invoke().await?;
    outcome.require_completed()?;
    let observations = outcome
        .steps
        .iter()
        .filter_map(|step| step.receipt.observation.clone())
        .collect();
    let receipts = outcome
        .steps
        .iter()
        .map(|step| step.receipt.clone())
        .collect();
    let record = AutomationRecord::new("lamp-run", observations, receipts)?
        .with_flow_outcome(outcome)?;

    let archive = yosoi::Archive::open("lamp-evidence").await?;
    let reference = record.write_to(&archive).await?;

    let restored = AutomationRecord::read_from(&archive, &reference).await?;
    println!("Saved operations: {}", restored.operations().len());
    if let Some(observation) = restored.observations().last() {
        let view = View::from_observation(observation, 10)?;
        println!("Captured elements: {}", view.total_rows());
        println!("First page rows: {}", view.rows().len());
    }

    Ok(())
}
```

The record comes from actual Flow evidence. Reading it from Archive does not reopen the browser. The View identifies rows within the saved observation and binds continuation cursors to that source. Inspecting those rows gives no authority to click in a live tab.

The program prints the saved operation count and positive captured-element and row counts. Persist the returned record reference when another process needs to locate the same record later.

### Python

This example writes `lamp-flow.json` in the current project.

```python
import asyncio
from pathlib import Path
import yosoi as ys
from yosoi.browser import FlowOutcome


async def main():
    recipe = ys.flow(
        [
            ys.navigate("https://qscrape.dev/eshop/html/product/obj-001/"),
            ys.wait_until(ys.exists("h1"), timeout_ms=5_000),
        ]
    )

    outcome = await recipe.invoke()
    outcome.require_completed()

    path = Path("lamp-flow.json")
    path.write_text(outcome.model_dump_json(indent=2), encoding="utf-8")

    restored = FlowOutcome.model_validate_json(path.read_text(encoding="utf-8"))
    print("Saved operations:", len(restored.steps))

    plan = ys.Plan(outputs=[ys.output("name", ys.css("h1").text())])

    for step in restored.steps:
        observation = step.receipt.observation
        if observation is not None and observation.html is not None:
            document = ys.Document.html(
                observation.id, observation.html.encode("utf-8")
            )
            print(document.locate(plan).values())


asyncio.run(main())
```

The saved outcome retains the recipe, receipts, observation identities, captured HTML, and cleanup facts. Restoring it validates the Python model without launching a browser. The program prints two saved operations and reads the lamp name from retained HTML. The Plan runs locally against each captured Document.

Python does not currently expose Rust's Archive or View. This file belongs to the application; it does not provide Archive's immutable references or View's bounded rows and continuation cursors.

## Where the series leaves us

We can start with bytes, acquire evidence, wait for a page, validate records, interact with a shop, discover URLs, and control the lifetime and bounds of browser work. Saved evidence brings those results back to local input we can inspect again.
