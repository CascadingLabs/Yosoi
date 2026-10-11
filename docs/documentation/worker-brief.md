# Documentation worker brief

Copy this brief for one bounded assignment. Replace the fields before handing it to an agent.

## Assignment

- Workstream:
- Selected source revision:
- Page-map entries:
- Allowed public files:
- Allowed tooling files:
- Explicit dependencies:
- Expected examples and fixtures:
- Required evidence level:

## Instructions

Read `docs/public/AGENTS.md`, this framework and the assigned page-map entries. Inspect the listed public Rust and Python code at the selected revision. Follow re-exports when checking behavior. Existing documentation and notebooks are secondary sources.

Write shared explanations and small Rust/Python code examples for the same task. Talk through the important calls below each block. Explain sequences with numbered steps when that makes them easier to understand. Code fences contain real public API code. Keep syntax-specific details with their corresponding variant.

Use Cargo and uv command variants. No new MDX or em dashes. Document only supported behavior. Record differences instead of inventing parity, selectors, automatic discovery or resource controls.

Stay inside the allowed files. Do not edit reference, releases, live navigation or another worker's files unless explicitly assigned. Do not modify product APIs to make an example work. Keep incomplete pages `draft: true`.

Use focused checks, one expensive command at a time. Use the existing UV environment and cache. Do not regenerate Rust reference output for a prose change. Do not publish, push or start additional agents unless instructed.

## Deliverables

1. Authored pages in the permitted scope.
2. Updated page-map status for reviewed progress, without claiming publication.
3. A completed review receipt with code pointers, commands, results and gaps.
4. A concise explanation of what the reader can now do.

## Return

Report the revision and changed files, source basis, completed examples, check results, unresolved claims, and next dependency. Distinguish a locally validated page from a browser-verified or deployed page.
