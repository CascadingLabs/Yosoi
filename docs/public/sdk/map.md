---
title: Map
description: Discover site URLs from Rust.
order: 1
---

# Map

Map starts with a URL and returns a bounded inventory of observed pages.

## Basic usage

Inside an async function returning a compatible error:

```rust
use yosoi_sdk::prelude as ys;

let policy = ys::Policy::default();
let outcome = ys::map::new("https://example.org/")
    .bind(&policy)
    .send()
    .await?;

for page in outcome.pages() {
    println!("{}", page.url);
}
```

## Scope and limits

Policy controls discovery scope and budgets. Keep runs bounded and inspect unfinished work when a limit stops discovery.

## Next steps

Try the [discovery recipe](../cookbook/discover-and-fetch.md) or compare the [CLI command](../cli/map.md).
