---
title: 'Handle failures and cancellation'
description: 'Keep accepted records, rejected candidates and uncertain effects distinct.'
order: 0
---

# Handle failures and cancellation

This task accepts a valid product while retaining the reason another product was rejected. It uses controlled local HTML, so it needs no network or browser.

## Example: validation

### Rust

```rust
use std::error::Error;
use yosoi::prelude as ys;
use ys::contracts::ContractOutcome;

#[derive(ys::Contract)]
#[ys(id = "product", description = "A product", root = ys::locator::css("article"))]
struct Product {
    #[ys(description = "Name", locator = ys::locator::css("h2").text())]
    name: String,
    #[ys(description = "USD price", locator = ys::locator::css(".price").text())]
    price: ys::Money,
}

fn main() -> Result<(), Box<dyn Error>> {
    let document = ys::Document::html(
        "catalog.html",
        b"<article><h2>Tea</h2><b class='price'>$4.50</b></article><article><h2>Coffee</h2></article>".to_vec(),
    )?;
    match Product::extract(&Product::locate(&document)?).validate() {
        ContractOutcome::Evaluated {
            records, issues, extraction_diagnostics, ..
        } => {
            for record in records {
                println!("{}: {}", record.value.name, record.value.price);
            }
            for issue in issues {
                for field in issue.fields {
                    eprintln!("{}: {:?}", field.field, field.kind);
                }
            }
            for diagnostic in extraction_diagnostics {
                eprintln!("Extraction: {diagnostic:?}");
            }
        }
        other => eprintln!("Contract outcome: {other:?}"),
    }
    Ok(())
}
```

Tea has both required fields; Coffee lacks a price. The outcome retains accepted records, rejected candidates and diagnostics.

### Python

```python
import yosoi as ys

class Product(ys.Contract):
    """A product whose required fields must be complete."""

    root = ys.css("article")
    name: str = ys.Field("Name", locator=ys.css("h2"))
    price: ys.Money = ys.Field("USD price", locator=ys.css(".price"))

document = ys.Document.html(
    "catalog.html",
    "<article><h2>Tea</h2><b class='price'>$4.50</b></article>"
    "<article><h2>Coffee</h2></article>",
)
outcome = ys.extract(document, Product).validate()
assert len(outcome.records) == 1
assert outcome.records[0].value.name == "Tea"
assert len(outcome.issues) == 1
print(outcome.records)
print(outcome.issues)
```

The checks confirm one accepted record and one rejected candidate. Keep issues beside records when partial acceptance is useful.

## Decide what the task can accept

1. Inspect the evaluated outcome.
2. Use accepted records only where partial acceptance is allowed.
3. Keep rejected candidates and field issues for diagnosis.
4. Use strict all-records acceptance when every candidate must be valid.

In the example, Tea has a required name and price. Coffee has no price, so its candidate is retained as an issue. A missing field and a conversion failure have different explanations.

## Stop dependent browser work

A Flow can continue after recoverable failures. Configure invocation stop behavior when a later action depends on a prerequisite. [Flows](../sdk/flows.md) and [Assertions](../sdk/assertions.md) show that choice in real code.

## Cancellation and cleanup

Cancellation signals that execution should stop; it does not undo an effect already dispatched to a page. Keep the returned termination and receipts.

If an action timed out after dispatch, check domain evidence before deciding whether another attempt is safe. Preserve cleanup errors beside the operation result. The [Session example](../sdk/sessions/index.md) attempts cleanup even when the task fails.

See [Errors and troubleshooting](../sdk/errors.md) for preparation, query, capture and resource-limit failures.
