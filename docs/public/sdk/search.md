---
title: Search availability
description: Understand the current boundary between CLI Search and the Rust SDK facade.
order: 18
---

# Search availability

The repository contains a Search implementation and a CLI command, but `yosoi` does not currently export a `search` module or a Search request type. There is no supported `ys::search::new(...)` call through this facade today.

`Policy` includes stored Search configuration. That field does not imply that Search execution is available through the SDK.

## Use the available command

See [CLI Search](../cli/search.md) for provider-backed search from the terminal. Provider routes are previews pending certification. Search results are candidate URLs; fetching their destination pages is a separate operation.

## Continue in Rust

Once you have a URL, use [Requests](requests.md) to acquire it and [Contracts](contracts.md) to extract a typed record. To discover pages within a site directly through the Rust SDK, use [Map](map.md).

The implementation crate's API is broader than `yosoi`. These docs keep their runnable examples on the facade so you can see exactly what that package supports.
