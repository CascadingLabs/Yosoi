# Policy capture wiring

## Verified E2E handoff — 2026-09-26

Isolated JJ change: `uxztousq`, stacked on CAS-398 `f02f07dc`. This receipt
covers the independent page/request policy path, not the pending Documents and
Locators namespace integration or combined certification.

| Gate | Evidence |
| --- | --- |
| SDK default-feature regressions | 22 tests passed; declaration example compiled |
| Real wreq HTTP E2E | 5 cases passed: default/404, byte-limited partial evidence, redirect admission/rebind, cancellation, concurrent fresh capture IDs |
| Real HTTP deadline | Custom 20 ms limit stopped a held response and retained applied identity |
| Live Headless browser | Source, synchronous-JS DOM/AX, bundle publication, identity and observed complete cleanup passed |
| Live Headful browser | Same assertions passed on an owned event-ready Xvfb display |
| Existing HTTP orchestration | Four formats and exact retained payloads passed through the standard public path |
| Targeted lint | SDK all targets with browser enabled and changed HTTP library passed `-D warnings` with `--no-deps` |

## Package layout after runtime consolidation

Since SDK 0.1.1, runtime modules are compiled under the private
`crates/yosoi/src/internal` tree. The controller integration lives in
`internal/browser`; its `yosoi-browser-core` component identity and 0.1.0
component version remain distinct from the enclosing SDK version. Browser
support is enabled through the public `yosoi` crate's `browser` feature.

The browser tests used regular Google Chrome Stable 153.0.8010.36 copied from
existing image `sha256:90ef59e3973300ec7c0ef8d3d8d0ca7f791ca6cc485a34ce2f13041c001137fd`.
Executable SHA-256: `ac7f9884974b551d29c89f24d0c697f373ce595a920ddafced441dd2554142db`.
The local test executable is `/tmp/cas399-regular-stable.ORA3A0/chrome/chrome`.
At the time of this receipt, VoidCrawl was the separate `void_crawl_core` 0.5.0
package. The current private module preserves its controller component
identity/version separately from the SDK package. The vendored controller
remains Chromiumoxide 0.9.1 (upstream base
`a7e2bb835b9643410f9e3dc044f0d947e96cbfa4`), and generated CDP remains
`0.10.0-yosoi.m153.1` / `r1681091`. No controller, generated protocol,
sandbox, launch-security or stealth setting changed.
These are adapter regression results, not a new full browser certification.

Run checks serially with `CARGO_BUILD_JOBS=1`, `--jobs 1` and
`--test-threads=1`. Browser test compilation used `CARGO_PROFILE_TEST_DEBUG=0`
and `CMAKE_BUILD_PARALLEL_LEVEL=1`; inspect memory/host workers first. The
runner checks the explicit browser digest, rejects testing-only distributions,
requires a positive passing test count, waits on Xvfb's `-displayfd` readiness
event, and reaps its own display without changing the operator's desktop.

```sh
bash scripts/browser/run-policy-browser-e2e.sh /path/to/regular-stable/chrome \
  ac7f9884974b551d29c89f24d0c697f373ce595a920ddafced441dd2554142db \
  headless sdk_browser_capture_headless_finalizes_policy_evidence_and_cleanup
bash scripts/browser/run-policy-browser-e2e.sh /path/to/regular-stable/chrome \
  ac7f9884974b551d29c89f24d0c697f373ce595a920ddafced441dd2554142db \
  headful sdk_browser_capture_headful_finalizes_policy_evidence_and_cleanup
```

Both browser processes and the task-owned Xvfb server were absent in the
post-test host process check. Xvfb emitted non-fatal GPU/keymap warnings.
Three pre-existing unused-import groups in the browser dependency still appear
in Direct HTTP-only builds; this is not a whole-workspace warnings-clean claim.
Full workspace/browser certification, external-site testing, and CAS-400/401
Documents/Locators integration were not run. Andrew confirmed those engine
dependencies are owned by the other conversation; CAS-393/394 are still Backlog.

Status: implemented end-to-end dispatch for prepared Direct HTTP and browser
policy attempts. A prepared attempt owns its validated engine spec and applied
policy snapshot; capture execution does not reread configuration or policy.

## Public entry points

The caller owns a Policy declaration and creates a snapshot with
`PolicySnapshot::from_policy(&policy)`. Each request is passed with that
borrowed snapshot to `PolicyResolver::resolve(&snapshot, request, context)`.
The caller may inspect the result before consuming it with
`ResolvedPolicyAttempt::execute(cancellation)`. A Requests project may own a
long-lived declaration and make this call per capture; that runtime ownership
is outside this facade.

`PolicyCapture` preserves the acquisition-specific result and provides common
access to its `CaptureBundle` and `AppliedPolicy`. A Direct HTTP result keeps
the complete `DirectHttpCapture`, including response status, final URL,
resolution, and source facts. A browser result keeps the finalized bundle and
the observed cleanup state from its unmanaged `BrowserAdapterResult`.

The ordinary browser path does not create a managed execution receipt. Its
cleanup state is available through `PolicyCapture::browser_cleanup()`; finalized
browser metadata may therefore have no `browser_execution` receipt. A
finalization error retains a clone of the bounded adapter result as typed
failure evidence.

That clone is created before finalization on every browser attempt, including
successful captures, and is dropped after successful publication. Some staged
payloads share storage, but structured accessibility evidence copies vectors;
finalization also materializes payload copies. Per-attempt domain bounds constrain
retention, not aggregate or peak process memory. This is an explicit memory cost
of preserving the original evidence when the existing finalizer consumes it.

## Execution paths

Direct HTTP passes the policy-mapped
`DirectHttpRedirectTargetPolicy` to
`capture_direct_http_with_redirect_policy`. That full orchestration entry point
uses the existing response-body, decoding, classification, lifecycle, and
bundle-finalization pipeline. Existing standard Direct HTTP entry points
delegate with the engine's standard Allow HTTP(S) target rule.

Browser execution is available through the facade's `browser` feature, which
enables the SDK's private browser provider modules. The default facade build
retains Direct HTTP without enabling browser dependencies. With
browser support enabled, execution calls `capture_attempt(spec, cancellation)`,
samples the real wall-clock finish time after the adapter returns, and calls
`finalize_browser_capture`. Resource and initiator origins are marked
Unobserved because this one-off attempt does not claim to have observed them.
Stopped or partial adapter results go through the same finalizer and retain
their actual terminal facts.

The caller's `CancellationToken` reaches the selected engine unchanged. There
is no fallback or retry between Direct HTTP and browser acquisition. Browser
provider resources remain owned and cleaned up by the existing adapter path.

## Error and evidence boundaries

Preparation failures are `PolicyResolutionError` and contain no applied
identity because no valid attempt spec exists. Once resolution has produced a
valid attempt, execution failures are `PolicyCaptureError::Execution`, which
retains the exact `AppliedPolicy` and the typed engine cause.

Direct HTTP errors retain transport or body failure facts, and construction
failures retain their `DirectHttpCaptureEvidence`. Browser adapter errors keep
their typed execution receipt where one exists. Browser finalization errors
retain the cloned `BrowserAdapterResult`, including staged evidence and the
observed cleanup state. The errors do not replace engine causes with strings.

Applied policy decisions and quantitative limits are content-free. They
include policy identity, selected acquisition, required/optional evidence
resolution, bounds, and the forwarded redirect-target rule. They never include
the target URL or captured source. The successful engine result separately
provides the data needed for callers that are authorized to inspect it.
