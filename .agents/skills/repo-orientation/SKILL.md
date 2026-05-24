---
name: repo-orientation
description: Use when starting work in Yosoi, mapping the relevant package area, or deciding which committed project docs and nested AGENTS files to inspect first.
---

# Yosoi Repo Orientation

Goal: build a correct Yosoi map from committed project truth before making changes.

## Read first

1. `AGENTS.md`
2. `CLAUDE.md` only for Claude-specific bridge guidance when relevant
3. `yosoi/AGENTS.md`
4. the nearest nested `AGENTS.md` for the module being changed
5. `tests/AGENTS.md` for test strategy
6. `pyproject.toml` for available `poe` tasks and tool configuration

## Yosoi-specific reminders

- Preserve the "discover once, scrape forever" and fail-fast philosophy.
- Use `uv`; do not fall back to `pip` or ad hoc execution.
- Core components should stay stateless.
- Respect package boundaries: fetcher/network, discovery/LLM, storage, outputs, models, and utils each have explicit rules.
- Prefer nested `AGENTS.md` files over generic Python assumptions when they disagree.

## Output

- task-relevant repo summary
- nested docs inspected
- likely modules and boundaries touched
- commands likely needed
- hazards or open questions before editing
