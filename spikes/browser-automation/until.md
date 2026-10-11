# Until implementation and review

CAS-572 implements scoped `.until` on the default browser-actions integration
`b774e260cb099e5b31246dd7d63c8182f78c257b`. Work lives in the isolated WTF/JJ
workspace `yosoi-browser-until--Yosoi`; the default workspace is preserved.
The public examples and contract are in
[`docs/public/browser-automation-review/until.md`](../../docs/public/browser-automation-review/until.md).

## What Andrew can review

```rust
let submitted = action::click("#submit").until(expect::all([
    expect::visible("#confirmation"),
    expect::response("https://shop.example/api/orders")
        .method("POST")
        .status(201)
        .json("/attempt", attempt_id)
        .into(),
    expect::ax("Order placed").role("status").into(),
]));

let confirmed = action::assert_all::<Order>(
    Order::plan()?,
    [check(|order: &Order| order.state == "accepted")],
)
.until();

let outcome = flow::new([submitted, confirmed])
    .with_lease(&work)
    .invoke()
    .await?;
```

The trigger dispatches once. The standalone assertion checks fresh typed
records repeatedly. Both use the inherited timeout unless overridden; integers
are milliseconds and `timing::seconds(n)` is a conversion helper. Existing
continuation and cancellation policies apply to the whole Until step. A parked
wait yields worker capacity while retaining exclusive ownership of its tab.

Response matching requires the original top-level frame/loader and a request
start at or after trigger dispatch. An application attempt ID distinguishes
business requests with identical transport filters. Subscribing before a click
does not establish causality. DOM and AX use fresh state; a completed response
is historical evidence from the matched request. All sources are independently
observed, rather than an atomic cross-source snapshot.

Cancellation is not rollback. A safely parked wait can settle its observer and
reuse the lease. A dropped invocation, navigation replacement, lost source, or
unsafe settlement fences the tab and retains an unknown outcome. Cleanup has
its own bounded allowance and does not rerun the trigger.

## Code map

| Area | Implementation |
| --- | --- |
| Authoring | `action/builder.rs`, `expect.rs`, and `flow/model.rs`: typed assertions, expectation builders, one Until step |
| Validation | `flow/validation.rs`: bounded trees, supported one-shot triggers, predicate rebinding and schema checks before effects |
| Scheduling | `session/until/browser.rs`: existing execution pool, watch arming, one trigger, fresh reads, event-driven parking, acknowledged settlement |
| Sources | `voidcrawl/page/observation_watch.rs`: bounded CDP queues, original frame/loader/epoch, request-event joins, request-start timestamps, body capture, DOM/AX wakeup hints and acknowledged cleanup |
| Browser adapter | `yosoi-web-capture/.../control.rs`: scoped native input and JS evaluation, bounded response capture, and fresh AX snapshot filtered by browser-computed name and role |
| Saved evidence | `session/until.rs`, `automation_record.rs`: bounded structured report, scope/timestamps/source proof, canonical receipt references |
| Python | `python/yosoi/browser.py`: same declarative schema and native Session execution; Rust predicates remain local |

This adds no second scheduler and no custom frontend. Legacy `wait_until`
remains available. Durable watchers, multiwriter tabs, navigation-spanning
confirmation, and portable Rust closures are outside this change.

## Compatibility boundaries

- Flows containing Until use schema 4; other Flows retain schema 3. Older
  schemas reject Until. Existing non-Until archived outcomes remain supported.
- `action::assert` and `action::assert_all` now return an assertion builder.
  Immediate assertions in a Step collection use `.into()` or `Step::from(...)`.
  Repository callers and public examples are updated atomically.
- Saved Contract checks retain descriptors and receipts, not executable Rust
  closures. Rebind them before replay. Python can inspect those descriptors.
- An Until report is bounded to 1 MiB and consumes the existing 8 MiB aggregate
  AutomationRecord evidence budget. Overflow cannot become a successful proof.

## Recorded verification

All results here are local. Hosted CI, publication, browser promotion, and
release-wheel proof are separate. Final runtime proof uses
`57f23beed4d4842fa1d21dc3833ab70f52d75316`; provider scope fixtures use
`c113dbe0d30fe37841e675d751657a805bd6f786`, with identical production source.
The final review handoff records the later documentation/preview revision.

