# QA Runtime Roadmap

QA dogfoods the indexed observation runtime while the reusable kernel remains independent of QA semantics. Tracks B+C+D now provide a read-only async session, injectable MCP transport, honest CLI launcher, and packaged skill; capture and providers remain unwired.

## Module map

| Module | Responsibility | Planned implementation |
| --- | --- | --- |
| `capture.py` | Adapt an existing Yosoi/VoidCrawl session into policy-safe observation snapshots | Begin with read-only headless capture; do not create another browser pool. |
| `runtime.py` | Compose capture, indexing, inspection, provider execution, and reporting | Keep provider-neutral; consume existing `ModelPolicy` when wired. |
| `index.py` | Typed async session over supplied snapshots, indexes, and artifact store | Capabilities/status/overview/inspect/expand/diff; ordinals resolve internally. |
| `tools.py` | Provider-visible overview/inspect/expand/diff contracts | Shared handler; enforce hard budgets in the observation kernel. |
| `integrations/qa_index_mcp.py` | Injectable MCP transport and fail-closed launcher | Transport only; no duplicate pruning or provider system. |
| `prompts.py` | QA-specific task instructions | Add only after tool semantics stabilize; prompts must not bypass tool limits. |
| `reports.py` | Findings and run-level audit output | Preserve evidence references and distinguish observed facts from model claims. |

## Delivery sequence

1. Consume the static HTML observation slice using deterministic fixtures.
2. Add a read-only QA runtime over overview and inspect tools.
3. Integrate the Track-B session with Track-A capture/index production wiring (out of scope here).
4. Compare QA detection against the MDS benchmark; do not infer discovery fitness.
5. Add live headless DOM/AX capture through existing Yosoi acquisition seams.
6. Add bounded provider loops through OpenCode and API-backed providers.
7. Add action episodes and diffs only after read-only behavior is stable.
8. Add network, visual evidence, interrupts, and human handoff as separate security-reviewed slices.

## Non-goals for the scaffold

- No capture/provider execution; `yosoi qa mcp` and `yosoi-qa-index-mcp` fail closed without injected evidence.
- No `Policy` wiring.
- No browser/provider imports.
- No persistence beyond observation-store test doubles.
- No production discovery authority.
