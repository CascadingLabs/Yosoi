---
title: 'Outcomes'
description: 'Distinguish completion, partial evidence, issues and unknown effects.'
order: 0
---

# Outcomes

An operation returning does not prove that every part succeeded.

| Result           | What to inspect                                     |
| ---------------- | --------------------------------------------------- |
| Response         | Attempts, document outcomes and termination         |
| Locate outcome   | Findings, completeness and diagnostics              |
| Contract outcome | Valid records, rejected candidates and field issues |
| Map outcome      | Inventory, unfinished work and termination          |
| Flow outcome     | Terminal state, step receipts and uncertainty       |

## Completion and completeness

A Request can finish with a partial document. A Plan can match one output while another is absent. Map can exhaust its observed frontier without knowing every URL on a site.

Keep these distinctions in application code. Do not convert failed work into an empty successful result.

## Browser effects

Receipts distinguish observed, rejected and unknown effects. Unknown effects need care because a remote page may already have changed.

A Flow can complete with issues after continuing past failures. `require_completed()` rejects that outcome. It checks terminal status; the recipe still needs assertions that establish its business result.

1. Inspect the terminal state.
2. Read unsuccessful or uncertain steps.
3. Check the domain confirmation, such as the returned order record.
4. Retain the evidence before deciding whether another attempt is safe.

For an order, confirm the order record or confirmation. A click receipt alone is insufficient.

See [Responses](../sdk/responses.md), [Validation](../sdk/validation.md) and [Flows](../sdk/flows.md).
