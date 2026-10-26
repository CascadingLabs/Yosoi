---
title: 'Keeping the evidence'
description: 'Save a Document or browser run in Archive, then inspect the same evidence after the browser closes.'
order: 16
---

# Keeping the evidence

For a policy-retained Surface session that can travel in one file, follow [Archiving a surface](archiving-a-surface.md). It uses the same Archive callable described here.

The browser has closed, but we still need to explain what it observed. Archive keeps the lamp's input, receipts, and captured evidence under immutable references. We can read them later without sending another request.

We'll save a small Document first, then preserve the two-step lamp Flow from earlier lessons. These examples use the local Archive backend, which currently supports Unix filesystems. Windows callers receive an explicit unsupported-platform error.

## Example: save and restore a Document

Both programs keep the Document's identity, representation, and exact bytes. The Plan stays in the program because we only need one selection here. Archive can also save a compiled Plan when the selection itself needs to be retained.

### Rust

Use Yosoi with `tokio` and its `macros` and `rt` features in your application.

```rust
use std::error::Error;
use yosoi::{Archive, prelude as ys};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let document = ys::Document::html("lamp", b"<h1>Arc desk lamp</h1>".to_vec())?;
    let plan = ys::Plan::new([ys::output("name", ys::css("h1")?.text())?])?;
    let archive = Archive::open("lamp-evidence").await?;

    let reference = archive.write_document(&document).await?;
    println!("Saved Document: {reference}");
    let restored = archive.read_document(&reference).await?;
    println!("{:#?}", restored.locate(&plan));
    Ok(())
}
```

`write_document` saves an immutable occurrence and returns its reference. `read_document` verifies the saved profile, payload length, and digest before returning the Document. Run `cargo run`: the restored input produces `Arc desk lamp` without a network request or browser. A reference can be saved as text and parsed as `yosoi::archive::DocumentArchiveRef` in another process.

### Python

```python
import asyncio
import yosoi as ys


async def main():
    document = ys.Document.html("lamp", b"<h1>Arc desk lamp</h1>")
    plan = ys.Plan(outputs=[ys.output("name", ys.css("h1").text())])
    archive = await ys.Archive.open("lamp-evidence")

    reference = await archive.write(document)
    print("Saved Document:", reference.value)
    restored = await archive.read(reference)
    print(restored.locate(plan).values())


asyncio.run(main())
```

`write` returns a typed immutable reference; `read` uses that reference to restore the original input. Run `uv run python main.py`: the name output contains `Arc desk lamp`. Use the same methods with a Plan to retain its compiled selection. The handle keeps no files open between operations, so it needs no explicit close method.

## Example: keep a browser run

This Flow opens the lamp page and waits for its heading. Managed invocation releases its Work and closes its Session before returning the outcome. We retain that outcome, including cleanup receipts and captured observations, as an AutomationRecord.

### Rust

Enable Yosoi's `browser` feature and add `serde_json` to the application. The regular Stable browser and sandbox requirements from [Using a browser](using-a-browser.md) still apply.

```rust
use std::error::Error;
use yosoi::{Archive, prelude as ys};
use yosoi::automation_record::{AutomationRecord, AutomationRecordRef};
use yosoi::view::View;

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let outcome = ys::flow::new([
        ys::action::navigate("https://qscrape.dev/eshop/html/product/obj-001/"),
        ys::action::wait_until(
            ys::flow::Condition::Exists { selector: "h1".into() },
            5_000,
        ),
    ]).invoke().await?;
    outcome.require_completed()?;

    let record = AutomationRecord::from_flow("lamp-run", outcome)?;
    let archive = Archive::open("lamp-evidence").await?;
    let reference = record.write_to(&archive).await?;
    std::fs::write("lamp-run-ref.json", serde_json::to_vec(&reference)?)?;

    let reference: AutomationRecordRef =
        serde_json::from_slice(&std::fs::read("lamp-run-ref.json")?)?;
    let reopened = Archive::open("lamp-evidence").await?;
    let restored = AutomationRecord::read_from(&reopened, &reference).await?;
    println!("Saved operations: {}", restored.operations().len());
    for observation in restored.observations() {
        let view = View::from_observation(observation, 10)?;
        for row in view.rows() {
            println!("{}: {}", row.ordinal(), row.text_preview());
        }
    }
    Ok(())
}
```

`from_flow` retains the original recipe, step results, cleanup, failure capture when present, and the observations those receipts carried. The small reference file points to the immutable record in Archive. Reading the record returns the same evidence rather than running the recipe again. Each View prints at most ten captured elements and their text previews; the lamp's heading appears in the retained page.

### Python

The browser requirements from [Using a browser](using-a-browser.md) still apply.

```python
import asyncio
from pathlib import Path
import yosoi as ys
from yosoi.archive import AutomationRecordRef


async def main():
    outcome = await ys.flow([
        ys.navigate("https://qscrape.dev/eshop/html/product/obj-001/"),
        ys.wait_until(ys.exists("h1"), timeout_ms=5_000),
    ]).invoke()
    outcome.require_completed()

    record = ys.AutomationRecord.from_flow("lamp-run", outcome)
    archive = await ys.Archive.open("lamp-evidence")
    reference = await archive.write(record)
    path = Path("lamp-run-ref.json")
    path.write_text(reference.model_dump_json(), encoding="utf-8")

    reference = AutomationRecordRef.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    reopened = await ys.Archive.open("lamp-evidence")
    restored = await reopened.read(reference)
    print("Saved operations:", len(restored.operations))
    for observation in restored.observations:
        view = ys.View.from_observation(observation, page_size=10)
        for row in view.rows:
            print(f"{row.ordinal}: {row.text_preview}")


asyncio.run(main())
```

`from_flow` keeps the recipe, results, cleanup, failure capture when present, and captured observations. Archive validates their supported Rust record representation, including screenshot bytes and source coordinates. The reference file can be read by another process with access to the same Archive root. Each View prints at most ten captured elements and their text previews; the lamp's heading appears in the retained page.

## Inspect the same evidence later

Archive retains evidence. View gives us bounded pages of that evidence. A continuation cursor belongs to its captured observation; changing the tab, epoch, or retained HTML makes continuation fail. Text previews can be truncated, and captured HTML cannot establish current live visibility.

Keep the reference and Archive root for later inspection. Repeated writes create distinct immutable occurrences, even when the authored Document ID is the same. Missing, corrupted, or unsupported data produces an error rather than a replacement snapshot.

Saving rejected or uncertain outcomes preserves their status. The successful example checks completion because it promises a completed lamp task; an application investigating a failure can archive its outcome without that check.

Offline reuse never resumes the old Session, restores a control lease, or repeats browser effects. To interact with the site again, start an explicit new run. See [Archive](../sdk/archive.md) for the storage and replay boundaries.
