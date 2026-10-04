---
title: Save and reuse a document
description: Store a document's identity, profile, and bytes, then locate it again locally.
order: 3
---

# Save and reuse a document

To repeat location without fetching a page again, save the document bytes together with its identity and profile. Add `serde_json = "1"` to your application for this recipe.

## Save and restore

This example writes `saved-document.json` and `saved-document.bin` in the current directory, then restores the document:

```rust
use std::error::Error;
use yosoi_sdk::prelude as ys;
use ys::documents::{DocumentId, DocumentProfile};

fn main() -> Result<(), Box<dyn Error>> {
    let document = ys::Document::html(
        "catalog.html",
        b"<h1>Tea catalog</h1>".to_vec(),
    )?;
    let metadata = serde_json::to_vec(&(document.id(), document.profile()))?;
    std::fs::write("saved-document.json", metadata)?;
    std::fs::write("saved-document.bin", document.bytes())?;

    let (id, profile): (DocumentId, DocumentProfile) =
        serde_json::from_slice(&std::fs::read("saved-document.json")?)?;
    let restored = ys::Document::from_profile(
        id,
        profile,
        std::fs::read("saved-document.bin")?,
    )?;
    let plan = ys::Plan::new([ys::output("title", ys::css("h1")?.text())?])?;
    println!("{:?}", restored.locate(&plan));
    Ok(())
}
```

Keeping the profile preserves the distinction between source HTML, JSON, rendered DOM, and accessibility evidence. Browser profiles also preserve the document epoch.

## Keep the evaluation context

Store the serialized Plan and Policy alongside the document when you want to repeat the same evaluation choices. Restore the Policy and use `restored.bind(&policy).locate(&plan)`.

If the document came from a partial response, also retain the response's partial reasons. Document metadata alone does not contain every acquisition-level diagnostic.

This recipe uses application-owned files. It does not provide the repository's full archive/replay format or an atomic multi-file save. See [Archive availability](../sdk/archive.md) for the current SDK boundary.
