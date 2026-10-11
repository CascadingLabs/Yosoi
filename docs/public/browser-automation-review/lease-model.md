---
title: 'Lease data model: a real release workflow'
description: 'Researched workflow, proposed timeout data and a source-grounded implementation plan.'
order: 3
---

# Lease data model: a real release workflow

This page is a design proposal. No timeout builders, new receipt fields or
runtime behavior have been implemented as part of writing it.

## A concrete use case: prepare a GitHub draft release

For Yosoi release work, a practical browser integration exercise is preparing
a draft release in a disposable repository using an already authenticated
Session. Open the release form, select an existing test tag, enter the title
and notes, save the draft, and verify it appears in the release list.

GitHub documents that workflow, including saving a draft separately from
publishing. This example ends at a draft and does not attach release artifacts.
See [GitHub's release management documentation](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository).

This is a proposed application to your release workflow, not a GitHub integration
that was exercised live. UI targets need inspection before a runnable example:
the target names below are placeholders, not verified selectors.

It exercises real lifecycle problems:

- The authenticated Session survives between tasks.
- A task waits while another task holds the same tab.
- Navigation needs more time than a field entry or click.
- Saving a draft may succeed remotely even when confirmation times out.
- A borrowed lease stays under caller ownership after the Flow finishes.

Before retrying an uncertain save, inspect whether that exact draft already
exists. Use a test tag and a unique title/run marker as reconciliation evidence;
the marker alone does not guarantee server-side deduplication.

## The structured recipe

The agreed timeout input is an integer count of **milliseconds**. Unit helpers
only translate into that integer: `seconds(60)` yields `60_000`, while
`milliseconds(60)` yields `60`. The timeout runner receives the same unit
either way. Conversion must check overflow and duration validation still applies.

```rust
// Proposed timeout input convention.
action::click(target).timeout(60);             // 60 milliseconds.
action::click(target).timeout(100 * 60);       // 6,000 milliseconds = 6 s.
action::navigate(url).timeout(seconds(60));   // 60,000 milliseconds = 60 s.
```

These lifecycle pseudotypes are an earlier proposal. Current timeout behavior
uses millisecond action and Flow inputs, `Policy.default_action_timeout_ms` as
the root fallback, nearest-scope inheritance for nested Flows, and explicit
per-action overrides. See [Timeout scopes](leases.md#timeout-scopes) for the
implemented Rust behavior and persistence compatibility.

```json
{
  "policy": {
    "default_action_timeout_ms": 5000,
    "lease_acquire_timeout_ms": 2000,
    "cleanup_timeout_ms": 5000
  },
  "flow": {
    "timeout_ms": 30000,
    "steps": [
      {
        "operation": { "kind": "navigate", "url": "<test-repo release form>" },
        "timeout_ms": 20000
      },
      {
        "operation": { "kind": "click", "selector": "<existing test tag>" },
        "timeout_ms": 1000
      },
      {
        "operation": {
          "kind": "enter_text",
          "selector": "<release title field>",
          "text": "Yosoi lifecycle review — unique run marker"
        }
      },
      {
        "operation": {
          "kind": "enter_text",
          "selector": "<release notes field>",
          "text": "Draft created by the lease integration exercise."
        }
      },
      {
        "operation": { "kind": "click", "selector": "<save draft button>" },
        "timeout_ms": 1000
      },
      {
        "operation": {
          "kind": "wait_until",
          "condition": { "kind": "exists", "selector": "<matching saved draft>" },
          "timeout_ms": 5000
        }
      }
    ]
  }
}
```

An omitted step timeout inherits the nearest Flow timeout, then the root Policy
default. An explicit action timeout has highest precedence and may exceed any
ancestor's configured value. The condition wait also stays within its action
deadline; its own limit cannot extend the surrounding action.

## Rust-shaped data

Separate persisted configuration from runtime ownership. These are pseudotypes,
not final public names. Keep validated positive durations behind constructors
that return typed errors for zero, excessive values or deadline overflow.

```rust
// Serializable configuration.
struct TimingPolicy {
    default_action: PositiveMillis,
    lease_acquire: PositiveMillis,
    cleanup: PositiveMillis,
}

struct ActionSpec {
    operation: Step,             // Existing Navigate / Click / Evaluate / ...
    timeout: Option<PositiveMillis>,
}

struct Flow {
    steps: Vec<ActionSpec>,
    timeout: Option<PositiveMillis>,
    capture_on_failure: FailureCapturePolicy,
}

// Runtime-only state: never serialized into the recipe.
struct InvocationContext {
    cancel: CancellationToken,
    inherited_action_timeout: PositiveMillis,
}

struct ActionContext {
    deadline: tokio::time::Instant,
    cancel: CancellationToken,
    dispatch: DispatchState,
}
```

The Flow contains a recipe. A borrowed Work lease, CancellationToken and
monotonic Instant belong to an invocation, not the saved recipe.

## What the SDK could look like

This is proposed syntax. `targets` contains previously inspected UI targets,
and `policy` contains the timing settings above. Authentication is established
before this example; it does not assume a saved Session restores authentication.

```rust
let steps = flow::new([
    action::navigate(release_form_url).timeout(20_000),
    action::click(targets.existing_tag).timeout(1_000),
    action::enter_text(targets.title, title),
    action::enter_text(targets.notes, notes),
    action::click(targets.save_draft).timeout(1_000),
    action::wait_until(targets.saved_draft_condition, 5_000),
])
.timeout(30_000);

let result = steps
    .bind(&policy)
    .with_lease(&lease)
    .with_cancellation(&cancel)
    .invoke()
    .await;
```

The caller acquired `lease` before invoking this Flow. Its acquisition wait has
its own budget; the 30-second Flow setting supplies a per-action fallback and
does not bound the whole Flow. The borrowed lease is not released automatically.

For automatic ownership, omit `with_lease`. Then the thirty-second Flow budget
remains a per-action fallback, and acquisition retains its separate bound.
Release/close happen afterward under the cleanup budget.

## One clock per action, shared by every internal call

```text
inherited = flow.timeout or parent.inherited or policy.default_action
for step in flow.steps:
    if step is a nested Flow:
        execute child with child.timeout or inherited
        restore parent's inherited timeout for the next sibling
    else:
        duration = step.timeout or inherited
        action_deadline = checked_deadline(now, duration)
    execute action using action_deadline throughout:
        permission and target checks
        foreground wait
        browser dispatch and completion
        required result capture

    record receipt; stop on rejection or uncertainty

settle or fence outstanding work
release only resources owned by this invocation
bound cleanup using a fresh cleanup deadline
return work outcome together with cleanup outcome
```

If an action has one second, target lookup, the click and its required capture
share that second. They do not each get another second. Root failure capture
uses a separate bounded allowance; child Flow failure capture is rejected until
its provenance can be retained explicitly.

## Separate why execution stopped from what happened

```rust
struct InvocationOutcome {
    work: FlowOutcome,
    stop_reason: Option<StopReason>,
    cleanup: CleanupOutcome,
    resource: ResourceDisposition,
}

enum StopReason {
    AcquisitionTimeout,
    ActionTimeout { step_index: u64 },
    FlowTimeout,
    CallerCancelled,
    SessionClosed,
}

enum DispatchState { NotDispatched, PossiblyDispatched, ProviderReturned }
enum CleanupOutcome { NotOwned, Complete, TimedOut, Failed }
enum ResourceDisposition { HeldReady, HeldFenced, Released, Closed, Quarantined }
```

Keep the operation's existing Observed / Rejected / Unknown evidence status.
For example, “caller cancelled” and “Save Draft may have succeeded” can both
be true. A provider returning is not proof of a business effect. A known completed
effect followed by a timed-out verification remains a recorded known effect with
an unconfirmed business result.

For a borrowed invocation, normal completion leaves HeldReady; uncertainty
leaves HeldFenced when safe reuse cannot be established. The caller decides
when to release or close. An owned invocation closes resources; failed shutdown
must preserve quarantine rather than admitting a replacement on an unsafe slot.

## What changes in the existing code

| Existing area                              | Current behavior                                                                                                                               | Required change                                                                                                                                                                       |
| ------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `crates/yosoi/src/action.rs` and `flow.rs` | Constructors return the Step enum; Flow has no timing field.                                                                                   | Add action timing metadata and Flow total duration; constructors and validators must update together.                                                                                 |
| `crates/yosoi/src/session.rs`              | One operation timeout, default 10 seconds, also constrains control acquisition. `Work::call` restarts it for each provider call.               | Separate timing defaults and phase budgets; carry one absolute action deadline through lookup, dispatch and capture. Direct Work operations need the same scope.                      |
| `crates/yosoi/src/flow/execution.rs`       | Executes sequential steps with a cancellation scope, but no total Flow clock.                                                                  | Resolve one invocation context before acquisition; propagate deadlines and cancellation through every stage; retain partial outcomes and separate cleanup results.                    |
| `crates/yosoi-engine/src/session.rs`       | Process admission has a ten-second wait; cleanup is configured at five seconds; control receives Session cancellation and a relative duration. | Thread the invocation deadline and waiter cancellation into admission and control acquisition. Use a shared acquisition deadline and independent cleanup budget.                      |
| `crates/yosoi-web-capture/.../control.rs`  | Already supports cancellation and an absolute deadline in `control_before`.                                                                    | Reuse that gate. Supply caller cancellation, preserve queue bounds, and retain post-wait authority checks.                                                                            |
| Request integration and receipts           | Browser Requests borrow the same control; outcomes retain uncertainty.                                                                         | Keep Request-specific semantics while applying shared control safety. Record timeout cause and dispatch progress without claiming an effect from transport completion alone.          |
| Archive decoding                           | Stores Flow definitions and outcomes under validated schemas.                                                                                  | Decide schema compatibility before changing persisted Step/Flow shapes. Verify immutable payload integrity before interpreting old/new records; do not rewrite stored bytes in place. |

`Work::release()` currently drops its held control. Existing drop fencing protects
uncertain dispatch, but an explicit settlement result is still needed to explain
whether a tab was released safely or stayed unusable. Rust Drop cannot await
cleanup; retain an owner-driven cleanup path for cancelled/dropped invocations.

The current code is conservative about pre-dispatch provider calls: cancelling
target inspection may fence the tab too. Track possible effect dispatch separately
so the public receipt can distinguish a prevented click from an uncertain click,
without weakening the control fence.

## What the research changes

[Playwright's timeout model](https://playwright.dev/docs/test-timeouts) separates
overall test time, action/navigation limits, assertion waits and teardown time.
That supports separating our budgets; it does not determine Yosoi's defaults.

[Playwright's actionability checks](https://playwright.dev/docs/actionability)
show why a click may include target-readiness work before dispatch. Our deadline
should cover its entire operation. Matching Playwright's full actionability
behavior is a separate capability decision.

[Tokio timeout](https://docs.rs/tokio/latest/tokio/time/fn.timeout.html) bounds
cooperative future execution; dropping a future does not establish what an
external browser or remote server did. Non-yielding work can also exceed a
deadline. Avoid a single outer timeout that loses receipts and skips async cleanup.

[CancellationToken child scopes](https://docs.rs/tokio-util/latest/tokio_util/sync/struct.CancellationToken.html#method.child_token)
let a Session cancellation stop descendants without making an individual
invocation cancellation cancel the Session. Keep those ownership scopes explicit.

## Proof required before calling this implemented

Use controlled fixtures first to force deadline boundaries, then run the draft
workflow against a test repository with inspected selectors and authorized
authentication. The evidence must establish:

- Multiple internal calls consume one action budget.
- All steps consume one total Flow budget.
- Cancelling a queued waiter leaves the current holder usable.
- Cancelling after possible dispatch retains uncertainty and prevents unsafe reuse.
- A borrowed Flow does not release the caller's lease.
- Cleanup remains bounded, preserves errors and quarantines uncertain resources.
- Older archived records remain readable under the chosen compatibility contract.

## Decision to review

Does this structured model express the four agreed lifecycle stories? The next
decision is whether acquisition and cleanup budgets live only in Session policy,
or also allow per-invocation overrides within policy maxima. Tab assignment and
durable resumption remain deferred.
