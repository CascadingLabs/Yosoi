# Rust browser automation spike

Andrew approved a broad workspace spike, then narrowed the completion gate to
**Rust core**, with browser validation in the existing Yosoi Docker containers.
This is the first concept pass, not a production release. Existing Python edits
are parked and unverified; they are outside this handoff's gate.

Workspace: `browser-actions--Yosoi`, based on `main` at `80911cec`.
The original sessions design in `docs/public/sdk/sessions/index.md` is preserved.
Its aspirational examples remain distinct from the executable APIs below.

## One engine, two levels of control

```rust
use yosoi::{action, flow};
use yosoi::flow::{Condition, FailureCapturePolicy};

let script = flow::new([
    action::navigate(url),
    action::click("#advance"),
    action::enter_text("#query", "shared fixture input"),
    action::assert(Condition::Exists { selector: "#status.ready".into() }),
    action::screenshot(),
]).with_failure_capture(FailureCapturePolicy::Screenshot);

let outcome = script.bind(&browser_policy).invoke().await?;
```

The managed runner acquires and closes its Session automatically. Borrowed Work
runs the same steps through the same scoped Policy and capture paths. Ordinary
`request::new(url).bind(&policy).send().await?` stays unchanged; its default
Policy remains Direct HTTP. Browser acquisition uses the engine Session.

```rust
use yosoi::{request, session};
use yosoi::session::SessionPolicy;

let settings = SessionPolicy {
    maximum_tabs: 2,
    allow_arbitrary_js: true,
    ..SessionPolicy::default()
};
let session = session::new().bind(&browser_policy).configure(settings).acquire().await?;
let mut first = session.watch();
let mut second = session.watch();
let work = session.work().await?;

let response = request::new(url).with_work(&work).send().await?;
let same_receipt_one = first.next().await?;
let same_receipt_two = second.next().await?;
let outcome = script.with_lease(&work).invoke().await?;
let value = work.evaluate("40 + 2").await?;

work.release().await?;
session.close().await?;
// The returned Documents and recorded observations remain available.
```

`with_lease(&work)` configures this invocation to borrow the existing tab lease.
It does not execute steps or acquire control. `invoke()` runs the recipe, leaving
the borrowed lease and Session open for the caller to release and close.
Without `with_lease`, `invoke()` acquires and cleans up its own Session and lease.

One Work owns a concrete tab's control gate. Each tab admits at most 32 waiting
Work acquisitions; commands sharing held Work reject concurrent execution rather
than creating another queue. The engine has two browser-process slots and 32
waiting Session acquisitions. These are internal bounds, not a fleet API or a
promise that every configured tab count fits every container.

Native click/text input and screenshots share foreground ownership. Background
navigation and DOM reads can progress independently. A dropped, cancelled or
timed-out dispatched command fences its tab until cleanup. Other tabs can
continue. Missing requested capture evidence is Unknown, not false success.
JS is denied by default, independently opt-in, and never treated as pure or
rolled back. Unique URL-based frame selection and top-document epoch guards
are available through `Work::evaluate_targeted`; isolated worlds are Unsupported.

## Runnable Docker proof

The current runner uses the existing `yosoi-cas333:local` image:
`sha256:90ef59e3973300ec7c0ef8d3d8d0ca7f791ca6cc485a34ce2f13041c001137fd`.
Its regular Chrome is `153.0.8010.36`, executable SHA-256
`ac7f9884974b551d29c89f24d0c697f373ce595a920ddafced441dd2554142db`.
The controller remains vendored Chromiumoxide 0.9.1 with M153 bindings.

The image supplies the browser/runtime; the runner mounts the newly compiled SDK
test executable and shared fixture read-only. It retains the existing entrypoint,
non-root 10001:10001, Chrome sandbox, site isolation, no-new-privileges, dropped
capabilities, checked-in seccomp, read-only root and network-none. Loopback serves
the fixture inside the container. CPU is capped at one, memory/swap at 2 GiB, and
PIDs at 512. A measured 256-PID run rejected the second browser
(`pids.events: max 2`, no memory OOM).

