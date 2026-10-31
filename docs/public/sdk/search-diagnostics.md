---
title: Search capture and replay
description: Save bounded Search documents and repeat parser decisions without another provider request.
order: 19
---

# Search capture and replay

A failed Search can be worth keeping. Retain its documents explicitly, save
them through Archive, and rerun the provider parser without sending the query
again. This also works for successful captures you want to compare after a
parser change.

Ordinary searches retain attempt facts without retaining replay documents.
Diagnostic capture is optional and contains query/page content. Review captures
before sharing them.

## Example: capture one provider

Both examples send one public query to Bing, retain bounded captures, and write
a manifest beside their Archive. The examples require network access. Browser
providers additionally need a compatible browser and the Rust browser feature.

### Rust

```rust
use std::{error::Error, fs::OpenOptions, io::Write};
use yosoi::{
    Archive, Policy,
    policy::search::{Provider, Search},
};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let policy = Policy {
        search: Search::new([Provider::Bing])?.per_provider_limit(3)?,
        ..Policy::default()
    };
    let response = yosoi::search::new("photosynthesis")?
        .bind(&policy)
        .with_diagnostic_capture()
        .send()
        .await?;
    let archive = Archive::open("search-evidence").await?;
    let mut records = Vec::new();
    for provider in response.providers() {
        println!("{:?}: {:?}", provider.provider(), provider.outcome());
        for capture in provider.captures() {
            records.push(capture.save(&archive).await?);
        }
    }
    let manifest = archive
        .root()
        .join(format!("sdk-{}.json", response.request_id()));
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt as _;
        options.mode(0o600);
    }
    options
        .open(&manifest)?
        .write_all(&serde_json::to_vec_pretty(
            &serde_json::json!({"schema_version": 1, "records": records}),
        )?)?;
    println!("Replay manifest: {}", manifest.display());
    Ok(())
}
```

`with_diagnostic_capture()` opts into retaining documents. `save()` writes each
exact document through Archive and returns its portable replay record. Add
`tokio` with `macros` and `rt`, and `serde_json = "1"`, to run this complete
program. Keeping the response separate from saving lets an application handle
an Archive error while retaining the completed Search result.

### Python

```python
import asyncio
import json
import os
import yosoi as ys
from yosoi.archive import Archive
from yosoi.policy import Policy, ProviderSelection, Search


async def main():
    policy = Policy(
        search=Search(
            providers=[ProviderSelection(provider="bing")],
            max_results_per_provider=3,
            max_total_results=3,
        )
    )
    bound = ys.search.new("photosynthesis").bind(policy).with_diagnostic_capture()
    response = await bound.send()
    archive = await Archive.open("search-evidence")
    records = []
    for provider in response.providers:
        print(provider.provider, provider.outcome)
        for capture in provider.diagnostic_captures:
            record = await capture.save(archive)
            records.append(record.model_dump(mode="json"))
    manifest = archive.root / f"sdk-{response.request_id}.json"
    fd = os.open(manifest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump({"schema_version": 1, "records": records}, stream, indent=2)
    print("Replay manifest:", manifest)


asyncio.run(main())
```

`diagnostic_captures` contains owning views of the retained native documents;
they are excluded from ordinary response JSON. Saving each view explicitly
keeps persistence separate from the completed response. For automatic saving,
`await bound.send(diagnostic_archive=archive)` instead populates
`provider.captures` with replay records; a saving error raises from that call.

## What was retained

Inspect each attempt's `capture_retention` before assuming evidence exists.
Capture bytes share a per-provider quota derived from Search's retained-content
budget, separately from normalized results. Original and recovery documents
share that quota. Whole documents that do not fit are omitted rather than
truncated. Acquisition failures can have diagnostics without a projected
document to replay.

A record describes one original or recovery document. Source and rendered
representations can have different parser decisions. These records reproduce
single-document interpretation, not the complete provider's recovery sequence
or a new live Search operation.

`selected_for_parsing` identifies the representation used by the live provider.
Google's provider-owned redirect resolution is separate network work. Offline
replay does not repeat it, so a record can reproduce an unresolved-document
failure even when the live operation ultimately returned resolved candidates.

## Example: replay saved records

Use the exact manifest path printed by capture. These examples read local files
and Archive documents; they start no Requests executor or browser.

### Rust

```rust
use std::{env, error::Error, fs, path::PathBuf};
use yosoi::{Archive, search::SearchReplay};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let manifest = PathBuf::from(env::args().nth(1).ok_or("Pass a manifest path")?);
    let bundle: serde_json::Value = serde_json::from_slice(&fs::read(&manifest)?)?;
    let records: Vec<SearchReplay> = serde_json::from_value(
        bundle
            .get("records")
            .ok_or("Missing replay records")?
            .clone(),
    )?;
    let archive = Archive::open(manifest.parent().ok_or("Missing Archive root")?).await?;
    for record in records {
        let replayed = record.replay(&archive).await?.decision();
        println!(
            "{:?}: matches={}",
            record.provider,
            record.observed == replayed
        );
        println!("Saved: {:?}; replayed: {:?}", record.observed, replayed);
    }
    Ok(())
}
```

Pass the manifest path as the program's first argument. Archive restores the
exact document; replay applies that record's provider and parser bounds. A
changed parser can produce a different decision, so inspect both values when
reviewing a repair.

### Python

```python
import asyncio
import json
import sys
from pathlib import Path
from yosoi.archive import Archive
from yosoi.search import SearchReplay


async def main():
    manifest = Path(sys.argv[1])
    bundle = json.loads(manifest.read_text())
    archive = await Archive.open(manifest.parent)
    for value in bundle["records"]:
        record = SearchReplay.model_validate(value)
        replayed = await record.replay(archive)
        print(record.provider, "matches:", record.observed == replayed.decision())
        print("Saved:", record.observed, "replayed:", replayed.decision())


asyncio.run(main())
```

Pass the manifest path after the script name. The typed `SearchReplay` validates
the record before the native SDK restores and parses its document.

## Read the comparison

A matching failure is a reproduced failure. It does not establish useful
results, and a successful HTTP status does not establish a usable provider page.
Recorded HTTP blocks remain classified as blocks independently of the markup.

The same bundle works with `yosoi search replay MANIFEST`. The
[CLI Search guide](../cli/search.md) explains its report and exit codes.
Return to [SDK Search](search.md) to inspect provider outcomes and use candidate
URLs, or [Archive](archive.md) for document persistence.
