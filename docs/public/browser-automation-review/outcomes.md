---
title: 'Say what happened, including uncertainty'
description: '0.2.0 concept review. Rust examples describe the local spike; Python examples are proposals.'
order: 8
---

# Say what happened, including uncertainty

A browser action is not a transaction. Clicking Submit can change the server
even if the client never sees confirmation.

## Three operation statuses

| Status   | What it means for the caller                                                       |
| -------- | ---------------------------------------------------------------------------------- |
| Observed | The operation produced the required observation under the current contract.        |
| Rejected | The operation or check was rejected with a known result. Inspect its receipt.      |
| Unknown  | Dispatch or effects may have occurred, but sufficient confirmation is unavailable. |

A Flow also records why it stopped, plus the receipts accumulated before that
point. Preparation and admission errors may be returned as SDK errors instead
of a completed Flow outcome.

Continuation preserves failed/cancelled results and records skipped paths with
their trigger and scope. `CompletedWithIssues` means execution finished with
retained issues; it does not mean all steps succeeded. The new structured outcome
keeps cancellation/failure cause separate from operation effects and retains
managed cleanup receipts. Durable Archive saving remains separate.

## A timeout after Submit

1. The click is dispatched.
2. The page begins a request.
3. The SDK deadline expires before confirmation.

The result must remain uncertain. Automatic retry could submit twice. The spike
fences uncertain control against reuse; the caller must close the tab or Session
and use application-specific evidence to decide whether to try again.

## Cancellation and cleanup

Cancelling before dispatch can prevent an action. Cancelling after dispatch
cannot undo it. Cleanup must account for possible outstanding effects before
resources are treated as reusable.

The spike has drop/deadline and empty-output controls, but richer terminal and
cleanup evidence is explicitly a second-pass input. Release behavior needs tests
for both Rust futures and Python task cancellation.

## Decision to review

Are explicit Unknown outcomes and no automatic action retries the right default?

**Recommendation:** yes. Offer application-controlled recovery later without
turning uncertain effects into success or blind retries.
