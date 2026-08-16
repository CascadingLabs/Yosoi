# Observation Boss Fights

This is Yosoi's deterministic adversarial evaluation tier for the indexed-observation kernel.

```text
tests/boss_fights/       pruning, evidence reachability, budgets, determinism
tests/evals/qa/           later model routing and defect detection
tests/evals/discovery/    later selector/extractor effectiveness
```

The full corpus design, no-auth SPA slate, and delivery order live in [`yosoi/observations/boss_fights.md`](../../yosoi/observations/boss_fights.md).

## Structure

```text
boss_fights/
├── controls/          one trivial control for HTML, DOM, AX, and network
├── html/              source-HTML adversarial workloads
├── dom/               rendered-DOM and virtualization workloads
├── ax/                accessibility semantics and omission workloads
├── network/           normalized/redacted traffic and causal episodes
├── cross_modal/       deliberate DOM/AX/network disagreements
├── episodes/          related snapshots, actions, and bounded diffs
├── generators/        deterministic fixture generators
└── scoreboard/        aggregation and threshold definitions
```

## Required workload files

```text
html/wikipedia_unique_prose/
├── manifest.toml
├── ground_truth.toml
├── artifacts/
└── test_html_wikipedia_unique_prose.py
```

- `manifest.toml` contains immutable capture identity, capabilities, budgets, prediction, and failure condition.
- `ground_truth.toml` contains evidence IDs and evaluator-only oracles independent from emitted index references.
- `artifacts/` contains frozen, content-addressed, policy-safe evidence.
- The test evaluates the implementation output against the sidecar ground truth.

## Running

```bash
uv run poe boss-fights
```

Pytest marks everything under this directory as both `boss_fight` and `eval`. Despite the `eval` mark, this tier is deterministic, offline, and provider-free.
