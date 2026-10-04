---
title: Rust SDK
description: Fetch pages, select evidence, and turn it into typed Rust records.
order: 0
---

# Rust SDK

Yosoi gives you a small set of tools for working with web data. Fetch a page, select the parts you need, and validate them as Rust values. You can also start with a local document or discover URLs with Map.

Start with a document you already have:

```rust
use std::error::Error;
use yosoi::prelude as ys;

fn main() -> Result<(), Box<dyn Error>> {
    let document = ys::Document::html(
        "welcome.html",
        b"<main><h1>Hello, Yosoi</h1></main>".to_vec(),
    )?;
    let plan = ys::Plan::new([
        ys::output("title", ys::css("h1")?.text())?,
    ])?;

    if let ys::LocateOutcome::Matched { result } = document.locate(&plan) {
        for finding in result.findings() {
            println!("{}: {:?}", finding.output_id(), finding.value());
        }
    }
    Ok(())
}
```

This prints a `title` finding containing `Hello, Yosoi`. It runs locally, without a browser or network connection.

## Choose your next step

| I want to…                                   | Read                            |
| -------------------------------------------- | ------------------------------- |
| Add Yosoi to an application                  | [Installation](installation.md) |
| Fetch a URL                                  | [Requests](requests.md)         |
| Understand what a request returned           | [Responses](responses.md)       |
| Configure behavior and budgets               | [Policy](policy.md)             |
| Work with saved bytes                        | [Documents](documents.md)       |
| Select text, attributes, or values           | [Locators](locators.md)         |
| Extract a typed record                       | [Contracts](contracts.md)       |
| Keep valid records and inspect rejected ones | [Validation](validation.md)     |
| Discover a site's URLs                       | [Map](map.md)                   |
| Capture a page with JavaScript               | [Browser](browser.md)           |

## Imports

Examples use `use yosoi::prelude as ys;`. The prelude includes common types and the `request`, `documents`, `locators`, `contracts`, `policy`, and `map` namespaces. For explicit imports, use those modules directly, such as `yosoi::request::DocumentOutcome`.

The package name is `yosoi`; the Rust crate name is `yosoi`.

## What is available

These pages describe the current facade in this repository. [Search](search.md) and [Archive](archive.md) explain the boundary with features that exist in implementation crates but are not exported by `yosoi`.

Use the guides for workflows and the generated API reference for individual type and method signatures.
