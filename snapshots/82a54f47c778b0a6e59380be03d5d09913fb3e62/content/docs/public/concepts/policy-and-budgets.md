---
title: 'Policy and budgets'
description: 'Set operation choices and resource bounds with explicit units.'
order: 0
---

# Policy and budgets

Policy describes the work an operation may perform. Start with defaults, change the settings your task needs, and bind the declaration to the operation.

## Bound work at its own stage

| Stage               | Examples of bounds                                           |
| ------------------- | ------------------------------------------------------------ |
| Acquisition         | Attempt deadline, source bytes and redirects                 |
| Document evaluation | Input bytes, nodes and depth                                 |
| Location            | Matches, regions, captures and output bytes                  |
| Map                 | Scope, frontier, requests, concurrency and retention         |
| Browser actions     | Permitted actions, input/result bytes and operation duration |

A request deadline and a locator match limit bound different work. Set both when the task needs both.

## Units are part of the setting

Request `maximum_elapsed` uses integer microseconds. Flow and browser action timeout inputs shown in the guides use milliseconds. Map elapsed limits use a seconds/nanoseconds duration.

The [Policy examples](../sdk/policy.md) allow five seconds per acquisition attempt and 500 locator matches. [Limits](../sdk/limits.md) lists the supported defaults and their units.

## Binding and snapshots

Configuration is checked before an operation executes. The result preserves the effective choices used for the run.

Rust's bound Request borrows its Policy. Python's binding captures validated Policy JSON; changing the original model later does not change that existing binding.

Keep the resulting snapshot when comparing runs or preserving evidence.

## Flow scopes

A nearer action timeout takes precedence over the containing Flow's inherited timeout. A nested Flow can supply a nearer inherited value for its own actions. Returning to its parent restores the parent's scope for subsequent siblings.

Failure and cancellation also have scoped continuation choices. Choose stop behavior when a later action depends on a successful prerequisite.

See [Flows](../sdk/flows.md), [Sessions](../sdk/sessions/index.md), and [handle failures](../sdk/errors.md).
