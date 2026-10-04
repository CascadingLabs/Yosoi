<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="media/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="media/logo-light.svg">
    <img src="media/logo-dark.svg" alt="Yosoi" width="200">
  </picture>
</p>

<h1 align="center">Yosoi</h1>
<p align="center"><strong>You Only Scrape Once (iteratively)</strong></p>
<p align="center">A Rust toolkit for turning web content into structured, traceable data.</p>

<p align="center">
  <a href="https://discord.gg/YreV3CzxsE"><img src="https://img.shields.io/badge/Discord-Join-c4d4df?labelColor=2e3742&logo=discord&logoColor=white" alt="Join Discord"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-c4d4df?labelColor=2e3742" alt="Apache 2.0 license"></a>
  <a href="Cargo.toml"><img src="https://img.shields.io/badge/Rust-1.98%2B-c4d4df?labelColor=2e3742&logo=rust&logoColor=white" alt="Rust 1.98 or later"></a>
  <a href="docs/README.md"><img src="https://img.shields.io/badge/docs-Read_the_guides-c4d4df?labelColor=2e3742" alt="Documentation"></a>
</p>

Yosoi brings page capture, reusable locators, and typed extraction into one workflow. Fetch content over HTTP or through a Chromium browser, find the fields you need, and validate them against Rust structs. Results retain their source evidence so you can inspect how each value was found.

Use the **Rust SDK** in your application or the **CLI** in scripts and terminal pipelines.

## What you can do

- **Capture web pages** through Direct HTTP or browser rendering, with explicit policies and bounded execution.
- **Locate information** in HTML, JSON, XML, text, rendered DOM, and accessibility trees using reusable plans.
- **Extract typed records** with derive-backed Contracts and explicit validation for required, optional, and repeated fields.
- **Discover website pages** with bounded mapping and source provenance.
- **Search across providers** with per-provider results and visible partial or failed outcomes. Built-in search providers are currently previews; see the [Search guide](docs/search.md).

## Get started

Install [Rust](https://rustup.rs/), then build the CLI from this checkout. The repository pins Rust 1.99.0 for development; the minimum supported version is 1.98.

```sh
CARGO_BUILD_JOBS=1 cargo install --path crates/yosoi-cli --locked
yosoi --help
```

Fetch a page and extract its heading as JSON:

```sh
set -o pipefail
yosoi request https://example.org/ | yosoi locate --css 'h1' --json
```

Or locate values in a local file:

```sh
yosoi locate --file page.html --format html --css 'h1' --json
```

See the [CLI guide](docs/cli-foundation.md) for installation options, settings, and shell completions.

## Rust SDK

Use [`yosoi-sdk`](crates/yosoi-sdk) as your application entry point. Its named modules cover documents, locators, contracts, requests, mapping, and policy; `yosoi_sdk::prelude` provides common imports.

The extraction flow keeps each step inspectable:

```rust
let located = Product::locate(&document)?;
let extracted = Product::extract(&located);
let outcome = extracted.validate();
```

Declare `Product` with `#[derive(ys::Contract)]` and pinned field locators. Rust types express cardinality: `T` requires one value, `Option<T>` accepts an optional value, and `Vec<T>` collects repeated values. Follow the [Contracts guide](docs/contracts-extractor.md) for a complete declaration and validation details.

## Documentation

- [Documentation index](docs/README.md)
- [Requests](docs/cli-requests.md) and [locating values](docs/cli-locate.md)
- [Contracts and extraction](docs/contracts-extractor.md)
- [Website mapping](docs/map.md) and [search](docs/search.md)
- [Policy and tuning](docs/policy-tuning.md)
- [Browser compatibility](docs/chromium-cdp-baseline.md)

## Development

Set up the pinned development tools with `CARGO_BUILD_JOBS=1 ./scripts/bootstrap.sh`. Run focused checks while iterating; `cargo xtask --help` lists the repository tasks. The [Rust policy](docs/rust-policy.md) documents the engineering rules.

Maintained by [Cascading Labs](https://github.com/CascadingLabs). Join the [Discord community](https://discord.gg/YreV3CzxsE) to discuss Yosoi, and see [SECURITY.md](SECURITY.md) to report a security concern.

## License

[Apache License 2.0](LICENSE).
