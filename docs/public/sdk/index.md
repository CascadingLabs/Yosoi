---
title: 'SDK'
description: 'Build the same evidence-based tasks in Rust or Python.'
order: 0
---

# SDK

Construct or acquire a document, locate values, and validate a typed record. Add browser work or discovery when needed.

Install through [Install](../getting-started/install.md). Rust uses the public `yosoi` facade; Python uses `import yosoi as ys`.

## Example: locate a local heading

### Rust

```rust
use std::error::Error;
use yosoi::prelude as ys;

fn main() -> Result<(), Box<dyn Error>> {
    let document = ys::Document::html(
        "greeting",
        b"<main><h1>Hello, Yosoi</h1></main>".to_vec(),
    )?;
    let plan = ys::Plan::new([
        ys::output("title", ys::css("h1")?.text())?,
    ])?;
    let outcome = document.locate(&plan);
    if let ys::LocateOutcome::Matched { result } = outcome {
        for finding in result.findings() {
            println!("{}: {:?}", finding.output_id(), finding.value());
        }
    } else {
        return Err(std::io::Error::other("title was not located").into());
    }
    Ok(())
}
```

The Plan names the output before evaluation. A finding preserves the selected value and its coordinate. Match on the outcome rather than assuming every query succeeded.

### Python

```python
import yosoi as ys

document = ys.Document.html(
    "greeting",
    "<main><h1>Hello, Yosoi</h1></main>",
)
plan = ys.Plan(outputs=[ys.output("title", ys.css("h1").text())])
outcome = document.locate(plan)

assert outcome.status == "matched"
assert outcome.values("title") == ["Hello, Yosoi"]
print(outcome.values("title"))
```

The same Plan uses typed Python models. `values` is convenient for this small check. Keep full findings when downstream work needs coordinates or provenance.

## Choose a task

| Task                        | Page                          |
| --------------------------- | ----------------------------- |
| Fetch a URL                 | [Requests](requests.md)       |
| Interpret acquisition       | [Responses](responses.md)     |
| Configure budgets           | [Policy](policy.md)           |
| Work with bytes             | [Documents](documents.md)     |
| Select evidence             | [Locators](locators.md)       |
| Produce typed records       | [Contracts](contracts.md)     |
| Inspect rejected candidates | [Validation](validation.md)   |
| Discover site URLs          | [Map](map.md)                 |
| Search providers            | [Search](search.md)           |
| Acquire rendered evidence   | [Browser](browser.md)         |
| Compose browser actions     | [Flows](flows.md)             |
| Retain browser state        | [Sessions](sessions/index.md) |
| Preserve captures           | [Archive](archive.md)         |

## Interface differences

Shared behavior does not require identical method names, field access or
ownership syntax. Python models describe inputs and inspect results while Rust
executes native document, locator, acquisition, discovery, and Policy work.

> [!NOTE]
> **Python**
>
> Python Contract records are constructed and validated by Pydantic from
> Rust-located evidence. Rust Contracts and `RuntimeContract` use Rust-owned
> value validation. See [Packages and capabilities](packages.md) for the
> boundary.

Some browser and archive controls are Rust-only. Each affected page states its boundary. See [Packages and capabilities](packages.md) and the detailed [parity audit](../python/parity.md).

Continue with [Concepts](../concepts/index.md), or use the reference for individual signatures.
