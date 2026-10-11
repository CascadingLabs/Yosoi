# 0.2.0 source CI audit

Audited on 2026-10-11 from default parent `517abee18e66c575615e4c8e36ddb74ca4d22e9c`.
This is a source-readiness audit, not a release approval. Documentation changes in this preparation do not change SDK behavior.

## Confirmed blocker

`cargo fmt --all -- --check` passed. The focused core check failed:

```sh
CARGO_BUILD_JOBS=1 RAYON_NUM_THREADS=1 cargo clippy --locked --package yosoi --lib --all-features --message-format=json -- -D warnings
```

It emitted 456 denied diagnostics. This is a core-library subset of the required workspace/all-target gate, not a complete CI failure inventory.
Raw evidence: `.local/cas562/core-clippy.jsonl` and `.local/cas562/core-clippy.log`.

| Lint | Count |
| --- | --- |
| `clippy::absolute_paths` | 279 |
| `clippy::missing_const_for_fn` | 37 |
| `clippy::significant_drop_tightening` | 30 |
| `clippy::collapsible_if` | 15 |
| `clippy::use_self` | 10 |
| `clippy::redundant_closure_for_method_calls` | 6 |
| `clippy::semicolon_if_nothing_returned` | 5 |
| `clippy::large_futures` | 5 |
| `clippy::indexing_slicing` | 5 |
| `clippy::single_match_else` | 4 |
| `clippy::match_same_arms` | 4 |
| `clippy::needless_pass_by_value` | 3 |
| `clippy::large_enum_variant` | 3 |
| `clippy::redundant_clone` | 3 |
| `clippy::derive_partial_eq_without_eq` | 3 |
| `clippy::manual_range_patterns` | 3 |
| `clippy::result_large_err` | 3 |
| `clippy::manual_let_else` | 3 |
| `clippy::as_conversions` | 3 |
| `clippy::arithmetic_side_effects` | 3 |
| `clippy::needless_return` | 3 |
| `clippy::cognitive_complexity` | 2 |
| `clippy::too_long_first_doc_paragraph` | 2 |
| `clippy::option_if_let_else` | 2 |
| `clippy::trivially_copy_pass_by_ref` | 2 |
| `clippy::used_underscore_binding` | 2 |
| `clippy::unused_async_trait_impl` | 2 |
| `clippy::unused_async` | 2 |
| `clippy::unnested_or_patterns` | 1 |
| `clippy::missing_fields_in_debug` | 1 |
| `clippy::manual_async_fn` | 1 |
| `clippy::assigning_clones` | 1 |
| `clippy::significant_drop_in_scrutinee` | 1 |
| `clippy::derivable_impls` | 1 |
| `clippy::struct_field_names` | 1 |
| `clippy::bool_to_int_with_if` | 1 |
| `clippy::manual_unwrap_or` | 1 |
| `clippy::if_same_then_else` | 1 |
| `clippy::or_fun_call` | 1 |
| `clippy::needless_pass_by_ref_mut` | 1 |

## Safety findings to review first

- `crates/yosoi/src/flow/execution.rs:390`: `clippy::indexing_slicing` — slicing may panic
- `crates/yosoi/src/flow/execution.rs:643`: `clippy::indexing_slicing` — slicing may panic
- `crates/yosoi/src/flow/execution.rs:663`: `clippy::indexing_slicing` — slicing may panic
- `crates/yosoi/src/flow/execution.rs:683`: `clippy::indexing_slicing` — slicing may panic
- `crates/yosoi/src/flow/validation.rs:227`: `clippy::as_conversions` — using a potentially dangerous silent `as` conversion
- `crates/yosoi/src/flow/validation.rs:319`: `clippy::as_conversions` — using a potentially dangerous silent `as` conversion
- `crates/yosoi/src/flow/validation.rs:359`: `clippy::indexing_slicing` — indexing may panic
- `crates/yosoi/src/flow/validation.rs:360`: `clippy::arithmetic_side_effects` — arithmetic operation that can potentially result in unexpected side-effects
- `crates/yosoi/src/flow/validation.rs:367`: `clippy::arithmetic_side_effects` — arithmetic operation that can potentially result in unexpected side-effects
- `crates/yosoi/src/flow/validation.rs:369`: `clippy::arithmetic_side_effects` — arithmetic operation that can potentially result in unexpected side-effects
- `crates/yosoi/src/view.rs:385`: `clippy::as_conversions` — using a potentially dangerous silent `as` conversion

## Bounded cleanup scope

1. Preserve all required workflow gates and lint levels. Start with safety findings: use checked arithmetic/conversions and safe access while retaining typed failure outcomes.
2. Fix import/style diagnostics mechanically where semantics stay unchanged. Review drop timing, large futures/enums and pass-by-value changes separately for cancellation, ownership and cleanup behavior.
3. Run focused regressions for changed runtime paths with one local worker. Run the full required lint gate after the core blocker is resolved, then repair additional target/test diagnostics it exposes.
4. Make the reviewed exact source available for PR/main CI. Require Rust, Python and docs results on that source; latest main success at `46f9625a` is baseline evidence only.

## Other preparation checks

- Public docs: final `vpr check` passed formatting, 73 pages, four assets, navigation, native rendering and 16 tooling tests; evidence is recorded in `.local/cas562/docs-check.log`.
- Release CD helpers: 77 tests passed; release-note helpers: eight tests passed.
- Existing release planner: five platforms, 15 wheels, 30 installed-wheel tests, crate order `yosoi-contracts-derive` then `yosoi`, and no local package-dependency blockers. This does not verify registry availability, checksums or installed artifacts.
- Version/date consistency: `cargo xtask bump-version 0.2.0 --date-released 2026-10-11 --check` passed with zero files needing updates. The initially cached xtask embedded the removed integration-workspace path; rebuilding that small binary resolved the missing-file error without source changes.
- GitHub returned no workflow runs for default parent `517abee18e66c575615e4c8e36ddb74ca4d22e9c`. Hosted success at main `46f9625a` cannot be transferred to this source.

## Release work after source CI

Use the existing release checklist in `docs/public/browser-automation-review/release.md`. Finalize bounded Archive/View wording, choose candidate or final beta/date, import authentic GitHub comparison notes against `v0.1.2`, verify metadata and registry prerequisites, and run release-profile artifact/install and platform gates. No fabricated changelog provenance or publication follows from this audit.

No full local suite or all-target build was run: the focused lint failure already establishes the next blocker. Hosted 0.2.0 CI and Release CD are unverified.
