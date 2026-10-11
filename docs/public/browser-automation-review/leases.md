---
title: 'A Session stays alive. Work holds the tab.'
description: '0.2.0 concept review. Rust examples describe the local spike; Python examples are proposals.'
order: 2
---

# A Session stays alive. Work holds the tab.

A Session keeps resources and browser state alive. Holding a Session handle
alone does not give a caller permission to control a tab. Acquiring Work does.

## Reuse one tab

Using the browser policy from the previous page:

```rust
use yosoi::{action, flow, request, session};

let session = session::new()
    .bind(&browser_policy)
    .acquire()
    .await?;

let work = session.work().await?;

let run = async {
    let response = request::new(url)
        .with_work(&work)
        .send()
        .await?;

    // Application logic can inspect response before choosing more work.
    let steps = flow::new([action::click("#advance")]);
    let outcome = steps.with_lease(&work).invoke().await?;

    Ok::<_, Box<dyn std::error::Error>>((response, outcome))
}.await;

// Attempt both cleanup operations even when the task returned an error.
let release = work.release().await;
let close = session.close().await;
let (response, outcome) = run?;
release?;
close?;
```

`with_lease(&work)` configures this invocation to borrow the existing tab lease.
It does not execute steps, acquire another lease, or take ownership of cleanup.
`invoke()` runs on that lease's tab; you remain responsible for releasing Work
and closing its Session.

Both operations use the same tab and Session state. The borrowed Flow does not
close your Session. `steps.with_lease(&work).invoke()` runs on the current page; add an
`action::navigate(url)` step to change pages. Response Documents remain usable
after Session close.

This example attempts cleanup before propagating errors. It still prioritizes
the task error when multiple errors occur. A polished SDK must make combined
task and cleanup failures easy to retain.

## What a lease means today

- One caller holds control of a tab at a time.
- Another caller can await Work acquisition, within bounded capacity and time.
- Commands issued concurrently through the same held Work are rejected rather
  than added to another queue. Run the sequence explicitly.
- Releasing Work lets another caller acquire control. It does not close the Session.
- Closing the tab or Session revokes control.

A Work lease is a local control capability. It is not yet a remotely transferable
lease with renewals, expiry and cross-host recovery.

## Timeout scopes

Rust Flow and action timeouts are measured in milliseconds. An omitted action
timeout inherits the nearest Flow timeout, then the bound Policy's
`default_action_timeout_ms`; an unbound Flow borrowing Work inherits the owning
Session Policy's value. A bound Flow Policy selects the root fallback. The
`SessionPolicy.operation_timeout_ms` value remains the default for direct Work
calls outside a Flow action scope.

Each selected timeout starts when its action begins and covers the full action,
including target lookup, browser calls and required evidence capture. A nested
Flow with its own timeout replaces its parent's inherited value, even when that
timeout is longer. When the child returns, the next parent action resolves from
the parent's fallback again. Flow timeouts do not create a cumulative invocation
deadline or extend acquisition and cleanup budgets.

```rust
use yosoi::{action, flow, timing::seconds};

let child = flow::new([action::wait(350)]).timeout(seconds(30));
let steps = flow::new([
    child.into(),
    action::screenshot().timeout(seconds(5)),
])
.timeout(seconds(10));

let outcome = steps.with_lease(&work).invoke().await?;
```

Here the child wait can run for up to 30 seconds, although the parent Flow's
fallback is 10 seconds. After the child finishes, the screenshot uses its
explicit 5-second action timeout. `seconds(60)` converts to `60_000`, and a bare
`.timeout(3_000)` means three seconds. Nested child failure-capture settings are
currently rejected during Flow validation because their receipts do not yet
have a child-level capture field.

## Next review: lease lifecycle through user stories

We are focusing on lease lifecycle first. Tab assignment, richer Watch
subscriptions, JavaScript file helpers, Archive release scope and durable
execution are deferred decisions. They may connect to leases, but we do not
need to settle them all to define ownership and cancellation.

The stories below retain broader lease lifecycle questions for the next pass.
Their older Flow-timeout proposals are superseded by the implemented scopes
above. `SessionPolicy.operation_timeout_ms` remains the direct Work default;
Flow actions use their selected timeout without clipping it to Session or
Request elapsed defaults.

## Story 1: a short action inside a bounded Flow

“Most actions may take five seconds. This Flow must finish within three seconds.
Its click should give up after one second.”

```rust
let steps = flow::new([
    action::navigate(url),
    action::click("#advance").timeout(1_000),
])
.timeout(3_000);

let outcome = steps.bind(&policy).invoke().await?;
```

Policy supplies the root fallback, Flow timeouts override that fallback for
their descendants, and action timeouts override the nearest Flow. Each action
gets a fresh deadline, and a longer child can outlive its parent timeout.

## Story 2: another task already holds the tab

“Wait for control of this tab, but do not wait forever. If I cancel while queued,
leave the current owner alone.”

Lease acquisition needs its own wait budget. Waiting for ownership is different
from executing an action or keeping a Session alive.

Session and Work acquisition keep their own existing bounds. A Flow action
timeout begins only when that action starts; a Flow timeout does not cancel
acquisition or act as a total-run deadline.

Automatic tab assignment remains a later policy decision.

## Story 3: cancel after clicking Submit

“Stop this Flow, but do not accidentally submit twice or give another task a tab
that still has an unresolved command.”

Cancellation requests a stop. An action timeout stops its action and later Flow
steps; neither operation rewinds a dispatched click or page mutation.

Before dispatch, cancellation can prevent the action. After possible dispatch,
retain an Unknown outcome when confirmation is unavailable, stop later Flow
steps, and fence the tab until it is safe or closed. Do not automatically retry.

Cleanup keeps its separate bounded budget after an action deadline expires. It
must retain cleanup failures and must not report a resource as reusable just
because the caller stopped awaiting it.

Flow cancellation should affect that invocation. Session cancellation is broader:
it revokes the Session's work. Those should remain distinct controls.

## Story 4: release control but keep the browser state

“I finished my interaction. Let another caller use the tab while I keep the
Session and cookies alive.”

Successful release relinquishes Work, not the Session. A borrowed Flow never
owns that release; its caller does. An automatically owned Flow cleans up its
own resources. Watchers observe receipts without becoming control owners.

If dispatch is unresolved, dropping a handle must not make the tab immediately
available to the next caller. Local cleanup and safe reuse belong to this
lifecycle contract. Restarting a workflow after a process dies is a separate
durable-execution design; Archive evidence alone does not resume a lease.

## Decision to review

For a real workflow, structured recipe, Rust pseudotypes and implementation map,
read [Lease data model: a real release workflow](lease-model.md).

The timeout precedence is implemented as documented above. The remaining
lifecycle questions are acquisition waits, cancellation scope and release after
uncertain dispatch.

**Recommendation:** keep the action default, acquisition wait and cleanup
budget separate. Keep ownership explicit, and keep timeouts from silently
transferring unsafe control to another caller.
