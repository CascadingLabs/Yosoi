---
title: Exploring a surface
description: Read a small structural view of a document, then drill into exact evidence.
---

# Exploring a surface

A Surface gives an agent a small view of a large document. It prepares structure once, then returns bounded pages as the agent explores. Preparation needs no field contract, selector, model, or task description.

Start with a document, search for a useful region, and inspect its evidence. The reference returned by the search belongs to that exact captured interpretation. A later capture can have different references even when its content looks similar.

## Example: inspect a product

These programs use the same HTML. Run the Rust program with `cargo run`, or save the Python program as `main.py` and run `uv run python main.py` in a project with the Surface-enabled SDK.

### Rust

```rust
use std::error::Error;
use yosoi::{documents::Document, surface::{Budget, Surface}};

fn main() -> Result<(), Box<dyn Error>> {
    let document = Document::html(
        "lamp", b"<main><h1>Arc desk lamp</h1><p>Stock: 3</p></main>".to_vec(),
    )?;
    let index = Surface::new(&document)?;
    let page = index.find("Arc desk lamp", None, Budget::default())?;
    for entry in page.entries {
        let evidence = index.inspect(&entry.reference, None, Budget::default())?;
        println!("{}", evidence.content);
    }
    Ok(())
}
```

`find` performs literal search over retained evidence. `inspect` follows an exact reference, so the result is backed by this document rather than an inferred description. Both calls propagate preparation, reference, and budget errors.

### Python

```python
import yosoi as ys
from yosoi import surface as sf

document = ys.Document.html(
    "lamp", "<main><h1>Arc desk lamp</h1><p>Stock: 3</p></main>"
)
index = sf.Surface(document)
page = index.find("Arc desk lamp")
for entry in page.entries:
    evidence = index.inspect(entry.reference)
    print(evidence.content)
```

The Python index owns a Rust handle. Parsing, reduction, addressing, and budget enforcement run in Rust. Python returns typed immutable results; it does not build a separate index.

## Explore without a query

Use `overview` to get routing hints, then `expand` to read a region's members. Repeated siblings can appear as one group with a member count and an exemplar. Expanding the group exposes its individual members.

HTML, XML, JSON, text, rendered DOM, and accessibility snapshots share these navigation operations. Detail stays faithful to the representation: XML and text retain source ranges, while HTML and structured snapshots use explicit normalization. They do not become interchangeable documents.

## Budget the conversation

The default Budget allows 4,096 serialized UTF-8 bytes and 20 entries per result. `next` means more evidence remains in the same operation. Copy the continuation unchanged into that operation, preserving the query and reference. Rust rejects continuations from another capture, query, or scope.

An inspection can split serialized JSON across several UTF-8-aligned chunks. Concatenate every chunk before parsing the complete value. A byte budget is a deterministic transport bound; token counts still depend on the model's tokenizer.

`coverage.complete` describes the captured source, independently of pagination. A fully read page can still come from partial evidence. A response that cannot fit one useful result fails explicitly.

## Share a reading protocol

`WebSurface` wraps an immutable HTML or rendered-DOM index with a source identity. Its shared `ReadRequest` protocol uses overview, expand, inspect, search, and parent operations. Video uses the same protocol for timeline navigation and advertises its own capabilities.

An immutable WebSurface has `controllable: false`. A reference identifies evidence; it does not confer browser access or permission to click. The [Surface CLI](../cli/surface.md) adds a live browser adapter, current eligibility checks, and explicit action authority.

For a complete network example, run `surface_read` in Rust or `python/examples/surface_read.py` in Python. Both acquire a live page, search its retained HTML, archive the Document, and reconstruct the same index. Continue with [video evidence](exploring-video.md), [keeping the evidence](keeping-the-evidence.md), or the [SDK reference guide](../sdk/surfaces.md) for cursor ownership and subscriptions.
