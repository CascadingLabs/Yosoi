---
name: yosoi-qa-action
description: Use for bounded agent discovery over a Yosoi QA observation index with evidence-bound navigate/click actions and deterministic postconditions.
---

# Yosoi QA Action Discovery

Use only the injected `qa_*` tools. They represent one retained, capability-gated QA session.
Do not request shell, browser, selectors, JavaScript, coordinates, text input, authentication, forms,
uploads, downloads, or arbitrary payloads.

## Workflow

1. Call `qa_status` once. Stop if index, capture, actions, deterministic assertions, or A3 recording is unavailable.
2. Call `qa_overview` for the current immutable snapshot. Treat displayed ordinals as snapshot-local evidence handles, never selectors.
3. Choose at most one transition:
   - `qa_navigate` only for the exact safe HTTPS URL declared by status. Navigation success is controller-proven by exact URL identity plus a real after-capture; do not guess unseen AX labels.
   - `qa_click` only for a displayed actionable AX node in the current snapshot.
4. Before a click dispatch, declare one exact AX postcondition expected in the next capture: semantic role plus accessible name. It must be a goal-relevant destination landmark, usually the heading corresponding to the visible link. Never infer success from the action call alone.
5. Read the returned normalized receipt summary. If it is not successful and proven, stop; do not retry by guessing another target.
6. Repeat overview → one action until the requested public state is proven.
7. Call `qa_complete` only when the final indexed state proves the goal and declared fields.

## Safety and evidence rules

- A model choice is intent, not evidence. Only returned snapshots, indexes, assertions, and receipts prove state.
- Never reuse an ordinal after the snapshot changes.
- Never synthesize or edit a `RegionRef`, selector, receipt, digest, or postcondition result.
- Missing, stale, foreign, ambiguous, unsupported, or over-budget evidence fails closed.
- Keep model interpretation separate from observed public fields.
- Replay is outside this workflow; discovery records authoritative source receipts for later fixture-backed compilation.
