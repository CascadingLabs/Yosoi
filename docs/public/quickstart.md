---
title: Install and quickstart
description: Install Yosoi and make your first request.
order: 1
---

# Install and quickstart

Use the CLI for terminal workflows or the Rust SDK to build Yosoi into an application.

## Install the CLI

With Rust installed, run this from the Yosoi repository root:

```sh
CARGO_BUILD_JOBS=1 cargo install --path crates/yosoi-cli --locked
yosoi --help
```

## Fetch a page

```sh
yosoi request https://example.org/ --raw > page.html
```

## Extract a heading

```sh
set -o pipefail
yosoi request https://example.org/ | yosoi locate --css 'h1' --json
```

## Try the SDK

Follow [SDK installation](sdk/installation.md) for the Cargo dependencies, then put this in `src/main.rs`:

```rust
use std::error::Error;
use yosoi_sdk::prelude as ys;

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let response = ys::request::new("https://example.org/").send().await?;
    for attempt in response.attempts() {
        println!("{:?}: {:?}", attempt.acquisition(), attempt.state());
    }
    Ok(())
}
```

Read [Responses](sdk/responses.md) to use the returned documents, or follow the [structured extraction recipe](cookbook/extract-structured-data.md). For an example that needs no network, start with the [Rust SDK overview](sdk/index.md).
