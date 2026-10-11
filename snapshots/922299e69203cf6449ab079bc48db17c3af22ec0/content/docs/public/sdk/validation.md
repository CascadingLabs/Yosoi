---
title: Validation
description: Inspect valid records, rejected fields, and the evidence behind them.
order: 13
---

# Validation

Validation turns candidate evidence into typed records. It checks cardinality, completeness, conversion, and the value type's semantic rules.

Use `.validate().require_all()?` when any rejected record should fail the operation. Match `ContractOutcome` when you want to keep valid records and inspect the rest.

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

The Tea record validates. The Coffee record has a missing required price. Its candidate remains available in the record issue.

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

## Strict mode with `require_all`

`require_all()` returns `Vec<T>` only when evaluation has no record issues or extraction diagnostics. It returns an empty vector for `NoMatch`, so require a nonempty result separately if your application needs at least one record. Indeterminate and failed outcomes return errors.

If you need detailed rejection reasons, inspect the outcome before consuming it with `require_all()`. The convenience error summarizes rejection rather than retaining every field issue.

## Money

`Money` currently represents nonnegative USD amounts. Its text parser accepts `$`, whole ASCII digits, a decimal point, and exactly two fractional digits, such as `$4.50`.

| Input                                                  | Result                                |
| ------------------------------------------------------ | ------------------------------------- |
| `$4.50`                                                | 450 minor units, `Currency::Usd`      |
| `$0.00`                                                | Valid zero amount                     |
| `$-1.00`                                               | Semantic validation failure           |
| `4.50`, `$4.5`, `$1,000.00`, or surrounding whitespace | Conversion failure                    |
| An attribute or JSON projection                        | Unsupported projected value for Money |

Use `minor_units()` for the exact integer amount, `currency()` for the currency, and `Display` for the formatted value. Other currencies are not supported by this type today.

## Keep enough evidence

Field issues distinguish missing or excessive values, incomplete evidence, unsupported projections, conversion failures, and semantic failures. Their evidence points back to the source findings. Candidate fields expose that same provenance for valid records.

This evidence can contain source content. Choose what to retain and display in your application; a debug representation is not a substitute for inspecting the typed outcome.
