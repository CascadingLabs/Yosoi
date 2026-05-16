---
name: verification-plan
description: Use when deciding how to validate a Yosoi change with the right mix of unit, integration, eval, static, and manual checks.
---

# Yosoi Verification Plan

Goal: choose the smallest trustworthy evidence set for a Yosoi change.

## Read first

1. `tests/AGENTS.md`
2. root `AGENTS.md`
3. `pyproject.toml` for current `poe` tasks

## Method

1. Identify the behavior that must be proven.
2. Classify the needed evidence:
   - unit / deterministic logic
   - simulated integration
   - quality eval
   - static checking / formatting
   - manual observation
3. Prefer the smallest relevant checks first, then widen only when risk requires it.
4. For bug fixes, require regression coverage when practical.
5. Distinguish deterministic checks from expensive real-model evals.
6. State remaining gaps plainly.

## Yosoi defaults

- Use `pytest`, never `unittest`.
- Prefer `uv run poe unit`, `uv run poe integration`, and `uv run poe evals` according to the tier needed.
- Use `uv run poe ci-check` before finishing when the task changes production code.
- Keep eval cost explicit when real-model tests are recommended.

## Output

- behavior to prove
- recommended test tier(s)
- exact commands
- regression or edge cases
- static checks
- manual checks if any
- intentionally unverified gaps
