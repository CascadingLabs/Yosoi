# QA Index Spike — headless DOM index with a falsifiable gate

Self-contained spike. Touches **nothing** under `yosoi/`. Disposable by construction.

## The question

Can we turn a large page into a small, *navigable* representation an agent walks
efficiently — without silently dropping the region that contains the bug?

Not compression. **Addressing**: a flat index the agent always holds, plus one hop
to detail. (Flat, not hierarchical — see Prior art.)

## The gate

> Beat `pruned-AXTree` on **Minimal Defect Set (MDS) coverage** at ≤ its token budget.

Until that number exists and is beaten, no network layer, no CLI, no MCP.

**MDS** = the smallest set of elements/episodes required to *notice a given defect*.
Adapted from Minimal Failure Sets (Revisiting Observation Reduction, arXiv:2605.29397),
where coverage correlated ρ>0.8 with end-to-end task success at 100–290× lower cost.
Coverage = fraction of (page, defect) pairs whose full MDS survives the reduction.

## Loop

| Stage | What | Why it's ordered here |
|-------|------|-----------------------|
| **L0** | Freeze captures of the corpus | Offline + deterministic. Otherwise every iteration re-crawls and you debug network flake instead of the index. |
| **L1** | Label MDS (inject defects into frozen captures) | Expensive, unglamorous, and **everything downstream is worthless without it**. Write labels *before* building the index. |
| **L2** | Baselines: raw HTML, AX tree, pruned-AXTree | Skip this and there is no gate and no comparability to the literature. |
| **L3** | Iterate the index, one change per turn, append to scoreboard | Deterministic pruning only. No LLM in the loop yet. |
| **L4** | Gate → then and only then, network capture gets *indexed* | Capture happens at L0 regardless; see below. |

### Capture network at L0 even though we index it at L4

Traces are only recordable at capture time. They cannot be retroactively added to an
index already built, and re-crawling to backfill is the exact cost we're avoiding.
Same call as CAS-102 (capture-first, record rich now, defer the compile).

## Non-goals (deliberate)

No CLI. No MCP. No contract integration. No headful. No LLM-authored pruning.
Each is a phase-2 decision the scoreboard should make for us, not a thing we assume.

## Known limits, stated up front

- **MDS labeling is subjective** → labels are written before the index exists, so they
  can't be tuned to flatter it.
- **Small N overfits** → accepted, and reported alongside every number.
- **Frozen captures structurally hide antibot / L3 defects** → accepted; headless-first
  was the decision.
- **The `dirty` lane never gates.** It is a canary for over-fitting to clean DOM,
  not a benchmark.

## Prior art this is built against

- `arXiv:2605.29397` — Minimal Failure Sets, coverage metric. **The metric comes from here.**
- `arXiv:2511.21398` — Prune4Web: LLM writes a *pruning program*, never reads the DOM.
  Matches the LLM-as-offline-compiler stance. Its pruning is task-conditioned; QA's
  "find anything wrong" is the degenerate case, so over-pruning is the failure mode we own.
- `arXiv:2607.17598` — Progressive disclosure. **Hierarchical depth actively hurts**
  (0.91 → 0.64 with a second routing level). Hence: flat index, one hop.
  Also: disclosure "buys context, not intelligence" — the win shows up at *site* scale,
  not single-page scale.
- `arXiv:2410.13825` — AgentOccam, the pruned-AXTree baseline we must beat.

## Layout

```
corpus.toml   the slate: axis, lane, pin, and a falsifiable prediction per target
capture.py    L0 — freeze captures (static HTML, rendered DOM, AX tree, network)
captures/     artifacts, content-addressed, gitignored
```

## Dogfooding VoidCrawl

`pyproject.toml` points `voidcrawl` at `../../../VoidCrawl` as an editable path
dependency. Python-side changes are live; Rust changes need a rebuild of the
extension module. Yosoi's own venv resolves `voidcrawl>=0.4` from the index
(currently a July build) — this spike deliberately does not touch that.
