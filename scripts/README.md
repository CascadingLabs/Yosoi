# Repository scripts

Use `cargo xtask` for standard repository tasks, including `cargo xtask docs`
and `cargo xtask sdk-boundary`.
Run scripts directly for specialized checks and local previews.

| Directory | Purpose | Standard entry point |
| --- | --- | --- |
| `benchmarks/` | Capture measurements, result directories and summaries | `cargo xtask benchmark <class>` |
| `browser/` | Browser measurements, Docker contexts and cleanup | `cargo xtask benchmark browser`, `browser-execution`, `browser-stealth`; other runners remain direct |
| `docs/` | Public-document manifests and version catalogs | `cargo xtask docs manifest <command>` |
| `fixtures/` | Fixture generation, locator corpus validation and independent oracles | Direct Python tools |
| `fuzz/` | Bounded Direct HTTP fuzz smoke checks | `cargo xtask fuzz` |
| `map/` | Map comparisons, live checks and CLI previews | Direct runners |
| `rust-reference/` | Commit-pinned SDK reference generation and verification | `cargo xtask docs reference <command>` |

`bootstrap.sh` installs the pinned Rust development tools. Measurement scripts
remain opt-in; run one expensive command at a time.

The retired CAS-520 Search container probe and preview have been removed.
Use the `yosoi search` CLI for current Search workflows. SDK visibility checks
live in `xtask/src/sdk_boundary.rs`; `SDK_CHECK_TOOLCHAIN` selects the compiler
(default: nightly). The retained tools and their standard
entry points are listed above or in `cargo xtask --help`.
