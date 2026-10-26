---
title: Archiving a surface
description: Save policy-retained evidence in one portable file and reload it later.
---

# Archiving a surface

A Surface session can retain the evidence behind its reads and actions. Enable `archive` in its policy, take an outcome, and pass that outcome to the same `Archive.write` and `Archive.read` calls used for other saved values.

The local Archive stores immutable values. `export_file` packages one outcome into a single portable file. You can move that file, remove the original Archive directory, and import it into another Archive in a later process. Source bytes, document profiles, exact index identities, compiled Plans and operation certainty travel with the outcome.

## Example: save a version lookup

Use the [0.4.0 candidate](../releases/0-4-0-rc-1.md) on Unix, where the local Archive backend is supported. Rust examples also need Tokio's `macros` and `rt` features. Start in a fresh directory so the export destination does not already exist.

This fixture searches the text of a version button and inspects its evidence. It does not click a live browser button. The session begins detached and needs no control authority for these reads.

### Rust

```rust
use std::{error::Error, io};
use yosoi::{
    Archive,
    documents::Document,
    surface::{ArchivePolicy, Budget, Session, SessionPolicy, Surface},
};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let document = Document::html(
        "versions",
        b"<main><button>v0.1.0</button></main>".to_vec(),
    )?;
    let session = Session::new(Surface::new(&document)?, SessionPolicy {
        archive: ArchivePolicy::Enabled,
        ..SessionPolicy::default()
    })?;
    let cursor = session.cursor()?;
    let page = cursor.find("v0.1.0", None, Budget::default())?;
    let entry = page.entries.first()
        .ok_or_else(|| io::Error::other("version missing"))?;
    println!("{}", cursor.inspect(&entry.reference, None, Budget::default())?.content);
    cursor.close()?;
    let outcome = session.close()?
        .ok_or_else(|| io::Error::other("archive policy is off"))?;
    let archive = Archive::open("version-store").await?;
    let reference = archive.write(&outcome).await?;
    archive.export_file(&reference, "version.yosoi").await?;
    Ok(())
}
```

`close` closes logical readers and revokes authority. It returns the retained outcome because archive policy was enabled. External browser or provider cleanup remains the adapter's responsibility. The exported file must have a new destination name; exports never overwrite existing files.

### Python

```python
import asyncio
from yosoi import Archive, Document
import yosoi as ys

async def main() -> None:
    document = Document.html("versions", "<main><button>v0.1.0</button></main>")
    session = ys.SurfaceSession(ys.Surface(document), ys.SurfaceSessionPolicy(archive="enabled"))
    with session.cursor() as cursor:
        page = cursor.find("v0.1.0")
        if not page.entries:
            raise RuntimeError("version missing")
        print(cursor.inspect(page.entries[0].reference).content)
    outcome = session.close()
    if outcome is None:
        raise RuntimeError("archive policy is off")
    archive = await Archive.open("version-store")
    reference = await archive.write(outcome)
    await archive.export_file(reference, "version.yosoi")

asyncio.run(main())
```

The cursor context closes its logical reader. `session.close()` returns the final immutable outcome. `await archive.write(outcome)` selects the Surface outcome branch of the normal Archive callable. No separate recording object is required.

## Example: reload in another process

Move `version.yosoi` wherever you want to read it. The original `version-store` directory is no longer required. Use a fresh local store for import.

### Rust

```rust
use std::{error::Error, io};
use yosoi::{Archive, surface::{Budget, Limits}};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let archive = Archive::open("reloaded-store").await?;
    let reference = archive.import_file("version.yosoi").await?;
    let saved = archive.read(&reference).await?;
    let source = saved.sources.first()
        .ok_or_else(|| io::Error::other("source missing"))?;
    let surface = saved.surface(&source.key, Limits::default())?;
    let page = surface.find("v0.1.0", None, Budget::default())?;
    println!("{} matches; sealed={}; complete={}",
        page.total, saved.sealed, saved.complete);
    Ok(())
}
```

`import_file` verifies the format marker, size, digest and outcome before storing it. `surface` reconstructs one retained interpretation and checks its identity. It returns immutable evidence with no live cursor or action lease.

### Python

```python
import asyncio
from yosoi import Archive

async def main() -> None:
    archive = await Archive.open("reloaded-store")
    reference = await archive.import_file("version.yosoi")
    saved = await archive.read(reference)
    if not saved.sources:
        raise RuntimeError("source missing")
    surface = saved.surface(saved.sources[0].key)
    page = surface.find("v0.1.0")
    print(f"{page.total} matches; sealed={saved.sealed}; complete={saved.complete}")

asyncio.run(main())
```

The same portable file works in either language. SHA-256 detects corruption; it does not authenticate who created the file. Treat retained URLs, page text, entered values and pixels as the original session's sensitive evidence.

## Bounds and unfinished work

Archive policy is off by default. Enabled sessions retain sources independently of the small live capture cache. The default archive limits are 64 MiB of source evidence, 256 retained sources, and 4,096 receipts. Configure `archive_limits` before creating the session. The maximum source budget is 128 MiB; the encoded portable payload is bounded at 256 MiB.

