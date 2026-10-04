# CAS-335 Yosoi browser acquisition certification

## Disposition

**Locally certified with the maintainer-approved VoidCrawl path dependency; ready for Final Boss review.**

The browser acquisition foundation executes bounded headless and headful Chromium document navigation, returns only Yosoi-owned facts after teardown, finalizes complete and stopped attempts into immutable `WebCapture`/`CaptureBundle` results, reconstructs offline, rejects payload tampering, and has native plus hardened-container resource evidence.

By maintainer disposition, Yosoi retains the local VoidCrawl path until Oxide is done. This certification makes no immutable publication-pin claim. Historical base `c1cba0dc196dc66b8c188b2e465e237b7cabdbad` does not contain the certified provider contract and must not be substituted.

## Certified local source and versions

- Yosoi browser adapter: `yosoi-web-capture-voidcrawl` 0.1.0.
- Local provider API: `void_crawl_core` 0.5.0 from `../VoidCrawl/crates/core`.
- Chromium controller: vendored `chromiumoxide` 0.9.1.
- Native browser observed during CAS-333: Chromium 152.0.7977.82.
- Hardened container browser: Google Chrome 149.0.7827.102.
- Container runtime base ID used by bounded smoke: `sha256:9f89ca6fcbe3ed40f9c3847edaecf9de98b997e57dd65395a990916cd68dd82a`.
- Rust toolchain: 1.98, edition 2024.

These version facts describe local evidence, not an immutable dependency certification. The manifest and lockfile intentionally retain a path dependency with no source/checksum until Oxide is done.

## Certified behavior

One validated `ResolvedBrowserCaptureSpec` controls mode, fresh isolation, environment overrides, instrumentation, artifact requests/schemas/identities, URL/header/body admission, observation bounds, and terminal policy. The adapter:

1. launches one owned Chromium process;
2. creates a fresh disposable isolated context and page;
3. applies validated environment overrides;
4. arms observation/navigation before navigation;
5. enforces cancellation, deadline, event/resource/byte bounds, and optional quiet settlement;
6. captures requested source, rendered DOM, accessibility, network, layout, PNG visual, and runtime evidence;
7. finalizes or cancels collectors, disposes the context, closes the session, and resolves terminal precedence;
8. crosses the provider boundary only with validated owned Yosoi facts and bytes;
9. publishes only after browser finalization and exhaustive `CaptureBundle` payload validation.

Source response bytes remain distinct from rendered DOM. CDP decoded response bodies are never called raw wire bytes. Structured evidence and raw-payload browser context retain schemas, document epochs/scopes, coordinate spaces, offsets, completeness/loss, provenance, lineage, byte extent, digest, and sensitivity. Console/exception values remain redacted from canonical metadata; retained-value digests and byte accounting remain.

Complete, logical partial, byte-truncated, discarded, unavailable, failed, policy-omitted, and unsupported family results remain distinct. Stopped attempts can yield validated incomplete bundles; a provider stop with no preserved artifact evidence is failed rather than partial. Unknown in-flight measurements remain explicitly unavailable rather than zero.

## Durable and architecture boundary

`finalize_browser_capture` is provider-neutral and has no VoidCrawl, Chromium, CDP, `wreq`, or Direct HTTP semantic dependency. It derives resolution only from admitted network facts, converts capture offsets to checked wall-clock provenance, constructs receipts/observations/manifests, and returns only a fully finalized bundle.

Canonical metadata plus exact `(WebArtifactRef, bytes)` pairs reconstruct in another process without a browser. Missing, foreign, orphaned, substituted, wrong-size, wrong-digest, and corrupted payloads fail closed. Source representation lineage is revalidated against the finalized source artifact. DOM/source scope and visual facts survive in durable browser artifact context; AX/network/layout/runtime decode from canonical typed structured evidence.

Semantic artifact relationships remain empty when exact artifact-to-artifact correlation is not provable. Shared epoch or timestamp proximity is not promoted into invented lineage.

## Verification evidence

Focused successful evidence captured during the project includes:

