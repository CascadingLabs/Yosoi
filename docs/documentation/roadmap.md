# Shared documentation roadmap

## Outcome

Explain behavior once, then let readers select Rust or Python examples and Cargo or uv commands. Use current code as authority. Get Started → Cookbook → SDK → CLI → Concepts is the learning path; generated Reference and release notes remain separate.

The structure follows short task-oriented pages and explicit result checks, inspired by [Bun documentation](https://bun.sh/docs) and [Pydantic's model documentation](https://pydantic.dev/docs/validation/latest/concepts/models/). These are editorial references, not authorities for Yosoi behavior.

## Completed foundation

- Plain Markdown authoring rules, worker briefs, page templates and review receipts.
- Shared concepts for discovery, evidence, locators, Contracts, Policy, Sessions, Actions, Flows and outcomes.
- CLI Request, Locate, Policy, Map and Search documentation.
- SDK walkthroughs with supported Rust/Python examples and explicit availability boundaries.
- Cookbook consolidation, including bounded waits, JavaScript, observation and failure handling.
- Accessible example tabs in the frontend, with separate language/tool preferences and fallback Markdown.
- Compatibility reading paths for old design-review URLs and removal of duplicate unpublished scaffolds.
- A guard against pseudocode and unfinished authoring markers inside public code fences.

[The quality review](quality-review.md) records the evidence. Check it before treating a page as runtime-certified.

## Next review pass

| Priority | Work | Acceptance |
| --- | --- | --- |
| 1 | Read the learning path as a new user | Every page explains its input, task, result and next step |
| 2 | Verify browser examples on an eligible local runtime | Record outcome assertions, cleanup and preserved failures separately from compilation |
| 3 | Exercise provider-dependent Map and Search stories | State provider configuration and reproducible limitations beside the example |
| 4 | Review archived rendering and deep links | Variant controls remain accessible and copy only selected code |
| 5 | Publish through the existing artifact pipeline | Confirm the exact source IDs, hosted checks and deployed routes |

Do not add proposed APIs to make a story fit. Narrow the story when the current interface has a boundary. Preserve immutable published bundles and explain legacy URLs with short Markdown reading paths.

## Agent tooling and ownership

The owner currently works alone in both default workspaces. Future delegated work must be explicitly requested. The [page map](page-map.json) provides bounded file sets and code authority; [the worker brief](worker-brief.md) states scope and expected evidence. One owner edits navigation and integration files. Workers report changes needed outside their scope.

Keep checks focused and serial. Reuse a verified reference artifact to render prose; do not rebuild Rust reference merely for a Markdown edit. Record source inspection, syntax/type checking, local execution, browser execution, hosted CI and deployment as separate evidence levels.

## Markdown and example contract

Use H2 Example groups with consecutive H3 Rust/Python sections. Installation groups use H2 Install and H3 Cargo/uv. Each panel contains real code and its language-specific explanation. Shared prose stays outside the panels. The frontend handles selection, keyboard access, preference storage, copy and deep links. Markdown remains readable without enhancement.

Explain conceptual sequences with numbered prose. No new MDX, pseudocode fences, unfinished code, invented API parity or em dashes. Python commands use uv. Installation snippets use unpinned add commands in an existing project.
