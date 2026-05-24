---
name: change-planning
description: Use when planning a Yosoi change before implementation, especially when the work crosses core modules, tests, provider behavior, or observability.
---

# Yosoi Change Planning

Goal: turn a requested Yosoi change into a scoped implementation path that respects repo boundaries.

## Method

1. Restate the user-visible or system-visible outcome.
2. Read the nearest relevant nested `AGENTS.md` files before proposing changes.
3. Identify the affected boundary:
   - `yosoi/core/`
   - `yosoi/models/`
   - `yosoi/storage/`
   - `yosoi/outputs/`
   - `yosoi/prompts/`
   - `yosoi/utils/`
   - `tests/`
4. Check whether the change touches:
   - retry behavior
   - provider configuration
   - LLM discovery logic
   - observability
   - task queue / concurrency
   - persisted selectors or debug output
5. Propose the smallest coherent implementation path.
6. Name explicit non-goals and verification needs.

## Output

- intended outcome
- docs and modules consulted
- proposed changes by boundary
- assumptions or unknowns
- non-goals
- risks
- verification needs
