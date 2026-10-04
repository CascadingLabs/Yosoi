# CAS-409 Contracts and Extractor certification

## Decision

The first typed offline pipeline is ready for Final Boss review. The stable JJ
change ID is `xmsuxoux`; its exact candidate commit and independent review are
recorded in Linear at handoff.

## Certified public model

```text
Document + pinned Contract locators or an external Plan
  -> LocateOutcome
  -> model-shaped Contract candidate extraction
  -> explicit runtime validation
  -> typed records plus precise issues and provenance
```

The locator-only stopping point remains supported. Contracts may pin static
locator data inline or by constant; those declarations compile into the same
ordinary Plan used by standalone location. Extractor performs no conversion or
validation. Validation performs no grouping or location.

## Correctness coverage

- derive/type-first Product and PageSummary Contracts;
- portable schema serialization and fixed semantic identity;
- strict schema versions plus constructor revalidation of hidden IDs;
- renamed facade extraction and validation, not only macro expansion;
- exact indexed output matching and complete RegionLineage grouping;
- scan, match, region, value, evidence, and diagnostic bounds;
- direct candidate field access and exact Finding evidence;
- raw identifiers, reserved generated names, and duplicate metadata diagnostics;
- root-presence scope inference, inline locator definitions, and referenced
  locator constants;
- cached generated Plans plus direct `Contract::locate` convenience;
- page and repeated record scopes;
- all locator terminal states;
- T, Option<T>, and Vec<T> cardinality;
- String and exact USD Money conversion;
- missing, excess, incomplete, unsupported, conversion, and semantic issues;
- precise offending evidence reserved against provenance limits before cloning;
- mixed valid and invalid sibling candidates;
- strict require-all behavior;
- exact terminal payload preservation with privacy-safe Debug;
- dimension-specific extraction and validation limits;
- custom Money deserialization preserving its non-negative invariant, including
  negative-form zero;
- real HTML and decoded-text Document/Plan pipelines.

## Architecture boundary

Recursive repository guards prevent acquisition or browser dependencies in the
new semantic crates, validation behavior in Extractor, and generated validation
hooks or callback constructors in the public prelude and source tree. Contract
locator declarations are static data compiled through the existing Plan API;
they do not add browser execution or Discovery. The previously landed Request
SDK remains available through the unified `yosoi` facade but is not invoked by
Contract location, extraction, or validation. Discovery, acquisition, Archive,
Storage, Indexing, Python, and Actions remain outside the implementation graph.

## Validation procedure

Run serially after host resource preflight:

```text
cargo xtask fmt
cargo xtask source-size
cargo xtask file-lines
cargo nextest run --workspace --all-features --test-threads 1
cargo clippy for the same targets with warnings denied
cargo test -p yosoi --doc --jobs 1
cargo xtask deny
git diff --check
```

Performance observations, if collected, are descriptive rather than budgets.
The Contracts pipeline itself needs no browser, network, hosted service, or
acquisition process.

Final post-Request-rebase evidence passed for the six affected crates and the
`yosoi` facade: focused all-target tests, one ordinary facade doctest, twelve
compile-fail Contract doctests, warnings-denied Clippy, formatting, dependency
policy, and the focused panic-free region-accounting regression. Warnings-denied
Clippy also passed for every all-feature/all-target workspace package except
`yosoi-benchmarks`; that unchanged package stops on the inherited cognitive
complexity of `benchmarks/tests/benchmark_contract.rs`.

The full-workspace Nextest run was stopped before completion to preserve the
workstation resource boundary, so no repository-wide pass or exact total is
claimed. `cargo xtask source-size` reports no Contracts/Extractor production
file above the limit; it still fails on the same ten files present in the
landed Request base. `cargo xtask file-lines` reports inherited advisory files
only.

## Deferred findings

- broader primitive and semantic Contract value types;
- comparative performance benchmarks for the new semantic pipeline;
- dynamic Contracts and Python bindings;
- defaults and arbitrary callbacks;
- nested, joined, or cross-document records;
- Discovery and enrollment generation.
