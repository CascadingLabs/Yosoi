---
title: 'One browser engine. Two ways to use it.'
description: '0.2.0 concept review of the Rust browser spike, typed Python models, and evidence scope.'
order: 0
---

# One browser engine. Two ways to use it.

The [refinement notebook](refinement.md) is the dedicated record of decisions,
open questions, deferred ideas and the paused implementation checkpoint.

Yosoi should make a short browser task easy, while giving you the controls to
build a larger asynchronous system. Both use the same browser engine.

For a short task, send a Request or invoke a managed Flow. Yosoi manages the Session and
tab control for you. For a longer workflow, keep a Session alive, acquire a
Work lease, and decide what runs next yourself.

## The pieces

| Piece   | What it does                                                  |
| ------- | ------------------------------------------------------------- |
| Session | Keeps browser resources and state alive, under a policy.      |
| Tab     | Identifies a page within that Session.                        |
| Work    | Gives one caller exclusive control of a particular tab.       |
| Watch   | Receives operation receipts without gaining control.          |
| Request | Acquires a document. Browser acquisition uses Sessions.       |
| Action  | Defines an operation for a Flow to execute using Work.        |
| Flow    | Describes an ordered sequence of actions and checks.          |
| Archive | Keeps records and captured evidence after the browser closes. |
| View    | Presents a bounded projection of captured evidence.           |

## A small task

“Open the page, enter a query, click Search, and check that results appeared.”
One managed Flow is enough. The caller does not need to coordinate tabs.

For one click followed by a wait for DOM, accessibility, or exact response
evidence, see [Until checks](until.md).

## A larger system

“Keep two tabs open. Let several async tasks request control. Subscribe to
results. Preserve cookies. Cancel one job without stopping the other tab.”
Use explicit Sessions, Work leases and Watchers. Your application decides
which jobs to submit; Yosoi enforces ownership and resource bounds.

## Where we are

The default workspace now contains the integrated Rust and Python 0.2.0 beta
SDK. CAS-574 is complete with local installed-wheel proof. Start with the
[current release checkpoint](release.md) and [Python browser workflows](../python/browser-workflows.md)
for shipping scope, examples and remaining gates. The concept-review history
below predates that integration.

The Rust first pass exists locally at `browser-actions-spike`, revision
`d7a16cc4`. The controlled browser and Archive tests passed in Docker on
October 5. This guide does not claim a fresh test run or a finished 0.2.0 release.

The agreed process is: **spike → concept review → serious implementation → polish**.
This guide preserves the original concept review. The current Rust and Python
Until implementation, validation, and fixture evidence are recorded on
[the Until page](until.md).

Rust examples are excerpts grounded in the spike source, rather than standalone
programs. The Until page shows the typed Python wire models; they do not transfer
Rust closure predicates. The API reference identifies its source commit; use
a preview pinned to the Until review revision when inspecting the new APIs.

Read the topics in sidebar order. Tell me **yes**, **no**, or **needs discussion**
for any topic in chat, along with what you would change. That feedback shapes
the next pass; it does not automatically approve a release.

## Decision to review

Does this layering match the product you want? In particular, should ordinary
users be able to finish a browser task without learning about Work leases?

**Recommendation:** keep automatic lifecycle management for simple use, and
expose explicit control for stateful or concurrent systems.
