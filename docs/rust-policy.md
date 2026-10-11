# Rust safety and dependency policy

This policy applies to first-party production code in workspace crates. `Cargo.toml`,
`clippy.toml`, `rustfmt.toml`, and `deny.toml` make the mechanical rules executable.
Run the complete local gate with:

```bash
cargo xtask check
```

Every workspace crate must contain `[lints]\nworkspace = true`; otherwise it does not inherit
the safety policy and must not be merged.

## Safety and failures

- First-party crates forbid `unsafe` code. An audited need for unsafe code must be isolated in a
  dedicated crate and approved by maintainers as a policy change; do not locally allow the lint.
- Production code returns typed errors rather than using `panic!`, `unwrap`, `expect`, unchecked
  indexing or slicing, or unchecked arithmetic. The test-only allowances in `clippy.toml` exist for
  clear assertions and test setup, not reusable production helpers.
- A lint suppression is a reviewed exception. Put it on the narrowest item, explain why the code is
  sound and clearer than the lint-compliant alternative, and cite its tracking issue. Never add a
  crate-wide `allow` merely to make a gate pass.

Generated code must live below a directory named `generated/`, identify its generator and
reproduction command in a nearby README, and be regenerated rather than hand-edited. Generated
Rust included in a first-party crate remains subject to the safety lints. Vendored source must live
below `vendor/`, retain upstream license and provenance metadata, and be excluded from workspace
membership; adding or updating it requires explicit maintainer review and dependency-policy checks.
Neither boundary is currently present in this repository.

## Comprehensible abstractions

Prefer concrete structs, enums, functions, and explicit control flow. Introduce a trait only when
there are multiple real implementations or a caller-owned testing boundary; document the boundary
and object-safety implications. Introduce generics when they remove demonstrated duplication
without obscuring errors or ownership. Avoid speculative extension points.

Rust production files target at most 400 lines. `cargo xtask source-size` rejects a new production
file above that target and prevents each explicitly grandfathered file from growing beyond its
recorded ceiling. A changed grandfathered file should move toward the target; remove its baseline
entry once it reaches 400 lines. Do not add or raise a grandfather entry as an ordinary code-change
escape hatch. `cargo xtask file-lines` separately reports all larger Rust files, including tests, and
suggests splitting cohesive code behind a small module facade. The complete `cargo xtask check` gate
includes both checks.

Architecture tests enforce the private implementation boundary and key module
dependency directions inside `crates/yosoi/src/internal`. A normal SDK build
without the `browser` feature must also exclude the vendored Chromiumoxide
controller. The publish-false `yosoi-dev-support` adapter can compile internal
modules for local benchmarks and fuzz targets; the shipped SDK does not depend
on that adapter or expose its module tree.

Declarative macros are appropriate only for repetitive syntax that ordinary functions or derives
cannot express clearly. Procedural macros require explicit maintainer approval. Macro definitions
must document generated items, accepted input, error behavior, and how to inspect expanded output.

## Dependencies and features

Before adding a dependency or enabling a feature, record in the pull request:

1. the concrete capability required and why the standard library/current graph is insufficient;
2. alternatives considered, including implementing the small behavior locally;
3. the exact features enabled, with default features disabled unless each is justified;
4. maintenance health, source/provenance, license, advisory status, and impact on the dependency
   graph, supported targets, compile time, and MSRV.

Declare shared versions in `[workspace.dependencies]`; member crates inherit them with
`workspace = true`. Use explicit compatible version requirements—wildcards are denied. Commit
`Cargo.lock`. Git dependencies and non-crates.io registries are denied until a reviewed `deny.toml`
exception names the exact source and explains why it is trusted.

Run the dependency gates directly when investigating failures:

```bash
cargo deny check advisories
cargo deny check licenses
cargo deny check bans sources
cargo tree --all-features
```

`cargo deny check` is the authoritative combined gate. Advisory ignores, license exceptions,
source allowances, duplicate-version skips, and feature allowances must be narrow entries with a
reason and tracking issue. Temporary exceptions must also state an owner and removal condition.
