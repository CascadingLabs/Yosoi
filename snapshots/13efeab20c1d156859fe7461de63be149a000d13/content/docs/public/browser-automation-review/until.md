---
title: 'Wait for browser evidence with Until'
description: 'Run one trigger, then wait for bounded DOM, accessibility or response evidence.'
order: 4
---

# Wait for browser evidence with Until

An Until step runs an optional trigger once, then waits for browser evidence to
confirm an expectation. The observation watch starts before trigger dispatch,
so a fast response is still available to the check. Until does not retry the
trigger.

## Check several sources

This Rust example clicks once and waits for a visible confirmation, an exact
response, and an accessible status name:

```rust
use yosoi::{action, expect, flow};

let checkout = flow::new([
    action::click("#place-order").until(expect::all([
        expect::visible("#confirmation"),
        expect::response("https://shop.example/api/orders")
            .method("POST")
            .status(201)
            .json("/state", "accepted")
            .into(),
        expect::ax("Order placed").role("status").into(),
    ])),
])
.timeout(10_000);

let outcome = checkout.with_lease(&work).invoke().await?;
```

`expect::visible` and the existing typed `Condition` values check the current
DOM. `expect::ax` matches an exact accessible name and can also require a role.
It checks the returned accessibility node; it is not a full accessibility audit.
An AX-only wait also listens for DOM mutation notifications as wakeup hints,
because AX update events do not report every new node. Those hints do not cause
HTML capture: a fresh AX query decides whether the name and role match. Raw DOM
is retained only when the expectation includes a DOM `Condition` or Contract.
`expect::response` matches the full URL, with optional method, status, and JSON
Pointer value checks. The full URL includes its query string when one is
present.

The `All` group confirms every clause before the Until step succeeds. Each
source keeps its own evidence: a response may be retained from earlier in the
wait, while DOM and accessibility checks use fresh confirmation evidence.
Those sources do not share one atomic timestamp. Browser condition results and
the accompanying HTML snapshot are also separate reads; the snapshot can
precede the successful condition. Use a Contract group when all comparisons
must use one captured record. Network evidence identifies a specific browser
request with its request ID, top-level flag, frame ID, and loader ID. The report
scope stores the original document's epoch, frame, and loader. The report also
retains the one trigger receipt and its dispatch-start
watermark in Unix microseconds. Response candidates must start at or after that
watermark and match the original top-level frame and loader. This identifies an
observed browser request attempt; it does not prove that the click caused the
request. If several business requests share the same filters, include an
application identifier in the response JSON checks.

DOM, Contract, and accessibility evidence includes its document epoch and
observation time in Unix milliseconds. Contract evidence wraps the assertion
report with the observation ID and epoch. Network evidence carries the browser
request's start time plus the confirmation time and scope. These are separate
observations, not one atomic cross-source timestamp.

## Wait without a trigger

Use an expectation's `.until()` when the relevant change may come from another
actor or is already in progress:

```rust
let ready = expect::visible("#ready").until().timeout(5_000);
let outcome = flow::new([ready]).with_lease(&work).invoke().await?;
```

Use the assertion builder when an existing typed `Condition` is clearer:

```rust
let ready = action::assert(Condition::Visible {
    selector: "#ready".into(),
})
.until();
```

A local Contract assertion can also wait for its Rust checks:

```rust
let confirmed = action::assert_all::<Order>(
    Order::plan()?,
    [
        check(|order: &Order| order.state == "accepted"),
        check(|order: &Order| order.lines.len() == 2),
    ],
)
.until();
```

These checks use ordinary Rust comparisons. The assertion is evaluated again
against fresh evidence while the step waits. An immediate assertion remains
available by converting the builder into a Step with `.into()`.

## Budget and control

An explicit timeout is optional. Without one, the Until step inherits the same
Flow, bound Policy, or Session action timeout as other steps. Timeouts use
integer milliseconds; `timing::seconds(10)` converts an existing seconds-based
value to milliseconds. A trigger's timeout and continuation settings apply to
the complete trigger-and-wait step. Explicit settings on a local Contract
assertion take precedence, and Step modifiers can also be applied after
`.until()`.

The trigger must be a Click, EnterText, Evaluate, EvaluateFile, or EvaluateModule
step. A Navigate step is rejected during Flow validation, before Session
acquisition or dispatch. Until remains bound to its starting Session, tab, and
document epoch. If the page changes navigation during the wait, the original
scope cannot be confirmed; the outcome is unknown and the tab is fenced from
reuse until cleanup establishes safe settlement.

