---
title: 'Refinement notebook: decisions and open work'
description: 'The continuing record of Andrew’s browser automation ideas, decisions and next-pass work.'
order: 0
---

# Refinement notebook: decisions and open work

This is the dedicated notebook for refining the 0.2.0 browser automation spike.
It records the discussion through October 9, 2026. Keep it current as we review
the SDK. The Linear cleanup project tracks implementation work; this page keeps
the reasoning and unresolved choices together.

The [workspace implementation plan](workspace-plan.md) maps all 15 current issues
to user decisions, code, dependencies and proof. On October 10, Andrew approved
the default parking policy: retain tab ownership and yield worker capacity.

- [Linear cleanup project](https://linear.app/cascadinglabs/project/browser-automation-refinement-and-cleanup-8a5df4c76ce7)
- [Linear refinement document](https://linear.app/cascadinglabs/document/browser-automation-refinement-decisions-ideas-and-lifecycle-plan-47ca860ee1fd)
- [Browser automation initiative](https://linear.app/cascadinglabs/initiative/020-browser-automation-7fb90980bad1)

The native Linear document is the continuing discussion record. This readable
docs page is its local companion. Update both when a decision changes.

## Where this work belongs

The initiative is **0.2.0 Browser Automation**. Treat the existing first-pass
projects as the review baseline and put refinement work in a separate cleanup
project. Their actual Linear states must be read back, not inferred from this
notebook. Final Boss is Andrew’s decision gate; the cleanup project is new work,
not evidence that the original spike was incomplete or ready for release.

Live read-back during project creation confirmed five capability projects in
Final Boss. Integration & Release was Planned. Those project states were left
intact. The six existing later-pass issues were moved into the new cleanup
project with new milestones; first-pass issues and their review history were
not moved or advanced.

The working sequence remains: tangible spike, concept review, serious integrated
implementation, then polish. Rust core was the first-pass completion gate.
Python edits exist but are parked and unverified.

## Agreed foundation

- One browser execution engine supports both automatic and advanced ownership.
- Sessions own browser resources, state, lifetime and permission policy.
- Work is an exclusive control lease on a concrete tab. Holding a Session alone
  does not grant mutation authority.
- Actions describe operations; Flows collect ordered operations and assertions.
- Requests, Actions, Flows, JavaScript and Views consume the same substrate.
  Direct HTTP Requests retain their own acquisition path.
- Watchers observe without obtaining mutation authority. A worker and multiple
  watchers can share a tab; workers need not remain permanently assigned to tabs.
- Keep partial, rejected, unsupported, unknown and cleanup failures explicit.
  Cancellation does not undo remote effects. Never blindly retry uncertain actions.

## Agreed Flow invocation spelling

```rust
steps.invoke().await?;
steps.bind(&policy).invoke().await?;
steps.with_lease(&lease).invoke().await?;
```

Without a lease, invoke acquires a Session and lease automatically and cleans up
what it owns. With a supplied lease, it borrows the current tab and leaves release
and Session close with the caller. Navigation is an explicit action in the recipe.

Rust cannot overload `invoke()` and `invoke(&lease)` on the same type. Andrew
accepted `with_lease` for Rust. Python should use an optional lease argument:

```python
await steps.invoke()
await steps.invoke(lease)
```

Python names and async context managers remain proposed; do not claim verified
Python parity. `invoke_managed` was rejected as unnecessary public vocabulary.

## Agreed timeout inputs and budget rules

**Latest contract:** [nearest timeout scope wins](timeout-scopes.md), approved
October 10 for CAS-568 implementation. The earlier total-Flow/minimum-of-parent
deadline discussion below is superseded: a child explicit override replaces
the inherited limit, even when longer. The old discussion remains as design history.

October 10 clarification supersedes the earlier microsecond proposal: raw timeout
integers are milliseconds. Explicit timeouts are optional for both actions and
Flows; omitted values inherit policy defaults. `seconds(...)` only translates
seconds to the integer millisecond input. The Policy fallback is 10,000 ms.

`.timeout(integer)` takes **milliseconds**. Unit helpers do pure conversion to
that integer. Validate zero and values that cannot form a monotonic deadline;
conversions must not panic or wrap.

```rust
action::click(target).timeout(60);           // 60 milliseconds.
action::click(target).timeout(100 * 60);     // 6,000 milliseconds = 6 s.
action::navigate(url).timeout(seconds(60)); // 60,000 milliseconds.
```

Milliseconds are an input unit, not a promise of browser scheduling precision.
Existing condition-wait and explicit-delay APIs already use milliseconds and
retain that meaning. Earlier prototype microsecond fields must not be reinterpreted
silently; reconcile or version them during implementation.

- A bound Policy supplies `default_action_timeout_ms`; a bound Flow Policy
  overrides the owning Session Policy for that invocation.
- An explicit root Flow timeout overrides that fallback. A nested Flow timeout
  overrides its parent, and an action timeout overrides its nearest Flow.
- A Flow timeout is an inherited per-action default. It does not create a total
  Flow deadline, and a longer child timeout may exceed its parent's value.
- When a nested child returns, the parent's fallback applies again to the next
  unannotated sibling.
- Target resolution, foreground waiting, command dispatch and required capture
  must consume one action budget rather than restart it for each provider call.
- Flow action timeouts do not bound Session/lease acquisition. Those lifecycle
  phases keep their own existing policy bounds.
- Cleanup gets a separate bounded budget after work stops. Returning a complete
  result may take the action time plus cleanup time.
- A parked action retains its active deadline; starting a later action resolves a
  fresh timeout from its nearest scope.

`SessionPolicy.operation_timeout_ms` remains the direct Work default outside a
Flow action scope. Unbound borrowed Flows inherit their owning Session Policy's
action default. Acquisition and cleanup override shapes remain open lifecycle
questions; no action maximum is added by this timeout contract.

## Agreed cancellation direction

**Three-level clarification:** cancellation propagates downward from its target
scope, not upward into its parent or unrelated siblings. Cancelling the root
reaches its whole subtree; cancelling the Session reaches its invocations. A
parent can remain uncancelled while responding to a cancelled child's structured
outcome. Whether it stops, skips dependent work or continues independent siblings
is a separate execution-policy decision that has not yet been selected.

**October 10 result decision:** after execution starts, cancellation returns a
structured outcome with the stop reason and retained step receipts. It does not
throw away partial execution into a generic error. Pre-execution validation or
acquisition failures can remain typed errors. Stop cause and action effect evidence
are separate: a cancelled Flow can contain an earlier Observed click and a later
Unknown operation. Final field/enum names still need shaping in CAS-569.

Every invocation is cancellable under the hood. Ordinary users should only need
`invoke()`. Explicit external references are advanced, optional control:

```rust
steps.with_cancellation(&cancel).invoke().await?;
// Another task can call cancel.cancel().
```

Use one executor, not a separate public `invoke_cancellable` mode. An internal
token supports timeout, shutdown and dropped-future handling; an external token
gives the application an accessible Stop handle.

Session cancellation stops its descendants. Cancelling an invocation must not
cancel its parent Session or unrelated work. Cancelling a queued waiter must
leave the current lease holder alone. After possible dispatch, preserve the
effect uncertainty and prevent unsafe reuse. Cleanup cannot disappear merely
because the caller stopped awaiting or dropped a future.

## Four lifecycle stories to implement together

1. Nested timeout scopes: a 10-second parent, 30-second child and explicit
   action timeout. The child may outlive its parent; the next sibling returns to
   the parent's inherited value.
2. Waiting for ownership: another task holds the tab. Acquisition waits within
   policy limits, and cancellation removes only that waiter.
3. Cancellation after Submit: the click may already have reached a server. Stop
   subsequent steps, retain receipts and uncertainty, settle or fence control.
4. Release without losing browser state: release Work, preserve Session/cookies,
   and only hand control to another writer when outstanding commands are safe.

`session.work().await` is the waiting operation; there need not be a separate
`wait_for_release` API. `lease.release().await` ends ownership; `session.close().await`
ends the Session and revokes its leases.

Release must distinguish a safe handoff, a bounded settlement attempt and a
fenced/quarantined failure. It must preserve task and cleanup errors together.
Rust Drop cannot await cleanup; a runtime owner must complete cleanup or maintain
quarantine after a caller drops the invocation/release future.

**Agreed default (October 10):** if a borrowed lease cannot establish safe release
within its cleanup budget, leave the tab fenced and return an error. Do not close
it automatically. Any automatic-close override needs separate shaping.

## Scheduling refinement: park is different from release

Andrew’s concrete example is one browser with tabs A, B, C and D and concurrency
two or four. A clicks and waits for a condition; it should give execution capacity
to other tabs immediately. The tab can keep working while its workflow is parked.
When eligible to run again, do a short check, then continue or park again. Mutating
work can queue FIFO. Eventually multiple workers and observers can use one tab.

Separate three resources:

| Resource                | Purpose                                           | During a parked wait                      |
| ----------------------- | ------------------------------------------------- | ----------------------------------------- |
| Logical tab ownership   | Protect dependent steps from unrelated mutations. | May remain reserved, according to policy. |
| Worker execution slot   | Limit active controller work.                     | Yield it so another tab can run.          |
| Foreground surface lock | Protect focus-sensitive input/capture.            | Release after that operation settles.     |

Async awaiting already yields the runtime thread. The controller must also avoid
holding scarce permits unnecessarily. Worker count, tab count and watcher count
are separate quantities. Tab selection versus automatic assignment is a policy
candidate, not a finalized API.

Prefer bounded event-driven observation and requeueing over a periodic 10 ms
busy loop. A 10 ms revisit was an illustrative aspiration, not measured capacity
or guaranteed latency. DOM reads may not need activation; focus-sensitive input,
visual assertions and screenshots have different requirements. Background tabs
can be throttled, frozen or discarded; do not assume foreground-equivalent painting.

**Agreed default (October 10):** park the workflow, yield worker capacity and
release foreground resources after safe settlement, while reserving its tab
against unrelated writers. Advanced yielding of tab ownership remains separately
shaped behavior.

**Advanced policy under discussion:** yield tab ownership too. Reacquiring it must
validate document generation, originating operation and intervening mutations.
An assertion after A’s Search must not accidentally pass against B’s new query.
Distinguish checks of current state from checks of a particular action’s effect.
Track pending assertions with bounded subscriptions, deadlines, cancellation and
stale-observation/conflict outcomes. Reads need freshness and fairness even when
they are cheap. Arbitrary JavaScript is not a guaranteed read-only operation.

Queue bounds, FIFO scope, fairness between reads/writes, foreground contention,
and safe suspension points must be settled together with the lease lifecycle.
The spike currently holds its tab-control gate across condition waiting; a
MutationObserver exists, but separate scheduler execution permits are not proven.

## JavaScript, files and permissions

- JavaScript is an advanced action requiring both a valid lease and explicit
  Session permission. It remains disabled by default.
- JavaScript inside Flows is desired and exists through `action::evaluate`.
- Values, mutations, exceptions, frame targeting and bounded results belong to
  the same receipt and cancellation model; cancellation is not rollback.
- `action::evaluate_file` snapshots a local UTF-8 source file at construction,
  retaining exact source and provenance in the recipe.
- Explicit `action::run_module` actions capture bounded local import/export graphs
  and use native ES module execution. `.mjs` alone does not change script
  evaluation into a module. Isolated worlds remain unsupported.
- Managed Flow invocation opts in with `.allow_javascript()` while acquiring the
  same Session/Work authority. Borrowed invocation cannot elevate its Session.
- Result limits after transfer do not prevent transient browser/CDP allocations.

Andrew approved JS files and local modules for implementation on October 10.
The [JavaScript guide](./javascript.md) records APIs and supported boundaries;
CAS-573 carries current verification evidence.

## Watchers, Archive and Views

Watch currently provides bounded Session-wide operation receipts and retained
captures. Rich network/visual subscriptions, collector arming and capture hooks
(for example a screenshot after an action) remain next-pass ideas. Correlate
observations with operations; a shared time window does not prove causation.

Archive persists versioned records and evidence, supports fresh-process reopen,
and detects missing/tampered payloads. Offline replay checks saved evidence;
live rerun produces fresh effects and identities. Neither restores browser memory
or resumes a lease. Durable resumption after process loss is separate design work.

Views provide bounded projections and capture-bound cursors. Offline Visible is
unsupported without live layout. No AI discovery layer is implied. Release
assignment of Archive and Views remains open; earlier direction placed archive
work later, while the broad spike explored it already.

Richer Watch subscriptions, Archive/View release scope and durable execution were
deferred while starting lifecycle review. Scheduling brought some observation
contracts back into the current discussion; that is not blanket authorization
to implement every deferred capability.

## Real workflow and research retained

The concrete proposed integration is preparing a GitHub draft release in a
disposable repository: authenticated state, tag selection, title/notes, Save Draft,
then verification. Targets still need UI inspection; no release was created.
An uncertain save must be reconciled before retrying. A unique marker helps
inspection but does not provide server-side idempotency.

See [the structured lease model](lease-model.md) for the recipe and source map.
Research informed separate phase budgets, full-action deadlines and child
cancellation scopes; it does not determine universal defaults or prove Yosoi behavior.

## Partial implementation checkpoint

Andrew approved a small timeout/cancellation implementation, then explicitly
stopped completion to design acquisition, release, cleanup and scheduling
together before further coding. Preserve the partial edits; do not report them
as verified or discard them while reshaping the design.

Current partial edits include `timing.rs` helpers/task-local deadline, Flow and
action timeout metadata, optional external cancellation bindings, Flow execution
deadlines, and Session timeout/error changes. Existing Rust tests/Python callers
were mechanically updated for invocation spelling. No Python parity was verified.

A focused Cargo check was started. Its process handle was unavailable when
coding was paused; no successful final result is recorded. The partial code
still needs compilation, focused behavioral tests, API reconciliation and Archive
schema compatibility work. Existing recorded spike test results do not validate
these new edits. Do not resume runtime changes merely because this notebook exists.

The implementation inventory is a checkpoint, not a promise that its shape is
the final design. In particular, direct Work operations, policy maxima, explicit
release outcomes, scheduler permits and dropped-future cleanup must be reconciled.

## Cleanup project workstreams

1. Finalize one ownership/lifecycle contract: acquire, park, resume, release, close.
2. Implement timeout data/units, policy defaults/maxima and shared absolute deadlines.
3. Implement always-on scoped cancellation and optional external references.
4. Implement safe release/cleanup, combined errors and quarantine after uncertain work.
5. Shape scheduling permits, deferred assertions, identity checks, queues and fairness.
6. Shape bounded observation subscriptions needed by the chosen lifecycle.
7. Park JS-file/module ergonomics, Python parity and Archive/View release decisions
   as distinct follow-ups, preserving their acceptance questions.
8. Prove the integrated model with controlled failures and a researched real workflow,
   then prepare a decision memo and release gate.

Before creating duplicates, inspect the existing later-pass CAS-562 through CAS-567
and link or relocate matching work deliberately. New refinement work starts in
shaping; it should not inherit Final Boss from the first-pass evidence.

## Linear work map

The cleanup project contains the six reused later-pass issues, plus seven
focused refinement issues. Three milestones separate contract review, integrated
implementation/proof and deferred release decisions.

| Issue   | Scope                                                        | Planning state |
| ------- | ------------------------------------------------------------ | -------------- |
| CAS-563 | Session and lease lifecycle umbrella                         | Shaping        |
| CAS-568 | Millisecond timeouts and phase budgets                       | Shaping        |
| CAS-569 | Intrinsic cancellation and external references               | Shaping        |
| CAS-570 | Safe release, cleanup errors and quarantine                  | Shaping        |
| CAS-571 | Tab ownership, worker permits and parked scheduling          | Shaping        |
| CAS-572 | Deferred assertion identity and handoff safety               | Shaping        |
| CAS-564 | Flow/assertion ergonomics umbrella                           | Backlog        |
| CAS-565 | JavaScript limits/interruption umbrella                      | Backlog        |
| CAS-573 | JS file snapshots, modules and managed permission ergonomics | Backlog        |
| CAS-574 | Python optional-lease API and installed-wheel parity         | Backlog        |
| CAS-566 | Archive integrity/versioning/replay                          | Backlog        |
| CAS-567 | View identity, bounds and inspection                         | Backlog        |
| CAS-562 | Release scope, packaging and final evidence                  | Backlog        |

These are the creation-time states, not a permanent mirror of the board. Use
Linear for current execution state. CAS-568 through CAS-571 are children of the
lifecycle umbrella; CAS-572 and CAS-574 belong to Flow ergonomics; CAS-573 belongs
to JavaScript refinement. Their native Plain English callouts and acceptance
criteria preserve the specific user stories and open policy decisions.

## October 10 additions to the work map

The current project has 15 issues. CAS-575 adds the typed, composable Qscrape
checkout integration under CAS-564. CAS-576 adds strict IPv6 and explicit networking
controls in a dedicated milestone. Their per-item decisions, source map and proof
are in the [workspace plan](workspace-plan.md).

Qscrape is the concrete typed recipe integration: reuse child Flows and typed
inputs for pickaxe ×10 / 145.00 GS and chisel ×3 / 19.50 GS, keeping preparation
and simulated submission separate. The existing example is in the separate
`qscrape-flow-example` workspace and uses flattening/CSS/data attributes; it does
not prove native composition or the proposed typed binding API. Native child
paths, exact conversion, runtime authority and persisted schema must be shaped
together. Existing live evidence includes grid failures, which remain visible.

Networking is a separately shaped capability: strict family enforcement on
every relevant hop, source/interface choices, incompatible pool/process reuse,
and explicit proxy versus destination-egress guarantees. No silent IPv4 fallback
is allowed under a supported strict IPv6 policy. Browser/proxy enforcement needs
feasibility evidence before a supported guarantee is promised.

The default parking policy is now agreed: retain tab ownership and yield worker
capacity. Advanced yielding to other writers remains separately shaped.

## Research references

- [GitHub draft-release workflow](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)
- [Playwright timeout budgets](https://playwright.dev/docs/test-timeouts)
- [Playwright action readiness](https://playwright.dev/docs/actionability)
- [Tokio timeout and cooperative cancellation](https://docs.rs/tokio/latest/tokio/time/fn.timeout.html)
- [CancellationToken child scopes](https://docs.rs/tokio-util/latest/tokio_util/sync/struct.CancellationToken.html#method.child_token)
- [Chrome page lifecycle and background behavior](https://developer.chrome.com/docs/web-platform/page-lifecycle-api)

## Release evidence still required

Focused Rust model/cancellation tests; browser-backed contention and cleanup
controls; total/per-action deadlines; cancellation before/after dispatch; parked
workflows across several tabs; stale deferred assertions; fresh-process Archive
compatibility if touched; installed Python wheel workflows when Python is re-enabled;
current Stable Chrome baseline; supported package/platform checks; real examples;
documentation, version metadata, release notes and required CI.

Run one expensive build or validation at a time, with one worker by default.
Existing Docker evidence is controlled Rust proof, not a live-site, Python,
performance, production or release certification claim.

## Decision to review

Use this notebook as the continuing record. Record each new idea as agreed,
proposed or deferred; give implementation work a Linear issue and acceptance
criteria. Do not erase unresolved alternatives or merge planning with release approval.
