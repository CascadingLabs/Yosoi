---
title: 'Continue or stop: scoped failure and cancellation'
description: 'Independent continuation overrides for Policies, Flows, actions and assertions.'
order: 3
---

# Continue or stop

Failure and cancellation each have a continuation policy. Both default to
`Continue`. Omit a local setting to inherit; explicitly select `Continue` to
replace an inherited stop setting.

```text
Policy fallback
    parent Flow override
        child Flow override
            action or assertion override
```

The closest explicit setting wins, independently for each event. A child's
settings do not leak into a parent's next sibling or another invocation.

## Stop globally; tolerate one optional check

```rust
use yosoi::{action, flow, policy::Policy};
use yosoi::flow::{Continuation::{Continue, Stop}, StopScope::Invocation};

let mut policy = Policy::default();
policy.flow.on_failure = Stop(Invocation);

let checkout = flow::new([
    action::click("#login"), // Required: inherits Stop(Invocation).
    action::assert(flow::Condition::Exists {
        selector: "#optional-estimate".into(),
    })
    .on_failure(Continue)
    .into(),
    action::click("#save-draft"),
]);
```

An optional estimate failure remains in the outcome. It does not stop saving the
draft when the tab remains safe. The parent does not reapply its global stop
policy to the same already-handled failure.

## Stop a child Flow; keep its parent running

```rust
use yosoi::flow::StopScope::CurrentFlow;

let estimate = flow::new([
    action::click("#calculate-estimate"),
    action::assert(flow::Condition::Exists {
        selector: "#estimate-ready".into(),
    })
    .into(),
    action::screenshot(),
]).on_failure(Stop(CurrentFlow));

let checkout = flow::new([
    estimate.into(),
    action::click("#save-draft"),
]).on_failure(Continue);
```

For an action, `CurrentFlow` is its nearest containing Flow. A failure in the
estimate skips its remaining screenshot; the parent can still save the draft.
`Stop(Invocation)` instead skips all remaining work in the invocation.

## Failure and cancellation are separate

```rust
let optional_lookup = action::evaluate("document.title")
    .on_failure(Stop(Invocation))
    .on_cancellation(Continue);
```

The continuation setting handles a local step's result. Cancelling the root
invocation or Session still stops its descendants; a local `Continue` cannot
revive cancelled ownership. Stopping execution does not cancel an ancestor's
cancellation reference or stop unrelated invocations.

An explicit local Stop reference is optional:

```rust
use yosoi::request::CancellationToken;

let lookup_stop = CancellationToken::new();
let optional_lookup = action::wait(10_000)
    .with_cancellation(&lookup_stop)
    .on_cancellation(Continue);

let recipe = flow::new([optional_lookup, action::screenshot()]);
// Application code can call lookup_stop.cancel() while recipe is executing.
// The invocation and Session cancellation references remain independent.
```

A nested Flow converted to a Step can bind a local reference the same way.
Cancelling that child stops its whole subtree, even under Continue; the parent
can continue with its next sibling. A local action cancellation affects only
that action. The outcome identifies a cancelled child with `cancelled_flow`.
Runtime cancellation authority is not serialized. Saved descriptors identify a
required binding; before executing a reopened recipe, explicitly reattach it
with `Step::rebind_cancellation`. Reading saved results does not require rebinding.

## Results survive continuation

Execution finishing does not mean every step succeeded. Retain the failed or
cancelled receipts, independent operation effects, skipped paths and reasons,
stop reason and owner cleanup evidence. A continued failure cannot become an
all-success result. Opening saved results does not rerun actions or predicates.
Durable Archive recording is a separate choice.
The outcome snapshots `continuation_defaults` so saved skip/stop reasons can be
checked against the actual bound Policy or Session fallback and local overrides.

Unknown dispatch is a safety boundary: an uncertain operation may already have
affected the page, so retain the fence and stop unsafe scheduling. `Continue`
does not bypass settlement, claim rollback or retry the action.

## Final Boss review

CAS-569 owns this approved implementation. Review the global-stop/local-continue
example, the child-only stop example and cancellation ownership boundaries.
Verification distinguishes deterministic scope tests, controlled browser tests,
Python model compatibility and installed-artifact or release certification.
