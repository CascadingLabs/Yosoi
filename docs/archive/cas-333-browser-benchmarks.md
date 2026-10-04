# CAS-333 browser benchmarks

CAS-333 adds bounded, loopback-only browser benchmark integration. It does not publish initial performance numbers: final numbers arrive only after controlled runs on a prepared browser host.

## Commands

```bash
cargo xtask benchmark check
cargo xtask benchmark browser
```

`check` is compile-only: it compiles the browser Criterion and allocation harnesses and `profile_browser`, without collecting a measurement. `browser` invokes `scripts/browser/run-cas-333-browser.sh`, the all-four-environment orchestrator. It records native Criterion and Divan evidence plus native and container profile matrices under one atomic `browser/` result root. Browser work is intentionally excluded from `cargo xtask benchmark all`; existing direct-HTTP baselines must remain uncontaminated.

## Environments

The result root always labels these distinct environments:

- `native-headless`: browser execution on the prepared host without a display;
- `native-headful`: browser execution on the prepared host inside a dedicated X11/Xvfb display;
- `container-headless`: browser execution in the hardened Docker boundary without a display;
- `container-headful`: browser execution in the hardened Docker boundary with an event-readied headless Sway/Wayland display.

They are not interchangeable comparison groups. Native measurements reflect host browser, display, GPU, driver, viewport/DPR, and `/proc` variance. Container measurements additionally reflect image identity, Docker scheduling/storage, cgroup-v2 behavior, seccomp, fixed resource limits, and software compositor overhead. Compare only equivalent labels with matching recorded source/provider/fixture hashes, browser metadata, artifact set, workload, concurrency, and limits. See [CAS-333 container benchmarks](cas-333-container-benchmarks.md) for the container security and cgroup contract.

Final CAS-333 certification accepts only a regular Chrome/Chromium Stable
distribution intended for normal browsing. The orchestrator rejects Chrome for
Testing explicitly. Testing-only browser builds are prohibited for all Yosoi
execution; there is no diagnostic exception.

## Scope and metric separation

The Criterion harness has distinct names for:

- provider capture to staged facts;
- browser finalization with capture setup excluded; and
- capture plus finalization end to end.

Do not combine those timings. They answer different questions. Process-tree sampling is likewise separate: it records controller and recursively discovered Chromium/other-descendant roles, RSS, PSS where available, CPU ticks, FD count, thread count, process count, and explicit unavailable fields. Process-tree metrics are diagnostics, not replacements for Criterion timing, allocation counts/bytes, peak heap, or direct-HTTP process metrics.

Each headless/headful and minimal/full/growth Criterion combination runs in a
separate benchmark process. Native headful execution unsets the ambient Wayland
display and runs in an isolated `1920x1080x24` X11/Xvfb server; the exact Xvfb
and `xvfb-run` paths and SHA-256 digests are recorded. Its command, console
output, and raw estimate tree remain separate beneath the same atomic result
root, preventing accumulated browser lifecycle or interactive desktop focus,
occlusion, and workspace state from contaminating another mode or artifact set.

Fixtures are committed synthetic HTML served only from IPv4 loopback. The fixture manifest identifies minimal, full, and growth artifact cases; contract tests pin their byte sizes and SHA-256 digests. Headless runs are always included. Native headful cases require Xvfb and `xvfb-run`; container headful cases provision their bounded internal Wayland compositor.

## Bounded matrix and outputs

The profile covers success, cancellation requested only after every concurrent delayed-loopback request has been accepted (post-ownership cancellation), a bounded deadline, and a loopback declared-length partial-disconnect stimulus that must end as a truthful stopped partial capture (provider stop or bounded deadline). Native and container matrices execute those workloads at concurrency 1, 2, and 4. Container summaries also report nearest-rank p50, p95, and p99 for elapsed and cancellation-return attempts alongside cgroup diagnostics.

Native and container success/cancellation/failure attempts use a 15,000 ms
bound; the deliberate deadline workload remains fixed at 5,000 ms. The
benchmark manager separately uses a 45,000 ms cleanup deadline, allowing
VoidCrawl's bounded close, reap, kill, and handler-stop fallback phases to
complete. Every limit remains a hard bound, and any cleanup timeout or remaining
browser process still fails certification.

The orchestration root and every profile/soak destination are built in staging directories and renamed atomically. The browser root retains exact Criterion, Divan, and matrix commands, raw outputs, fixture/provider hashes, and constrained environment metadata, so a failed or interrupted run does not leave a partial per-change output directory. Native identity in `environment.txt` uses schema `cas333.native-browser-identity.v1`: it records the canonical `CHROME`-first executable path, one-line version, and executable SHA-256; the JJ/Git revision, change, dirty state, and a non-ignored source-tree SHA-256 that includes eligible untracked source; the vendored Chromiumoxide package/version/upstream revision/source-tree SHA-256; and the generated CDP package/version, Chrome/Chromium/V8 revisions, source-tree SHA-256, PDL manifest SHA-256, generated-output manifest SHA-256, and generated Rust SHA-256. Criterion and both native profile modes bind that exact executable and identity explicitly. The orchestrator recomputes the full identity after measurement and rejects drift before replacing the published result. Container records use relative artifact names and persist image/hash/security identity rather than full inspect output, environment dumps, or process argv.

No public URL is a valid benchmark target. Result artifacts retain only the runner-constructed benchmark commands needed for reproduction; they must not persist sampled process argv, secrets, dotenv contents, proxy-derived targets, or environment dumps.

## Initial review alerts and limitations

The initial budgets are review alerts, not universal CI thresholds. They apply only when environment label, source/provider/fixture/image identities, browser version, resource limits, and workload match:

- any nonzero finalization failure, cleanup timeout, remaining process/cgroup/container, nonzero runner status, or attempt-count mismatch is an immediate correctness alert;
- provider capture or end-to-end median wall time moving by more than 25%, or an entire Criterion estimate interval moving beyond the prior interval, requires review;
- setup-excluded Yosoi finalization requires review at 2x or an absolute increase of 100 microseconds because its baseline is small and noisy;
- allocation-count increases require review; total allocated or maximum live bytes moving by more than 15% requires review;
- native RSS/PSS/FD/task/CPU and container cgroup memory/PID/CPU/IO metrics moving by more than 30% require review, not automatic failure.

The operational defaults remain bounded and can be raised explicitly for unattended soak. Browser startup, Chromium scheduling, Docker storage, software compositing, and host load introduce substantial variance; tight timing or memory gates would create false positives before repeated same-snapshot baselines exist. Missing PSS, RSS, FD, cgroup, IO, or close-time data is reported unavailable rather than inferred.

## Advantages and disadvantages

Advantages: the in-process adapter preserves rich typed evidence and exact cleanup state; deterministic loopback inputs eliminate public-network variance; finalization cost is isolated from browser lifecycle; native PID-tree and container cgroup scopes expose leaks that controller-only metrics miss; rootless networkless containers match the intended server deployment boundary.

Disadvantages: fresh Chromium process ownership dominates latency and memory; browser timing remains noisy; finalization copies/hashes canonical payloads; headful rendering depends on compositor behavior; container builds coordinate Yosoi and VoidCrawl source identities; local path dogfood still prevents final clean-pin certification. The native schema proves the selected executable and checked-out source identity, but does not prove package-manager provenance, code signing, host-library/driver identity, display/compositor identity beyond configured/not-configured, or that the recorded Chrome milestone is compatible with the generated CDP revision; that compatibility remains a separate certification decision. Registry images or a service boundary should be considered only if repeated evidence shows source coordination or process overhead outweighs the evidence/isolation benefits.
