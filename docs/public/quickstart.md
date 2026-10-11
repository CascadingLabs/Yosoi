---
title: 'Get Started'
description: 'Install Yosoi 0.2.1 and locate a value in local HTML.'
order: 0
---

# Get Started

Install Yosoi, then read a heading from local HTML. This example needs no browser or network connection.

## Requirements

Rust projects need Rust 1.99 or newer. Python projects need CPython 3.12 through 3.15 and uv. The Python package includes its native extension and depends on Pydantic.

Yosoi is published on [crates.io](https://crates.io/crates/yosoi) and [PyPI](https://pypi.org/project/yosoi/). Python wheels vary by operating system, architecture and interpreter ABI.

## Install

### Cargo

```sh
cargo add yosoi
```

Save the Rust example below as `src/main.rs`, then run `cargo run`. Local document processing does not require browser support.

### uv

```sh
uv add yosoi
```

Save the Python example below as `example.py`, then run `uv run python example.py`. uv selects a compatible wheel when one is available for the target platform.

## Example: read a heading

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

`Document::html` retains the input bytes under the identity `greeting`. The Plan names one output, `title`. `locate` evaluates the CSS query. The loop prints the output name and its selected value.

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

`Document.html` creates the same input. The Plan names the same output. The checks confirm that locating succeeded and returned exactly the heading text.

## What happened

The document is the input, the Plan describes the query, and the outcome keeps the evidence. The selector belongs to the controlled HTML in this example; a field description alone does not discover a selector on another site.

1. Keep the supplied HTML bytes in a Document with the identity `greeting`.
2. Name the heading query `title` in the Plan.
3. Call `locate` to evaluate the Plan against that Document.
4. Check the outcome and inspect the selected heading.

## Next steps

Read [Concepts](concepts/index.md), send a [Request](sdk/requests.md), or produce a typed record with [Contracts](sdk/contracts.md).

For shell workflows, install the [CLI](cli/index.md). Browser execution also needs compatible regular Chrome or Chromium; see [Browser](sdk/browser.md).
