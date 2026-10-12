---
title: Documents
description: Create immutable documents from bytes and reuse their parsed representation.
order: 5
---

# Documents

A Document holds an identity, a representation profile, and immutable bytes. Create one from local data or borrow one from a [response](responses.md).

```rust
use std::error::Error;
use yosoi::prelude as ys;

fn main() -> Result<(), Box<dyn Error>> {
    let document = ys::Document::html(
        "article.html",
        b"<article><h1>A small example</h1><p>Read me.</p></article>".to_vec(),
    )?;
    let plan = ys::Plan::new([ys::output("title", ys::css("h1")?.text())?])?;
    println!("{:?}", document.locate(&plan));
    Ok(())
}
```

The identity is yours to choose. A filename or application record ID works well. It must not be empty. It is not a URL to fetch or a filename to open.

## Choose the representation

| Constructor                                      | Input                         | Query tools                              |
| ------------------------------------------------ | ----------------------------- | ---------------------------------------- |
| `Document::html(id, bytes)`                      | Source HTML                   | CSS, XPath, tree text                    |
| `Document::xml(id, bytes)`                       | Source XML                    | Namespace-aware CSS and XPath, tree text |
| `Document::json(id, bytes)`                      | JSON                          | JSON Pointer and supported JSONPath      |
| `Document::text(id, bytes)`                      | Decoded UTF-8 text            | Literal text and regex                   |
| `Document::rendered_dom(id, epoch, bytes)`       | Yosoi rendered-DOM JSON       | CSS, XPath, tree text                    |
| `Document::accessibility_tree(id, epoch, bytes)` | Yosoi accessibility-tree JSON | Role, name, text, state                  |

Choose the constructor that describes the data. A rendered DOM is a structured snapshot with node identities, not an HTML string. Browser snapshot bytes must match Yosoi's schema and document epoch. Prefer obtaining these documents through a [browser response](browser.md).

Construction validates identity and representation metadata. Parsing and locating validate the content and apply resource limits, so a successful constructor does not prove that the bytes are well formed.

## Read a file

```rust
use std::error::Error;
use yosoi::prelude as ys;

fn main() -> Result<(), Box<dyn Error>> {
    let bytes = std::fs::read("catalog.html")?;
    let document = ys::Document::html("catalog.html", bytes)?;
    println!("{}: {} bytes", document.id(), document.byte_len());
    Ok(())
}
```

`bytes()` borrows the retained bytes. `class()` gives the broad document class. `profile()` records the representation, source format, schema profile, and optional epoch.

## Parse once

Use `parse()` when several plans will inspect the same document:

```rust
use std::error::Error;
use yosoi::prelude as ys;

fn main() -> Result<(), Box<dyn Error>> {
    let document = ys::Document::html(
        "links.html",
        b"<h1>Links</h1><a href='/about'>About</a>".to_vec(),
    )?;
    let title = ys::Plan::new([ys::output("title", ys::css("h1")?.text())?])?;
    let links = ys::Plan::new([
        ys::output("href", ys::css("a[href]")?.attribute("href")?)?,
    ])?;

    let policy = ys::Policy::default();
    let parsed = document.bind(&policy).parse()?;
    println!("{:?}", parsed.locate(&title));
    println!("{:?}", parsed.locate(&links));
    Ok(())
}
```

`ParsedDocument` borrows the original document and retains its parse budget. Set the Policy before parsing. `document.locate(&plan)` is convenient for one evaluation; `document.bind(&policy).locate(&plan)` applies your own limits.

## Preserve a document's profile

For application-owned storage, keep `id()`, `profile()`, and `bytes()` together. Restore them with `Document::from_profile(...)`. This preserves the distinction between source HTML, rendered DOM, and accessibility evidence.

`DocumentEpoch` is a positive identity for a browser document generation. Coordinates from one epoch should not be interpreted against another. See the [save and reuse recipe](../cookbook/save-and-reuse.md) for a complete example.
