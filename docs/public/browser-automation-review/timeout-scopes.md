---
title: 'Timeouts: nearest scope wins'
description: 'The approved millisecond timeout inheritance contract for CAS-568.'
order: 2
---

# Timeouts: nearest scope wins

This is the October 10 implementation contract for CAS-568. It supersedes the
earlier microsecond proposal and the earlier minimum-of-parent total deadlines.
The timeout implementation is integrated in the review checkout. Native child
Flows use `child.into()`; integer timeout inputs are milliseconds.

## Defaults require no annotations

Policy provides the outermost fallback. Every Flow/action can omit timeout and
inherit the closest parent scope. Only explicit local settings override it.

```text
policy default
    parent Flow override, if present
        nested Flow override, if present
            action override, if present
```

The closest explicit value wins. Do not take a minimum of these defaults.

## Milliseconds, with conversion helpers

```rust
action::click(button).timeout(500); // 500 milliseconds
action::navigate(url).timeout(seconds(20)); // 20,000 milliseconds
```

Helpers only translate to the integer millisecond input. Omitted values inherit;
zero and invalid/overflowing durations produce typed errors rather than panics.

## A child can override a shorter parent

```rust
let child = flow::new([
    action::navigate(url),             // 30 seconds inherited from child
    action::click(button).timeout(500), // action overrides to 500 ms
]).timeout(seconds(30));

let parent = flow::new([
    child.into(),
    action::screenshot(),              // parent scope restored: 10 seconds
]).timeout(seconds(10));

parent.bind(&policy).invoke().await?;
```

Andrew explicitly confirmed that the thirty-second child can run longer than
the ten-second parent setting. A Flow timeout is an inherited execution default,
not a cumulative outer stopwatch that cancels its explicitly overridden child.
If a separately named whole-run deadline is needed later, shape it separately.

Child settings never leak into a parent's next sibling or another concurrent
invocation. Native nested scope execution is required; flattening a recipe alone
does not prove this contract.

## An action still has one clock

Once resolved, one action deadline covers target checks, foreground waiting,
dispatch, browser completion and required capture. Internal calls do not each
receive a fresh copy of that duration. Parking an already-started action does
not reset its deadline.

Acquisition waits, cleanup and actual resource authority are separate lifecycle
constraints. Timeout inheritance does not disable cancellation, Session close,
uncertain-dispatch fencing or safe resource handoff. Existing unrelated Direct
HTTP transaction limits keep their own contract.

## Acceptance

Policy fallback, parent/child/action overrides, a longer child, sibling restoration,
concurrent isolation, one action budget, invalid durations and compatible old/new
record decoding must have focused evidence. Do not reinterpret stored `_us`
prototype integers as milliseconds.

Focused executor, Flow-model and record checks pass in the integrated checkout.
Controlled browser evidence is recorded separately in CAS-568. This is local
implementation evidence; no push, landing or release is authorized by this task.

Policy defaults to 10,000 ms through `default_action_timeout_ms`. A Flow bound
to a Policy uses that fallback. A Flow borrowing Work without binding a Policy
uses the owning Session's Policy fallback. Nested child failure capture is
currently rejected with a typed error; root failure capture remains supported.

## Decision to review

The scope precedence and integer units are agreed. Any new total-run deadline,
typed Qscrape authoring feature or broader scheduler behavior needs its own scope.