An exhausted retention budget marks the outcome `complete: false`. A source retention failure rejects publication and leaves live evidence uncertain. Operation retention exhaustion preserves earlier receipts and marks the outcome incomplete. You can still save and inspect partial outcomes. `sealed` means logical finalization was observed; it does not mean the task succeeded. Rejected attempts and unknown effects remain in the record. Closing with an outstanding action records uncertainty.

Offline replay reconstructs captured evidence and its recorded results. It does not run a saved page's JavaScript or restore browser memory. Running a task against today's live site is a separate execution with fresh observations, references, authority and eligibility checks.

## A live version change

The [Surface CLI](../cli/surface.md) includes a complete live docs-version example. With `--archive`, normal close also exports `surface.yosoi` in the output directory. Both offline replay and live repeat accept that file:

```sh
node crates/yosoi/examples/surface_cli_versions.mjs yosoi docs-version-run
yosoi surface replay --record docs-version-run/surface.yosoi --repeat 3
yosoi surface repeat --record docs-version-run/surface.yosoi --count 3 --headless --output docs-version-repeat
```

Live repeat requires a sealed, confirmed recipe with explicit target intentions and postconditions. Each repetition produces separate evidence. Video replay reads retained source and materialized frames without the original video path or decoder; decoding a new frame remains a separate capability.

Continue with [Keeping the evidence](keeping-the-evidence.md) for the wider Archive and View model.

## Example: deliberately run the live recipe again

Use the `surface.yosoi` file from the live CLI story here. The earlier static button lookup has no action recipe. Rerun validates the whole procedure before opening a browser, resolves fresh targets, and creates separate outcomes. Rust requires `browser`; Python's standard wheel includes the runtime.

### Rust

```rust
use std::{error::Error, path::PathBuf};
use yosoi::{
    Archive,
    surface::{ArchivePolicy, SurfacePolicy},
};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let archive = Archive::open("rerun-store").await?;
    let reference = archive.import_file("docs-version-run/surface.yosoi").await?;
    let saved = archive.read(&reference).await?;
    let outcomes = saved.rerun(SurfacePolicy {
        archive: ArchivePolicy::Enabled,
        output: Some(PathBuf::from("fresh-version-runs")),
        ..SurfacePolicy::default()
    }, 1).await?;
    for (index, outcome) in outcomes.iter().enumerate() {
        let reference = archive.write(outcome).await?;
        archive.export_file(&reference, format!("fresh-version-{index}.yosoi")).await?;
    }
    Ok(())
}
```

Each result is a normal archivable outcome. If execution fails after producing evidence, `ExecutionError::Execution` carries the completed and partial outcomes. They can still be written through Archive. Selecting an output directory also keeps checkpoints and artifacts for inspection.

### Python

```python
import asyncio
from pathlib import Path
from yosoi import Archive
import yosoi as ys

async def main() -> None:
    archive = await Archive.open("rerun-store")
    reference = await archive.import_file("docs-version-run/surface.yosoi")
    saved = await archive.read(reference)
    outcomes = await saved.rerun(ys.surface.SurfacePolicy(
        archive="enabled", output=Path("fresh-version-runs")
    ), count=1)
    for index, outcome in enumerate(outcomes):
        reference = await archive.write(outcome)
        await archive.export_file(reference, f"fresh-version-{index}.yosoi")

asyncio.run(main())
```

Python delegates execution to Rust. A rerun failure raises `surface.ExecutionError`; `rust_error_details(error).details["outcomes"]` retains any completed and partial outcome models as wire data. Convert each value with `surface.Outcome.model_validate` before saving it.

## Supported procedure operations

| Operation                                                | Retained evidence                                 | Live rerun                                                                 |
| -------------------------------------------------------- | ------------------------------------------------- | -------------------------------------------------------------------------- |
| Describe, overview, find, expand, inspect, parent, focus | Original inputs, results and observations         | Used to resolve new targets; exploratory reads are not replayed as effects |
| Click                                                    | Target, expectation, receipt and captures         | Requires a unique query/tag target and explicit postcondition              |
| Fill                                                     | Value, target, receipt and captures               | Requires a unique query/tag target; checks the resulting value             |
| Key                                                      | Key, target, expectation and receipt              | Requires a unique query/tag target and explicit postcondition              |
| Scroll                                                   | Deltas, expectation and receipt                   | Uses the fresh page root and an explicit postcondition                     |
| Navigate                                                 | URL, receipt and captures                         | Uses the fresh page root and checks the destination                        |
| Wait                                                     | Text expectation and observed result              | Rechecks the condition; a timeout stops the procedure                      |
| Video seek, frame, crop                                  | Frozen source/profile and actual requested pixels | Read-only evidence replay; a live effect procedure is rejected             |

Element intentions use the existing literal query/tag binding. Compiled locator Plans remain normal retained Plans; this does not introduce a new selector language. Missing intentions, ambiguous matches, stale evidence, unsupported commands, rejected effects and unknown postconditions stop execution. Rerun destinations must be new directories so earlier outcomes stay intact.
