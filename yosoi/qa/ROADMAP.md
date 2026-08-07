# QA Runtime Roadmap

QA dogfoods the indexed observation runtime while the reusable kernel remains independent of QA semantics.

## Module map

| Module | Responsibility | Planned implementation |
| --- | --- | --- |
| `capture.py` | Adapt an existing Yosoi/VoidCrawl session into policy-safe observation snapshots | Begin with read-only headless capture; do not create another browser pool. |
| `runtime.py` | Compose capture, indexing, inspection, provider execution, and reporting | Keep provider-neutral; consume existing `ModelPolicy` when wired. |
| `tools.py` | Provider-visible overview/inspect/diff/check-selector contracts | Start with overview and inspect; enforce hard budgets in handlers. |
| `prompts.py` | QA-specific task instructions | Add only after tool semantics stabilize; prompts must not bypass tool limits. |
| `reports.py` | Findings and run-level audit output | Preserve evidence references and distinguish observed facts from model claims. |

## Delivery sequence

1. Consume the static HTML observation slice using deterministic fixtures.
2. Add a read-only QA runtime over overview and inspect tools.
3. Compare QA detection against the MDS benchmark; do not infer discovery fitness.
4. Add live headless DOM/AX capture through existing Yosoi acquisition seams.
5. Add bounded provider loops through OpenCode and API-backed providers.
6. Add action episodes and diffs only after read-only behavior is stable.
7. Add network, visual evidence, interrupts, and human handoff as separate security-reviewed slices.

## Non-goals for the scaffold

- No executable CLI runtime or top-level public API; `yosoi qa` exposes help/status only.
- No `Policy` wiring.
- No browser/provider imports.
- No persistence beyond observation-store test doubles.
- No production discovery authority.