```sh
CARGO_BUILD_JOBS=1 cargo test -p yosoi --features browser --offline \
  --test browser_sessions --test session_safety --no-run
# Use the exact executable paths printed by Cargo:
spikes/browser-automation/run-container.sh /absolute/browser_sessions-test \
  /absolute/ignored-evidence-directory --nocapture --test-threads=1
spikes/browser-automation/run-container.sh /absolute/session_safety-test \
  /absolute/ignored-safety-directory --nocapture --test-threads=1
```

The native test binary's runtime ABI was checked in this image. That does not
certify a portable Linux/Windows/wheel matrix. Run one expensive command at a
time. Tests without `YOSOI_BROWSER_TESTS=1` skip browser execution.

The shared fixture is
`spikes/browser-automation/fixtures/session-flow.html`. Baseline has 12 result
rows; `?variant=drift` has four. It serves concurrent browser connections,
bounds pending connections, and cancels them at shutdown.

## Current evidence

| Project | Built and checked |
| --- | --- |
| Sessions & Policy | Real ownership, bounded leases/commands, two watchers, request reuse, retained Documents, close/cancel, shared cookies and fresh isolation. |
| Actions, Flows & Assertions | One managed/borrowed runner; native click/text, explicit wait, condition waits, typed assertions, screenshots and separate failure-capture receipt. |
| JavaScript | Default denial, opt-in values/mutation/errors, frame/epoch targeting, result bounds and fencing of unresolved dispatch. |
| Archive & Replay | Real immutable Archive Documents, policy/provider/source lineage, fresh-process read, missing/tampered payload controls and offline assertions. JS records use their actual JS-enabled authority. |
| Views & Browser Index | Bounded DOM rows, raw evidence/exact references, live and archived projection, capture-bound cursor rejection and supported offline checks. |
| Integration & Review | Controlled Rust run spanning all projects, deliberate drift, linked records, safety controls and independent review. Final source/evidence sign-off is tracked in Linear. |

Authoritative current logs live in ignored `target/`:

- `docker-core-safety-final-validation.log`: **18 passed**, including two-process admission,
  independent tabs, cross-tab watchers and JS timeout/result/exception controls.
  Dropped borrowed Requests and exact-empty-output deadline receipts are included.
- `docker-integrated-validation.log`: earlier Docker run **2 passed**.
- `docker-core-final-validation.log`: **2 passed** before the final Request review fixes, including
  the separately attributed JS record and fresh-process replay.
- `docker-core-final-validation-v2.log`: **2 passed** on the final Request
  fencing/correlation slice, including fresh-process replay of all four records.
- `approved-model-validation.log`: **14 passed**, plus the fresh-process child
  check, covering Flow, Archive, View and existing public SDK contracts.
- `docker-process-cap-validation.log`: failed 256-PID control and actual cgroup
  counters; superseded by the passing 512-PID safety run.
- `final-http-only-check.log`: final facade compiles without browser features.

`target/docker-core-final-evidence-v2/` contains `record_ref.json`,
`rerun_ref.json`, `drift_ref.json`, `js_ref.json` and the Archive payloads.
The fresh-process replay child disables Chrome and reopens all linked records.
Browser/source identity strings are harness-recorded metadata, not automatic
source attestation. Image/browser identities are verified by the existing
entrypoint. Earlier host/older Python logs are historical, not current proof.

## Limits and next-pass corrections

Remote endpoint attachment, public placement/fleet scheduling, raw continuous
network/AX streams, isolated JS worlds and module imports remain Unsupported or
deferred. Watchers receive bounded operation receipts and retained captures.
Offline Visible requires live layout and is Unsupported. A live rerun produces
new effects and receipts; it does not restore browser memory or guarantee
arbitrary-site determinism. There is no AI discovery layer.

Result/screenshot limits bound retained values after provider transfer; they do
not impose browser-heap limits or prevent transient oversized CDP allocations.
Archive records are capped at 64 MiB. Capture fingerprints are advisory; Archive
references/digests provide persisted integrity. No performance, distributed-scale,
host-rendering or production certification claim is made.

The concrete second-pass inputs are foreground-resource scheduling, richer
terminal/cleanup evidence, explicit collector subscriptions, tighter aggregate
memory budgets and clearer authority/provenance APIs. Rust core is the reviewed
slice; Python and the six later hardening issues stay parked. No push, landing,
release or deployment has occurred.
