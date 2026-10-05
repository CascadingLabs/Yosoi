# Rust SDK documentation notes

This file is for maintainers and is excluded from published pages. The public SDK pages are ordinary Markdown; `_navigation.json` in the parent directory supplies their sidebar order. Generated API reference remains the final navigation section.

## Scope

Document the facade in `crates/yosoi`, including its actual limitations. Do not turn an implementation-crate API into an SDK example merely because it is public somewhere else in the workspace. Search is exposed by the facade and has provider-preview limitations. Archive has an availability page because archive execution and handles are not exported. The hidden `__macro` module is derive linkage, not an application namespace.

The reading path is installation, requests and responses, Policy, documents, locators by representation, contracts and validation, Map, browser acquisition, limits, and troubleshooting. Recipes connect those pieces. Concepts and the locator guide replace the skeleton's placeholder pages.

## Source map

Paths below are relative to the repository root. Follow re-exports to their implementations when checking behavior.

| Pages or claims                        | Authoritative source                                                                                                          |
| -------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| SDK surface and features               | `crates/yosoi/src/lib.rs`, `src/prelude.rs`, and `crates/yosoi/Cargo.toml`                                            |
| Requests and responses                 | `crates/yosoi/src/request/`, `crates/yosoi-engine/src/request/execution/standard.rs`                                             |
| Document ownership and constructors    | `crates/yosoi/src/documents.rs`, `crates/yosoi-documents/src/document_profile.rs`                                         |
| Locator authoring and outcomes         | `crates/yosoi-documents/src/plan_authoring.rs`, `plan_compatibility.rs`, `query_builders.rs`, `query_output.rs`, `outcome.rs` |
| XML namespace behavior                 | `crates/yosoi-documents/src/query.rs`                                                                                         |
| JSONPath subset                        | `crates/yosoi-documents/src/json/query.rs`                                                                                    |
| Accessibility matching and states      | `crates/yosoi-documents/src/accessibility/evaluate.rs`, `crates/yosoi-documents/src/query.rs`                                 |
| Contract derive and static locators    | `crates/yosoi-contracts-derive/src/lib.rs`, `support.rs`, `crates/yosoi-documents/src/locator_declaration.rs`                 |
| Contract outcomes and Money            | `crates/yosoi-contract-validation/src/outcome.rs`, `value.rs`, `validation.rs`                                                |
| Extraction limits                      | `crates/yosoi-engine/src/lib.rs`, `crates/yosoi-extractor/src/lib.rs`                                                                |
| Policy fields, defaults, serialization | `crates/yosoi-policy/src/policy/`, `policy_value.rs`, `policy_serde.rs`, `snapshot.rs`                                        |
| Map authoring and outcomes             | `crates/yosoi/src/map.rs`, `crates/yosoi-map/src/lib.rs`                                                                  |
| Map discovery, retention, and robots   | `crates/yosoi-engine/src/map/`, `crates/yosoi-policy/src/policy/map.rs`                                                              |
| Browser projection and timing          | `crates/yosoi-engine/src/projection/browser.rs`, `crates/yosoi-engine/src/request/execution/standard.rs`                                    |
| Browser distribution requirements      | `docs/chromium-cdp-baseline.md`                                                                                               |

## Editorial references

The structure takes cues from [Bun](https://bun.sh/docs), [Pydantic](https://docs.pydantic.dev/latest/), and [shadcn/ui](https://ui.shadcn.com/docs): a short explanation, an example early, focused task pages, and deeper reference material separately. The prose and examples are original and grounded in this checkout.

## Validation

Run `vpr check` from `scripts/docs` for formatting, content, links, navigation, and native Markdown rendering. This gate does not compile Rust snippets or validate a live website.

For this draft, Rust fences are extracted verbatim into a temporary Cargo package depending on the local `yosoi`, Tokio, and serde_json. Helper-function snippets receive an empty `main` only for compilation. Local examples run from a single temporary binary; the file-reading example receives a local HTML fixture. No harness or implementation code is added to the repository.

Verified on 2026-10-04 against the local 0.1.0 SDK with Rust 1.99.0:

- All 32 Rust fences compiled against the SDK's default features. Browser examples were type-checked through the same public API, without building or launching a browser adapter.
- All 22 local runnable examples completed, including XML namespaces, accessibility queries, record rejection, Policy serialization, and document save/restore. Their outputs matched the examples' described behavior.
- The formatted Markdown fences matched the compiled sources exactly.
- `vpr check` passed: 31 published Markdown pages, 3 assets, resolved navigation, native Markdown rendering, and 13 tooling tests. Local heading anchors were also checked.

Network and browser examples require their own environment and live validation. Compilation alone does not establish provider availability, browser certification, or published-site rendering.
