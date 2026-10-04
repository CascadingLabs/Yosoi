## Setup

Install [rustup](https://rustup.rs/), clone the repository, and run:

```bash
./scripts/bootstrap.sh
```

The bootstrap script and `rust-toolchain.toml` pin Rust 1.99.0 with rustfmt and Clippy. Bootstrap also installs cargo-nextest 0.9.106 and cargo-deny 0.19.0. `Cargo.toml` records Rust 1.99 as the current minimum supported Rust version and defines the workspace lint policy.

## Pre-commit checks

Install [prek](https://prek.j178.dev/installation/) 0.3.6 or later, then enable the repository's Git hook:

```bash
prek install
```

Commits check Rust formatting, YAML/TOML/JSON syntax, merge conflicts, private keys, trailing whitespace, and final newlines. Vendored code and test fixtures are excluded. Hooks may fix whitespace and final newlines; review and stage those changes before committing again.

Run the fast checks explicitly with `prek run --all-files`. When using JJ, run prek explicitly before review; Git commit hooks do not enforce JJ operations.

Clippy is a manual hook to keep commits fast. Run it before review with one build worker:

```bash
prek run clippy --stage manual --all-files
```

Run the dependency audit separately so expensive checks stay serial:

```bash
prek run cargo-deny --stage manual --all-files
```

This checks advisories, licenses, banned dependencies, and allowed sources using `deny.toml`. It may fetch current advisory data. For a handoff, capture each command's output and let the next agent resolve the findings; no automatic Rust or dependency fixes are applied.

Clippy treats warnings, including Rust's unused-code warnings, as errors. This does not prove that exported library APIs are used by consumers. CI remains the shared enforcement point; the full review checks are still `cargo xtask check`.

## Changes

- Keep each change focused and link it to its tracking issue.
- Use Conventional Commit-style descriptions such as `chore:`, `docs:`, `feat:`, and `fix:`.
- Use `cargo xtask test` for the standard test suite.
- Run the narrowest relevant xtask while iterating, then `cargo xtask check` before review.
- Follow the safety, abstraction, generated/vendored-code, dependency, and feature rules in [`docs/rust-policy.md`](docs/rust-policy.md).
- Follow the measurement, fixture, environment, and comparison rules in [`docs/benchmarking.md`](docs/benchmarking.md) when adding benchmarks.
- Document intentional changes to behavior or compatibility assumptions.
- Do not copy Python source, package structure, or internal architecture from Yosoi Alpha. Alpha is a behavioral reference only.

## Error handling

Use `thiserror` for typed, domain-specific errors that callers may inspect or recover from. Use `anyhow` at application boundaries where the caller needs contextual diagnostics rather than a stable error type.

Add context when propagating failures, preserve the original error source, and do not use `anyhow` to erase meaningful library or domain error types. Production code must avoid panics, unchecked indexing and slicing, unchecked arithmetic, silent `as` conversions, `unwrap`, and `expect`. Tests may use direct panics, indexing, `unwrap`, and `expect` where they make assertions clearer.

Workspace crates should inherit these dependencies with `anyhow.workspace = true` and `thiserror.workspace = true` as appropriate; a crate does not need both unless it serves both roles.

## Crate boundaries

`yosoi-types` owns dependency-light shared wire and domain vocabulary. It must remain independent of capture implementations, browsers, providers, storage, and SDK bindings. Capture behavior belongs in `yosoi-web-capture`, which may depend on `yosoi-types`; dependencies must never point in the reverse direction. Keep this direction explicit in crate manifests, and do not add a shared abstraction before a current consumer needs it.

## Pull requests

Explain the intent, relevant AI prompts, significant design choices, verification performed, and remaining risks. Justify every new dependency and enabled feature using the checklist in the Rust policy. New dependencies, frameworks, crate boundaries, safety policy, lint strictness, and policy exceptions require explicit maintainer agreement rather than being introduced incidentally.

## License

Unless explicitly stated otherwise, contributions are licensed under Apache-2.0, matching the project.
