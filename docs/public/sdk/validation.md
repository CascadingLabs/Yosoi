---
title: Validation
description: Inspect valid records, rejected fields, and the evidence behind them.
order: 13
---

# Validation

Validation checks candidate cardinality, completeness, and supported projections. Rust Contracts retain string values. Python Contracts also apply the field types and validators declared on the Pydantic model; applications own domain parsing and semantic rules.

Rust uses `.validate().require_all()?` when any rejected record should fail the operation. Python validates models automatically in `Product.extract(document)`. Use `Product.extract_report(document)` to inspect accepted records and rejected candidates without accepting the whole result.

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
    #[ys(description = "Price text", locator = ys::locator::css(".price").text())]
    price: String,
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
    price: str = ys.Field("Price text", locator=ys.css(".price"))

document = ys.Document.html(
    "catalog.html",
    "<article><h2>Tea</h2><b class='price'>$4.50</b></article>"
    "<article><h2>Coffee</h2></article>",
)
# callout: The Python report validates automatically and retains both accepted models and rejected candidate evidence.
outcome = Product.extract_report(document)
assert len(outcome.records) == 1
assert outcome.records[0].value.name == "Tea"
assert len(outcome.issues) == 1
print(outcome.records)
print(outcome.issues)
```

The report validates through Pydantic and retains one accepted record and one rejected candidate. Use `Product.extract(document)` for strict ordinary extraction, or keep this report when partial acceptance is useful.

## Walk through the result

The Tea record validates. The Coffee record has a missing required price. Its candidate remains available in the record issue.

> [!NOTE]
> **Python**
> Pydantic field and model validators run automatically during extraction. A single model rejection can raise its `ValidationError`; terminal failures and combined rejection reports use `ys.contracts.ContractIssues`. `extract_report` retains those errors and the original findings.

## Outcome states

| `ContractOutcome`    | Meaning                                                                |
| -------------------- | ---------------------------------------------------------------------- |
| `Evaluated`          | Validation produced records, record issues, and extraction diagnostics |
| `NoMatch`            | Location found no matching records                                     |
| `Indeterminate`      | Incomplete evidence prevents an absence conclusion                     |
| `LocateFailed`       | Location failed before extraction                                      |
| `ExtractionRejected` | Extraction could not accept the located evidence                       |
| `ValidationRejected` | Validation itself failed, for example at a resource bound              |

`Evaluated` does not imply every record passed. Inspect all three collections. Each `ValidatedRecord` includes both `value` and `candidate`; each `RecordIssue` retains the candidate and its field issues.

## Rust strict mode with `require_all`

`require_all()` returns `Vec<T>` only when evaluation has no record issues or extraction diagnostics. It returns an empty vector for `NoMatch`, so require a nonempty result separately if your application needs at least one record. Indeterminate and failed outcomes return errors.

If you need detailed rejection reasons, inspect the outcome before consuming it with `require_all()`. The convenience error summarizes rejection rather than retaining every field issue.

## Keep enough evidence

Field issues distinguish missing or excessive values, incomplete evidence, unsupported projections, and application validation failures. Their evidence points back to the source findings. Candidate fields expose that same provenance for valid records.

This evidence can contain source content. Choose what to retain and display in your application; a debug representation is not a substitute for inspecting the typed outcome.
