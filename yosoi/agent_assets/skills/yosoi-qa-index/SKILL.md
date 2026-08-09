---
name: yosoi-qa-index
description: Use for bounded read-only QA over an existing Yosoi observation index.
---

# Yosoi QA Index

For a packaged CLI status check, use `uvx yosoi qa status --json`.

This surface is read-only and only reports evidence that is actually wired. It does not capture
pages, start a browser, call a model, or infer missing modalities.

## Workflow

1. Check `status` and `capabilities`. State unavailable capture, visual, network, or accessibility
   modalities explicitly; never imply that a missing modality was checked.
2. Request a bounded `overview` for the snapshot. Treat each displayed ordinal as a handle, not as
   a selector or a claim that omitted entries do not exist.
3. Use `inspect` with the snapshot and overview ordinal (the service resolves it to the exact
   `RegionRef`). Use `expand` only for a region and keep its offset/item/byte budgets bounded.
4. Use `diff` only for related snapshots. Report identity limits and truncation from the returned
   evidence instead of matching by position.
5. Report findings with exact snapshot/region references and distinguish observed facts from model
   interpretation. If evidence is absent or a call is refused, say so plainly.

Do not encode pruning or ranking rules in prompts. Do not claim a live browser, provider, screenshots,
video, actions, persistence, or security/auth wiring. The MCP launcher is only a transport over an
injected handler and fails closed when no index session is supplied.
