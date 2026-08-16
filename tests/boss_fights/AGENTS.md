# Boss Fight Agent Guide

## Purpose

`tests/boss_fights/` is the deterministic, provider-free adversarial evaluation tier for `yosoi.observations`. It tests semantic pruning, exact addressing, bounded inspection, and cross-modality preservation. It does not test whether a model can perform QA or discovery.

Read these before changing a workload:

1. `tests/boss_fights/README.md`
2. `yosoi/observations/boss_fights.md`
3. `yosoi/observations/AGENTS.md`

## Hard rules

- Use `boss_fights`, never a hyphenated Python/test directory.
- Tests consume frozen, policy-safe artifacts. They never fetch a live site.
- Boss fights make no provider or LLM calls.
- Controlled fixtures and pinned self-host captures may gate; live sites never gate.
- Ground truth identifies canonical evidence through sidecar oracles. Never copy emitted `RegionRef` values into ground truth.
- Keep semantic pruning separate from tokenizer-specific rendering.
- Every index reference must resolve against the exact snapshot and artifact digest.
- Missing modalities are explicit capabilities, never empty successful views.
- Do not store credentials, cookies, authorization values, protected bodies, or unredacted secrets.
- Write the prediction and failure condition before running or tuning a pruner.
- Give test modules globally unique names, even though this directory is a package.

## Workload layout

```text
<modality>/<workload>/
├── manifest.toml
├── ground_truth.toml
├── artifacts/
└── test_<modality>_<workload>.py
```

The manifest records capture identity, available capabilities, budgets, and machine-readable predictions. Ground truth records evidence IDs and private evaluator oracles. Tests map those oracles to implementation-emitted references; fixture authors do not prescribe the implementation's addressing result.

## Metrics

Keep these states distinct:

- **retained** — evidence remains in the canonical artifact;
- **addressable** — an emitted reference resolves to the required evidence;
- **routable** — an overview enables bounded selection of that reference;
- **detected** — a QA/discovery consumer recognizes the task outcome.

Boss fights own deterministic retention/addressability and deterministic routing counters. Model routing and detection belong under `tests/evals/qa/` or `tests/evals/discovery/`.

## Commands

```bash
uv run poe boss-fights
uv run pytest tests/boss_fights/html -m boss_fight
uv run pytest tests/boss_fights/network -m boss_fight
```
