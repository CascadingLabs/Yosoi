---
title: Extract structured data
description: Fetch a page and validate its heading as a Rust record.
order: 1
---

# Extract structured data

This recipe fetches a page, selects a complete HTML response, and turns its heading into a typed record.

## Fetch, locate, and validate

```rust
use std::error::Error;
use yosoi_sdk::prelude as ys;
use ys::documents::DocumentClass;
use ys::request::DocumentOutcome;

#[derive(ys::Contract)]
#[ys(id = "page_title", description = "The main heading on a page")]
struct PageTitle {
    #[ys(description = "Heading text", locator = ys::locator::css("h1").text())]
    title: String,
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let policy = ys::Policy::default();
    let response = ys::request::new("https://example.org/")
        .bind(&policy)
        .send()
        .await?;

    for attempt in response.attempts() {
        println!("Acquisition: {:?}", attempt.state());
        for selected in attempt.documents() {
            match selected.outcome() {
                DocumentOutcome::Produced(document)
                    if document.class() == DocumentClass::SourceHtml =>
                {
                    let located = document.bind(&policy).locate(PageTitle::plan()?);
                    let records = PageTitle::extract(&located).validate().require_all()?;
                    for record in records {
                        println!("{}", record.title);
                    }
                }
                other => eprintln!("Document: {other:?}"),
            }
        }
    }
    Ok(())
}
```

The document is borrowed from the response. Evaluating `PageTitle::plan()` directly avoids copying it into an owned Document.

## Adapt the record

Add fields to the struct and pin each field's locator. Use `Option<String>` for an optional field or `Vec<String>` for several values. Add a `root` selector to create one record per product card or table row.

`require_all()` rejects field issues and extraction diagnostics. For partial success, match the [validation outcome](../sdk/validation.md) and retain its valid records. If the selected response is partial, decide whether your application can use it before evaluating the Contract.

For JSON input, use [JSON locators](../sdk/json.md) and read the returned JSON values directly.