- Final repository aggregate gate after the CAS-347 deadline-test correction: `cargo xtask check` passed workspace Clippy and policy checks, 676/676 tests, and cargo-deny advisories/bans/licenses/sources.
- CAS-347 retained concurrent test execution while raising the all-inclusive deadline budget and reporting early task completion; the corrected case passed in three concurrent runs with no Chromium residue.
- CAS-332 provider-neutral browser finalization/handoff: 11/11 tests.
- Provider-neutral browser contract matrix: 15/15 tests.
- Final local adapter suite after provider corrections: 20 unit + 17 lifecycle + 14 source/DOM/network + 3 dependency + 9 smoke = 63/63 tests.
- CAS-333 benchmark/container contract: 9/9 tests.
- Browser benchmark Clippy and compile-only harness gate: passed.
- Native headless process soak: 560 attempts across 12 cells, zero finalization failures, cleanup timeouts, or remaining/orphan PIDs.
- Hardened container full-family matrices: headless 12 cells/28 attempts and headful 12 cells/28 attempts; every exit zero, finalization `ok`, attempt cleanup `Complete`, cgroup disappeared, and no labelled container remained.
- Native headful full-family repeated provider gate: all three Criterion groups completed 10 measured iterations after warmup with Visual included and no deadline/provider failure.

See `docs/archive/cas-333-browser-results.md` and the ignored local per-change dashboard for measurement identity and limitations. A maintainer-requested long all-four run was stopped and atomically published no result; it is not claimed.

## Operating envelope and review alerts

The foundation is conservative: one owned launched browser process and fresh context per attempt. Native and container concurrency 1/2/4 were exercised. Container comparisons use rootless UID/GID 10001, network none, read-only root, 1 GiB tmpfs and shared memory, 4 GiB memory/swap, 2 CPUs, 1,024 PID limit, capability drop ALL, no-new-privileges, reviewed seccomp, and Chrome sandbox enabled.

Correctness alerts are zero-tolerance for finalization failure, cleanup timeout, residual PID/cgroup/container, nonzero runner status, or attempt-count mismatch. Matching-identity review alerts are 25% browser/end-to-end timing, 2x or +100 microseconds finalization, any allocation-count increase or 15% allocation-byte increase, and 30% process/cgroup resource movement. These are review triggers, not universal CI gates.

## Known limitations

- The maintainer-approved local VoidCrawl path remains until Oxide is done; this is not an immutable publication pin and does not support a clean external-checkout claim.
- Browser response bodies are the explicitly named CDP decoded layer, not raw transfer bytes.
- Provider frame/loader identifiers are not promoted into durable document identity.
- Screenshot/AX collection is post-materialization bounded, not streaming-memory bounded.
- Browser timing and native headful compositor behavior are noisy; repeated matched-source evidence is required for comparison.
- Cookies and storage capture/mutation, persistent profiles, leases, operator handoff, actions, sessions, replay, policy, crawling, extraction, archive, remote storage, and SDK stabilization remain outside this foundation.
- Browser bundles are in-memory transfer boundaries; this project does not define archive admission or remote storage.

## In-process adapter assessment

Advantages: no provider serialization hop; owned teardown before publication; exact typed evidence and accounting; straightforward cancellation; reusable VoidCrawl lifecycle; small Yosoi finalization overhead relative to Chromium; offline consumers need no browser.

Disadvantages: coordinated source/API evolution across repositories; browser process memory and launch latency; provider bugs can block adapter builds; payload copies/hashing/canonical serialization remain visible; native compositor variability; current local source coupling prevents reproducible external consumption.

A registry release or process/service boundary is justified later only if repeated evidence shows that source coordination, crash isolation, independent deployment, or multi-language consumption outweighs added IPC, payload transfer, lifecycle, and version-negotiation cost.

## Maintainer disposition and post-Oxide action

The local VoidCrawl path is approved for the remainder of Oxide and does not block CAS-335 Final Boss review. It remains a publication limitation, not an immutable production pin.

After Oxide is done, a separate publication step may select an exact reviewed reachable Git revision or registry release, update `Cargo.lock`/`deny.toml`/dependency-contract assertions, disable local overrides, and reproduce clean-checkout gates. CAS-335 does not claim that future publication evidence.