| Check | Result | Evidence and source boundary |
| --- | --- | --- |
| Selected Rust model/executor/archive checks | 79 passed (32 library, 47 integration) | Shared `until-final-rust-checks.log`; nested subprocess count is not added twice |
| Observation-provider units | 5 passed | Shared `until-final-provider-units.log` |
| Python Until/browser/continuation models | 19 passed | Shared `until-final-python-models.log` |
| Known Rust callers | 8 examples and 3 affected browser harnesses compiled | Shared `until-final-callers-check.log` |
| Provider scope fixtures | 3 headless passed in 8.65 s; 3 headful passed in 7.29 s | `target/until-bound-provider-{headless,headful}/run.log` |
| Full Until fixture set, headless | 16 passed in 70.55 s | `target/until-final-fixtures-headless/run.log` |
| Full Until fixture set, headful | 16 passed in 63.67 s | `target/until-final-fixtures-headful/run.log` |
| Headful four tabs, one worker, reordered source gates | 20 rounds / 80 invocations passed in 19.36 s | `target/until-final-stress-headful/run.log`; timing is not a performance comparison |
| Partial-response cancellation and same-tab reuse | Passed headful in 3.31 s | `target/until-final-cleanup-headful/run.log` |
| Python native browser fixture | 1 passed in 4.76 s | `target/until-final-python-native/python-until.log`, saved JSONs with source/browser identity; shared command log includes runner header |
| Live exact-response recipe | httpbin passed headful and headless | `target/until-final-live-{headless,headful}/live-until.json` |
| Live dynamic-loading recipe | Navigation returned Unknown before Until in both modes | Retained failed summaries, outcomes, screenshots, and `run.log`; 30.51 s headful / 30.72 s headless |
| Archive write/fresh-handle read/equality | All 4 live records verified, including both unknown outcomes | `archive_read_verified: true`; no Archive error; pool active/queued/parked all zero after close |

The current headless fixture set covers immediate responses, old same-URL
requests, fresh Contract records and missing records, terminal malformed
evidence and predicate panic, AX/network-only evidence without HTML, result
bounds, one compound deadline, queued expiry, cancellation settlement, dropped
invocation fencing, and navigation invalidation. The intentional
predicate-panic fixture prints its panic hook but is caught and returns a
rejected assertion.

The browser fixtures use regular sandboxed Google Chrome 154.0.8037.57 and
image `sha256:355aa95235603948f766f946efbfc4f4f2a54c923d161abdb7adca4d34596537`.
The stress runner is bounded to 1 CPU, 3 GiB, and one Cargo worker. Controller
is vendored Chromiumoxide 0.9.1; generated CDP bindings are
`0.10.0-yosoi.m153.1`. Each retained browser run records source revision, mode,
and image identity. These focused runs do not constitute full browser-baseline
certification.

Vendored patch 14 replaces the renderer-side scroll observer with
`DOM.scrollIntoViewIfNeeded`; the scoped native-input helpers keep the resolved
element handle and validate its frame/epoch before input. Patch 15 supplies the
globally unique JS context ID and dispatches expression or function evaluation
in the watched frame session. Provider-side scope tests cover replacement
navigation and the current scope in both browser modes.

## Failures retained and fixes

The first 14-case headful run passed 12 cases and timed out in two. A longer
outer harness deadline let the standalone immediate-response case pass. The
multi-source failure still timed out before trigger dispatch: phase tracing
showed the background-tab scroll completed, but native input produced no
business click. The CDP scrolling patch alone did not fix that case. Guarded
foreground preparation for a hidden headful tab, then final-handle scope checks
for native input, address the observed path. The later full headful run
completed 15 of 16 cases; its remaining failure is recorded below.

The retained 15/16 headful run's only failure was a harness assumption. The
Until DOM condition evaluated true and the AX status was `Entered Blueberry-42`,
while the separately retained HTML showed `Blueberry-4`. HTML capture and the
condition read are separate observations, so the retained HTML was not a
synchronized view of the later input. The fixture now checks the final exact
HTML through a fresh leased observation after completion. The retained run
remains 15/16; the fixture correction does not rewrite or retry that result.

The scoped provider APIs take an active `ObservationWatch`, rather than a raw
`DocumentScope`, because frame and epoch identifiers are page-local and can
collide across tabs. The watch binds the scope token to its originating page
before input or JavaScript evaluation proceeds.

