---
title: Installation
description: Add the Rust SDK to a local application and run your first request.
order: 1
---

# Installation

The examples here use the SDK from a local Yosoi checkout. This avoids assuming that the current facade has been published to a package registry.

## Create an application

The repository requires Rust 1.99 or newer and uses edition 2024. Its development toolchain is pinned in `rust-toolchain.toml`.

Create an application next to your checkout:

```sh
cargo new yosoi-example
cd yosoi-example
```

Add these dependencies to `Cargo.toml`. Adjust the path to point to your checkout's `crates/yosoi` directory:

```toml
[dependencies]
yosoi = { path = "../Yosoi/crates/yosoi" }
tokio = { version = "1", features = ["macros", "rt"] }
```

## Fetch your first page

Replace `src/main.rs` with:

```rust
use std::error::Error;
use yosoi::prelude as ys;
use ys::request::DocumentOutcome;

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let response = ys::request::new("https://example.org/").send().await?;

    for attempt in response.attempts() {
        println!("Attempt: {:?}, HTTP {:?}", attempt.state(), attempt.status());
        for selected in attempt.documents() {
            match selected.outcome() {
                DocumentOutcome::Produced(document) => {
                    println!("{:?}: {} bytes", document.class(), document.byte_len());
                }
                other => eprintln!("Document: {other:?}"),
            }
        }
    }
    Ok(())
}
```

Run it:

```sh
CARGO_BUILD_JOBS=1 cargo run
```

This uses Direct HTTP. Its output depends on the response from the remote site. For a fully local example, start with the [SDK overview](index.md).

## Optional dependencies

| Task                                                       | Dependency or feature                                                         |
| ---------------------------------------------------------- | ----------------------------------------------------------------------------- |
| Local documents, locators, contracts, and Policy           | `yosoi`                                                                       |
| Async Requests and Map                                     | An async runtime; these examples use Tokio                                    |
| Browser acquisition                                        | `yosoi` with `features = ["browser"]`, plus regular Chrome or Chromium Stable |
| Serialize policies, plans, or findings in your application | `serde_json = "1"`                                                            |

The SDK has no default Cargo features. Enabling `browser` makes browser acquisition available; choose it through [Policy](policy.md) to use it.

Continue with [Requests](requests.md), or [Documents](documents.md) if your input is already on disk.
