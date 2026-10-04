---
title: Install and quickstart
description: Install Yosoi and make your first request.
order: 1
---

# Install and quickstart

Start with the CLI, then try the Rust SDK when you need to integrate Yosoi into an application.

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

Rust integrations use the `yosoi-sdk` facade. This example runs inside an async function returning a compatible error:

```rust
use yosoi_sdk::prelude as ys;

let policy = ys::Policy::default();
let outcome = ys::map::new("https://example.org/")
    .bind(&policy)
    .send()
    .await?;
```

See [SDK Map](sdk/map.md) for the next step, or follow a [cookbook recipe](cookbook/index.md).