The retained failure is:
`background_enter_text_until_yields_capacity_and_confirms_the_typed_value`
completed its Until step; the original harness then compared the later input
with the earlier retained HTML snapshot.

The next retained headful run, `target/until-bound-fixtures-headful/run.log`,
also passed 15/16 in 63.40 s. Its multi-source outcome was correctly Satisfied,
but typing-specific assertions had been inserted into that fixture. The final
test checks DOM at index 2 and AX `Ready current` / `button` at index 1, and
puts the typing assertions in the typing fixture. Independent read-back
matched both sets of checks to their saved evidence. The subsequent complete
headful and headless runs passed all 16 cases.

An earlier 16-case headful run passed 13 and failed three due to an unpinned
typing-harness wait, generic `Unknown` classification for a known
pre-keyboard target loss, and a direct cold-run deadline that was too short.
Those failures remain retained as historical evidence. They are not combined
with the latest pass counts. The final provider changes also close the caller
scope race by retaining and checking the resolved element handle, and pin JS
evaluation to the original globally unique context. Function/arrow-string
triggers preserve the existing `Page::evaluate_js` auto-invocation behavior.

Network request-start timestamps are a freshness watermark, not proof of
causality. DOM, AX, and network checks retain separate observations; Until does
not promise an atomic cross-source snapshot. The backend is never blindly
retried to turn an uncertain trigger into success.

Earlier runs remain under `target/until-fixture-1`, `until-fixture-2`,
`until-stress-debug`, `until-stress-trace`, and the headful diagnostic folders.
Independent review also found forged Archive receipts could bypass kind,
timestamp, and canonical-reference checks. Those are fixed and covered by
`until_archive_forgery.rs`.

The final live dynamic-loading runs stopped during `navigate`, before an Until
watch or trigger existed. Their receipts retain navigation uncertainty and
their later screenshots show the Start page. Neither a later screenshot nor
an older passing run establishes safe navigation completion. The later
investigation reproduced delayed HTTP 503 responses containing Heroku's
application-error page independently of the SDK; the exact internal hosting
defect remains unconfirmed. This is a recorded live-navigation limitation for
release verification, not a passing DOM/AX/Contract proof. See
`spikes/browser-automation/until-investigation.md` for the fixed-peer captures
and the separate CSSOM wakeup and response-burst limitations. httpbin completed
in each mode, and Archive readback preserved all four success/failure records.

## Reproduce

Use the shared target and one expensive command at a time:

```sh
CARGO_BUILD_JOBS=1 CARGO_TARGET_DIR=/home/andrew/Desktop/cl/Yosoi/target \
  cargo test -p yosoi --lib --test until_model --test until_archive_forgery \
  --test assertion_groups --test flow_models --test continuation_archive \
  --test continuation_policy --test automation_record -- --test-threads=1

CARGO_BUILD_JOBS=1 CARGO_TARGET_DIR=/home/andrew/Desktop/cl/Yosoi/target \
  cargo test -p yosoi --features browser --test until_browser \
  --test until_archive_forgery --no-run

spikes/browser-automation/run-yielding.sh \
  /home/andrew/Desktop/cl/Yosoi/target/debug/deps/until_browser-e3708ecacfd85f58 \
  "$PWD/target/until-fixtures-review" \
  --nocapture --test-threads=1 \
  --skip stress_reordered_updates_across_four_tabs_and_one_worker

YOSOI_UNTIL_STRESS_ROUNDS=20 spikes/browser-automation/run-yielding.sh \
  /home/andrew/Desktop/cl/Yosoi/target/debug/deps/until_browser-e3708ecacfd85f58 \
  "$PWD/target/until-stress-review" \
  --nocapture --test-threads=1 \
  --exact stress_reordered_updates_across_four_tabs_and_one_worker

UV_PROJECT_ENVIRONMENT=/home/andrew/Desktop/cl/python-sdk-scaffold--Yosoi/.venv \
PYTHONPATH="$PWD/python" uv run --no-sync pytest \
  python/tests/test_browser_models.py python/tests/test_until_models.py \
  python/tests/test_continuation_models.py -q
```

Binary hashes/names are local build outputs; use Cargo's reported executable
path if they change. The hardened runner's headful mode is selected with
`YOSOI_YIELD_MODE=headful` and uses the same sandbox and resource bounds.
