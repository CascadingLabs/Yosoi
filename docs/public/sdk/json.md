---
title: JSON
description: Select JSON values with JSON Pointer and a small JSONPath subset.
order: 9
---

# JSON

Use JSON Pointer for a known path and JSONPath for simple array selection. Both return JSON values through `.value()`.

```rust
use std::error::Error;
use yosoi_sdk::prelude as ys;

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

The `name` output yields two findings. Numbers, booleans, objects, arrays, strings, and null retain their JSON types.

## JSON Pointer

| Pointer            | Selects                  |
| ------------------ | ------------------------ |
| `""`               | The whole document       |
| `/products/0/name` | The first product's name |
| `/a~1b`            | A key named `a/b`        |
| `/a~0b`            | A key named `a~b`        |

Array indices are zero based. A missing key or index produces no finding; an invalid pointer escape is an error.

## JSONPath subset

Supported forms are `$`, `.name`, `["quoted key"]`, `[0]`, and `[*]` for array elements. Combine them as needed, such as `$.products[*]["display name"]`.

Filters, recursive descent, unions, slices, negative indices, object wildcards, and single-quoted bracket keys are not supported. Validate with `json_path(...)` before building the plan.

## Contract conversion

JSON findings remain `ProjectedValue::Json`. The current Contract `String` conversion accepts text and attribute projections; it does not coerce a JSON string. Read JSON values directly in your application, or explicitly convert them before constructing an application model.

See [Locators](locators.md) for evidence coordinates and outcome handling.