Native triggers retain the resolved element and verify the original document
around selection and focus. JavaScript triggers stay in the original execution
context; they do not select a replacement context after navigation. In headful
mode, native input can bring the leased tab forward when it is hidden. A typing
target replaced during focus is rejected before text is sent, so the existing
failure policy can decide whether the Flow continues.

The current Work lease remains assigned to the tab during the wait. With the
default `yield_on_wait` setting, the implementation releases its worker slot
while parked and reacquires it to inspect new evidence; another task can use
capacity without taking this tab. Setting `yield_on_wait` to false retains the
worker slot while parked. Neither mode releases the Work lease or closes the
caller's Session.

Cancellation before trigger dispatch can prevent the trigger. A token already
cancelled before observation is armed, or a deadline while waiting for Work or
queue admission, uses the ordinary Flow not-dispatched result and has no Until
report. Once armed, the trigger runs at most once and its receipt remains in the
report; cancellation retains that report through cleanup. Cancellation does not
roll back the trigger or abort a backend job or network request that the page
started.

While the runner is parked with no browser command outstanding, an acknowledged
observer settlement can keep the Work lease healthy if the original page scope
still matches. Settlement gets a separate bounded one-second cleanup allowance.
If the invocation future is dropped before settlement, or navigation changes
the original scope, the tab is fenced by default. A fenced tab is not read again
to infer that it is safe to reuse. If cleanup cannot establish safe settlement,
the report is unavailable and the receipt is unknown. Until does not
automatically retry a possibly dispatched trigger.

## Bounds and saved recipes

An expectation tree can contain at most 128 nodes and eight levels, including
the root expectation and its leaves.
Response expectations allow at most 32 JSON matches. Selectors and expectation
names are bounded to 4 KiB, response URLs to 8 KiB, JSON Pointers to 4 KiB, and
each expected JSON value to 16 KiB. Flow validation also enforces the existing
serialized Flow limit, 128 step-and-wrapper nodes, and nested Flow depth of
eight. A trigger counts as a step node alongside its Until step.

One Until report is limited to 1 MiB encoded, including all retained DOM, AX,
network, Contract, and trigger evidence. The per-wait observer queue and
retained response evidence use the Session's configured event-count and byte
bounds; they are not a ledger of every network event for the life of the tab.
The report consumes the enclosing AutomationRecord's 8 MiB evidence budget.

Until Flows use schema version 4. Flows without Until keep the existing schema
version. Schemas 1 through 3 cannot represent Until steps. A saved local Rust
Contract assertion retains its descriptor and check names, but never its
closure code; rebind those Rust checks before invoking the saved Flow. Python
models can inspect that descriptor but do not transport Rust predicates.

The Python models expose the same declarative wire shapes for condition,
response, accessibility, and All expectations:

```python
from yosoi import browser as ys

checkout = ys.Flow(steps=(
    ys.click("#place-order").until(ys.all_of((
        ys.visible("#confirmation"),
        ys.response(
            "https://shop.example/api/orders",
            method="POST",
            status=201,
            json_matches=(ys.JsonMatch(pointer="/state", value="accepted"),),
        ),
        ys.ax("Order placed", role="status"),
    ))),
))
```

`OperationReceipt.until_report()` returns a validated typed view of the Until
result. It includes the scope, each check's source and evidence, and the one
trigger receipt when there was a trigger.

## Run the Python native browser proof

The opt-in Python fixture at `python/tests/test_until_browser.py` serves a
local checkout page and two ordered responses with distinct order IDs. It
requires the response URL, method, status, and `/order_id` JSON Pointer to
match the expected order, then checks the visible confirmation and accessible
status. It also cancels a second response wait after the local server has
accepted the request, checks that the Until report retains the trigger outcome,
and lets the server finish its response to show that cancellation did not undo
accepted backend work. The Python bridge does not expose a scheduler-parked
barrier, so cancellation may race with the active browser command: either a
cancelled outcome or an unknown outcome is safe. Either retains the trigger's
known or uncertain execution status. The proof never accepts a satisfied result for
this cancelled wait. Rust headful coverage separately verifies cleanup after a
parked cancellation.

Run it from the repository root after the Python extension has been built for
CPython 3.14 and placed in `python/yosoi`. The runner uses the existing pinned
Chrome Stable image and existing synced UV environment; it does not use the
host's browser:

```sh
spikes/browser-automation/run-python-until.sh "$PWD/target/python-until"
```

