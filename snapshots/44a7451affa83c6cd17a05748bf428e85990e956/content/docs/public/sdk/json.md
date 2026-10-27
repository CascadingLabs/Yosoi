---
title: JSON
description: Select JSON values with JSON Pointer and a small JSONPath subset.
order: 9
---

# JSON

Use JSON Pointer for a known path and JSONPath for simple array selection. Both return JSON values through `.value()`.

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

## Walk through the result

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

For Rust `RuntimeContract`, JSON findings remain `ProjectedValue::Json`. Its
`String` conversion accepts text and attribute projections; it does not coerce
a JSON string. Read JSON values directly in your application, or explicitly
convert them before constructing a runtime Contract value.

> [!NOTE]
> **Python**
>
> A Python Contract validates the projected value through Pydantic. A custom
> Pydantic model can accept a text or JSON projection when its schema or
> validators support that input. This Python behavior does not extend the
> portable Rust `RuntimeContract` value vocabulary.

See [Locators](locators.md) for evidence coordinates and outcome handling.
