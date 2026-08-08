# Observation Runtime Rules

## Purpose

`yosoi.observations` is the task- and provider-agnostic evidence kernel shared by QA and future discovery adapters. It models immutable multimodal captures, derives deterministic pruned views, compiles addressable indexes, and resolves bounded detail.

## Dependency boundary

- Never import `yosoi.qa`, discovery/provider code, prompts, VoidCrawl, or fetchers.
- Models are frozen value objects. Exact artifact hashes establish identity; page fingerprints remain advisory metadata.
- Pruners are deterministic and modality-local. They do not call browsers, providers, storage writes, or other pruners.
- Semantic pruning produces structured `PrunedView` values. Token-budget rendering is a separate stage.
- Pruning is recoverable through canonical artifacts, not reversible from summaries.
- Sensitive values must be redacted or excluded before an artifact becomes canonical.
- No mutable global plugin registry. Pass pruners explicitly to compilers/runtimes.

## Picking this up

Start with [`docs/plans/observation-pruning-handoff.md`](../../docs/plans/observation-pruning-handoff.md) — current state, invariants, the traps already paid for, and what to build next. Design rationale is in [`docs/plans/observation-pruning.md`](../../docs/plans/observation-pruning.md).

## Current phase

The source-HTML slice is implemented end to end — `HtmlPruner` → `ObservationIndexCompiler` → `ObservationInspector` — and gated by `tests/boss_fights/{controls,html}`. Everything else remains scaffolding: DOM, AX, and network pruning, index rendering, diffing, and filesystem persistence all still refuse.

The package is still not wired into Yosoi operations, policy, acquisition, discovery, or public top-level exports. Follow `ROADMAP.md` when replacing the remaining placeholders.
