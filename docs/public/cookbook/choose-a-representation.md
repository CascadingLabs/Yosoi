---
title: 'Choose a document representation'
description: 'Match the input representation and projection to the value your task needs.'
order: 0
---

# Choose a document representation

Choose the representation from the evidence available to the application. This task reads a shop name and product names from local JSON.

## Choose by input

| Input                      | Constructor or acquisition                    |
| -------------------------- | --------------------------------------------- |
| Local HTML                 | Source HTML Document                          |
| Local XML                  | XML Document with namespace-aware queries     |
| Local JSON                 | JSON Document with value projections          |
| Decoded text               | Text Document with literals or regex captures |
| Browser structure          | Request a rendered DOM capture                |
| Accessible roles and names | Request an accessibility-tree capture         |

## Example: json

### Rust

```rust
use std::error::Error;
use yosoi::prelude as ys;

fn main() -> Result<(), Box<dyn Error>> {
    let document = ys::Document::json(
        "catalog.json",
        br#"{"shop":"Corner","products":[{"name":"Tea"},{"name":"Coffee"}]}"#.to_vec(),
    )?;
    let plan = ys::Plan::new([
        ys::output("shop", ys::json_pointer("/shop")?.value())?,
        ys::output("name", ys::json_path("$.products[*].name")?.value())?,
    ])?;

    if let ys::LocateOutcome::Matched { result } = document.locate(&plan) {
        for finding in result.findings() {
            if let ys::locators::ProjectedValue::Json(value) = finding.value() {
                println!("{}: {value}", finding.output_id());
            }
        }
    }
    Ok(())
}
```

JSON Pointer selects one known field. JSONPath selects the names from the products array. Values preserve JSON scalar types.

### Python

```python
import yosoi as ys

document = ys.Document.from_json(
    "catalog.json",
    '{"shop":"Corner","products":[{"name":"Tea"},{"name":"Coffee"}]}',
)
plan = ys.Plan(outputs=[
    ys.output("shop", ys.json_pointer("/shop").value()),
    ys.output("name", ys.json_path("$.products[*].name").value()),
])
outcome = document.locate(plan)
assert outcome.values("shop") == ["Corner"]
assert outcome.values("name") == ["Tea", "Coffee"]
```

The JSON constructor is `from_json`. The two projections select the same fields and retain product order.

## Read the result

The JSON Pointer selects one known shop field. JSONPath selects each product name in array order. The value projection retains JSON types.

Use the [HTML](../sdk/html.md), [XML](../sdk/xml.md), [text](../sdk/text.md), and [accessibility](../sdk/accessibility.md) programs for the other supported representations.

A browser snapshot carries its document epoch and schema profile. Acquire the snapshot through the browser API when reading a live site, then query its immutable captured evidence.

## Failure interpretation

Inspect a constructor or Plan error when the declared shape is unsupported. Inspect the Locate outcome when evaluation is incomplete or fails. Preserve partial-capture reasons with the acquired Document.