The runner mounts the existing UV executable, Python source (including the
built extension), `pyproject.toml`, `uv.lock`, the synced UV environment, and
its CPython base prefix. Those mounts are read-only; the existing shared UV
cache and output directory are writable. It writes the pytest log to
`python-until.log` under that output directory. Set `YOSOI_PYTHON_UV_ENV` to
select a different existing synced environment. The fixture is opt-in and its
native browser run passed in the pinned image using the isolated development
extension. It saved the confirmed order outcome and the cancellation outcome;
the final active-command cancellation returned an unknown confirmation and an
unknown trigger receipt. Python does not currently expose Archive reopen,
so this fixture checks the native Flow result and retained Until receipt. Rust
live examples cover the separate Archive write/reopen boundary.

## Current limitations

The deeper review found two limitations that remain open after local
integration:

- A stylesheet-only visibility change, such as `CSSStyleSheet.insertRule`, can
  leave an Until check asleep even when the element becomes visible before its
  deadline. A DOM style-attribute mutation wakes the same check. Computed
  visibility wake coverage is tracked in CAS-583.
- Unrelated network requests can overflow the default response-watch capacity.
  In the recorded 64-request burst, capacity 16 returned unavailable/unknown
  and fenced the tab; capacity 128 completed the same workload. Robust bounded
  handling of unrelated traffic is tracked in CAS-584.

The live dynamic-loading navigation failure is separate: independent HTTP
captures received Heroku application-error HTTP 503 responses after about
30 seconds. Until had not started. The site's internal cause remains unknown;
the client navigation deadline and worker-yielding follow-up is CAS-585.

The SDK is integrated locally with these limitations documented. This does
not resolve those follow-ups or establish a completed release. The full
diagnosis and measurements are retained in
`spikes/browser-automation/until-investigation.md`.

## Verification checkpoint

These are local checks against regular sandboxed Chrome. They do not imply
hosted CI, release packaging, publication, or full browser-baseline
certification. Runtime proofs use source
`57f23beed4d4842fa1d21dc3833ab70f52d75316`. The provider scope fixtures use
`c113dbe0d30fe37841e675d751657a805bd6f786`; production source is identical
between these two revisions. Final documentation and preview provenance are
recorded separately in the review handoff.

| Check                                       | Result                                                | Evidence                                                               |
| ------------------------------------------- | ----------------------------------------------------- | ---------------------------------------------------------------------- |
| Selected Rust Until models/executor/archive | 79 passed (32 library, 47 integration)                | Shared `until-final-rust-checks.log`                                   |
| Observation provider unit tests             | 5 passed                                              | Shared `until-final-provider-units.log`                                |
| Python declarative models                   | 19 passed                                             | Shared `until-final-python-models.log`                                 |
| Known Rust callers                          | 8 examples and 3 affected browser harnesses compiled  | Shared `until-final-callers-check.log`                                 |
| Provider scope fixtures                     | 3 passed in each mode                                 | `target/until-bound-provider-{headless,headful}/run.log`               |
| Full browser fixtures                       | 16 headless and 16 headful passed                     | `target/until-final-fixtures-{headless,headful}/run.log`               |
| Headful four-tab, one-worker stress         | 20 rounds / 80 invocations passed                     | `target/until-final-stress-headful/run.log`                            |
| Parked cancellation and tab reuse           | Passed headful                                        | `target/until-final-cleanup-headful/run.log`                           |
| Python native browser fixture               | 1 passed in 4.76 s                                    | `target/until-final-python-native/python-until.log` and saved outcomes |
| Live exact-response recipe                  | httpbin passed in each mode                           | `target/until-final-live-{headless,headful}/live-until.json`           |
| Live dynamic-loading recipe                 | Navigation returned unknown before Until in each mode | The same live summaries, failure outcomes, and screenshots             |
| Fresh Archive handle readback               | All 4 live outcomes matched their saved records       | `archive_read_verified: true` in the live summaries                    |

The headless fixture cases cover fresh evidence, immediate responses, old
same-URL requests, source changes, Contract failures, deadlines, cancellation,
and tab fencing. Earlier failed runs remain available. They exposed native
scroll/focus behavior, known target-loss classification, cold-run budgets, and
harness assumptions about evidence order and separate HTML/condition reads.
The final counts come from complete runs after those corrections.

The live response matches an exact URL and expected query-field value. The
dynamic-loading recipe is intended to confirm the visible “Hello World!”
heading through DOM, AX, and a typed Contract; its final runs stopped during
navigation and never reached those checks. An older headless run passed both
recipes, but it does not replace this current limitation. No uncertain action
was retried to manufacture success. Both successful and failed outcomes were
saved and verified through a fresh Archive handle; worker counts returned to
zero after Session closure.
