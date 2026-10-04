# Repository-wide benchmarks

`yosoi-benchmarks` owns capture/browser measurements;
`yosoi-document-locator-benchmarks` isolates the static Documents and Locators
SDK from those heavyweight dependencies. Production crates own no measurement-tool dependencies.

## Layout

- `benches/criterion_capture.rs`: capture wall-clock latency and throughput.
- `benches/gungraun_capture.rs`: one-shot Callgrind instruction and modeled-cache evidence.
- `benches/allocation_capture.rs`: allocation count and allocated-byte evidence using Divan's allocator profiler.
- `src/bin/profile_capture.rs`: stable loopback-only process boundary for RSS, utilization, hardware counters, and process heap tools.
- `benches/criterion_browser.rs` and `src/bin/profile_browser.rs`: CAS-333 browser capture/finalization timing and bounded browser-process attempts.
- `document-locators/benches/criterion_document_locators.rs`: XML and accessibility-tree parse, locate-only, and end-to-end timing on tiny golden fixtures.
- `document-locators/benches/criterion_documents.rs`: decoded-text parsing, locating, and end-to-end evaluation, with opt-in advanced
  text input.
- `document-locators/benches/document_locators.rs`: source-HTML and canonical rendered-DOM parse, locate, and end-to-end timings on their tiny golden products fixtures; an opt-in advanced rendered-DOM parse case.
- `document-locators/benches/criterion_json.rs`: source-JSON parse, locate, and end-to-end timing.
- `document-locators/benches/allocation_document_locators.rs`: per-modality end-to-end allocation count, allocated bytes, and maximum live allocation evidence.
- `src/bin/profile_browser_execution.rs`: CAS-352 warm-process fresh-context capacity and soak records.
- `src/bin/profile_browser_stealth.rs`: CAS-374 fingerprint, lifecycle, and optional passive live-detector evidence.
- `fixtures/web-capture/v1/`: fixed public-synthetic inputs shared across measurement classes.
- `fixtures/browser-capture/`: committed loopback-only CAS-333 browser inputs.
- `fixtures/document-locators/v1/`: the tiny offline 15-pair document/locator
  conformance authority plus a compressed retained advanced stress artifact.
- `results/by-change/jj/<change-id>/`: machine-specific retained baselines grouped under the stable JJ change identity.
- `results/by-change/git/<commit-id>/`: fallback layout when JJ is unavailable.

Setup, fixture reads, server construction, and input construction must remain outside the measured operation unless a benchmark name explicitly says otherwise. Criterion, Callgrind, DHAT, hardware counters, and process RSS are separate measurement classes and must be reported separately.

The document-locator Criterion harnesses separate parse, locate, and
end-to-end timing for XML, accessibility trees, source HTML, canonical
`yosoi.rendered-dom.v1`, decoded text, and source JSON. Fixture/document
construction, plan construction, and pre-parsed input stay outside measured
operations. End-to-end cases include parsing and locating; they exclude document
and plan construction. Advanced fixtures are materialized and verified offline. Both the
decoded-text and rendered-DOM cases require `YOSOI_DOCUMENT_LOCATOR_ADVANCED_DIR`
to select advanced input; they read materialized files and never launch a browser
or CDP session. Do not collect or publish timings until the applicable
correctness checks and independent reference agreement have passed. By default,
the benchmark targets use only tiny golden fixtures. See
[`fixtures/document-locators/v1/README.md`](fixtures/document-locators/v1/README.md).

All document-locator targets are compiled by `cargo xtask benchmark check`.
Run them individually with `cargo bench -p yosoi-document-locator-benchmarks --bench
criterion_document_locators`, `--bench criterion_documents`, or `--bench
document_locators`; JSON and allocation evidence use `--bench criterion_json`
and `--bench allocation_document_locators`. The decoded-text target reads
`derived/whatwg-html-standard.txt` beneath the configured materialized directory;
if the environment variable is unset, it uses the tiny golden text fixture.

## Commands

Use the single repository entry point:

```bash
cargo xtask benchmark check
cargo xtask benchmark criterion
cargo xtask benchmark deterministic
cargo xtask benchmark allocations
cargo xtask benchmark process
cargo xtask benchmark heap
cargo xtask benchmark browser
cargo xtask benchmark browser-execution
cargo xtask benchmark browser-stealth
cargo xtask benchmark all
```

`check` is compile-only: it compiles all harnesses, including the CAS-333 browser Criterion/allocation harnesses and browser profile binary, without collecting measurements. `criterion` publishes the capture wall-clock baseline; document-locator timings
use the individual `cargo bench` commands above. `deterministic` runs Callgrind after verifying Valgrind and the matching Gungraun runner are installed. `allocations` runs Divan with allocator instrumentation. `process` runs full, compressed, redirect, and truncated loopback capture workloads in fresh processes under GNU time and perf. `heap` runs the same process workloads under Massif with stack accounting enabled. `browser` is the all-four-environment CAS-333 orchestrator. It sequentially records browser Criterion (`criterion_browser`), browser Divan allocation (`allocation_browser`), and bounded loopback-only success, post-ownership cancellation, deadline, and failure matrices at concurrency 1/2/4 for `native-headless`, `native-headful`, `container-headless`, and `container-headful`. All classes publish atomically under one per-change `browser/` root with exact commands, raw outputs, fixture/provider hashes, and constrained environment metadata. Container matrices add p50/p95/p99 and cgroup-v2 CPU/memory/PID/IO/throttling/events diagnostics. It is deliberately excluded from `all` until browser-host variance and provider availability have a separately reviewed baseline. `all` runs capture Criterion, Callgrind, allocation, process, and heap
measurements sequentially. Document-locator and browser runs are separate. The
capture runner scripts compile with one Cargo worker to keep the workstation
responsive.

Gungraun 0.19.4 is pinned by the benchmark package. Its Callgrind metrics include instructions and modeled cache behavior. DHAT heap measurements remain a separate measurement run; allocation count, total allocated bytes, peak live heap, and end-of-process heap must remain distinctly named metrics.

## Local history and comparison

Each runner resolves its default destination with `scripts/benchmarks/benchmark-result-directory.sh`. JJ repositories group all measurement classes under the stable change ID, while each baseline also records the exact source snapshot commit measured. Git-only checkouts group by commit ID.

```bash
scripts/benchmarks/benchmark-result-directory.sh criterion
find benchmarks/results/by-change -name baseline.md -print
```

Capture runners and the browser, browser-execution, and browser-stealth
orchestrators keep the latest successful result at the existing destination
(for capture, `<change>/<class>/`) for the dashboard. When replacing it, they move the previous result, including raw
evidence and source metadata, into
`<destination-parent>/history/<destination-name>/<timestamp>.<unique-id>/result/`;
no second copy is created. Failed publication restores the previous result. The dashboard reports
only the latest run of each class, so repeated measurements do not become extra
trend points. The standalone browser profile and soak diagnostics retain their
existing publication behavior.

Capture classes share a nonblocking lock and compile with one Cargo worker.
Criterion writes into the run directory instead of deleting or copying the
shared `target/criterion` tree. No stale staging directories or historical runs
are automatically deleted. Choose the narrowest class needed for a concrete
question; a passing check or unchanged result does not justify another run.
Retain failed-run diagnostics separately when investigating a failure.

Start a new JJ change before measuring a code modification to retain
side-by-side history. Compare Criterion estimates or Gungraun summaries only when fixture digests, toolchain, target, profile, features, and relevant environment metadata agree.

CAS-352 adds directly comparable cold-process and warm-process/fresh-context Criterion cases. `cargo xtask benchmark browser-execution` runs those two Criterion commands and the loopback-only 1×1, 1×2, and 2×4 process/context/concurrency soak matrices sequentially. Every measurement command explicitly receives the canonical Chromium executable selected through VoidCrawl's detection order; finalization records its path, digest, and version alongside final Yosoi, VoidCrawl, and chromiumoxide dirty-source hashes. It rejects source/runtime drift, verifies each soak JSONL has `concurrency × iterations` attempts plus one matching summary, and hashes metadata with the exact command/output evidence. `CAS352_SOAK_ITERATIONS` bounds the local soak. An unfinalized directory, or one whose recorded identity no longer matches current source/runtime, is not final evidence and must be regenerated rather than relabeled. These are local operating-envelope observations, not CI thresholds; do not run them concurrently with another browser lane.

CAS-374 keeps its deterministic fingerprint matrix separate from optional live
detector observations. `cargo xtask benchmark browser-stealth` binds every
record to the certified Chrome 153 container, runs one 1-CPU/2-GiB cell at a
time, and aborts on host memory or swap growth. Public detector URLs are never
contacted by default; `--live-suite substrate` or an explicit `--live-url`
requires approval because it shares browser and network fingerprint data with
that third party. Live URLs must be HTTPS and contain no credentials, query, or
fragment. The default policy uses a reserved non-zero loopback CDP port and
expects Chrome's native `navigator.webdriver=false`; explicit port zero is the
native-true comparison and the bounded page getter remains rejection evidence.
The certified stealth profile uses minimal CDP: the final Device & Browser Info
matrix detected normal CDP in both display modes, while minimal CDP was not
flagged. Normal CDP remains an explicit capability profile rather than a
stealth-certified one.

CAS-333 separates provider capture-to-staged-facts timing, finalization timing with capture setup excluded, and capture-plus-finalization end-to-end timing. Browser Divan allocation metrics, where parseable, remain distinct from wall time. Browser process-tree RSS/PSS, CPU ticks, FD count, thread count, process count, controller/browser/renderer/GPU/utility roles, cleanup/orphan fields, and unavailable metrics are diagnostic process measurements, not substitutes for Criterion timings or allocator/heap metrics. The dashboard normalizes browser metrics separately from Direct HTTP tool and scope labels; the bounded profile records atomic per-change outputs only and does not establish final performance numbers. Native and container labels are separate comparison populations: container results additionally depend on the exact image/source hashes, Docker and cgroup-v2 behavior, fixed isolation limits, seccomp, and headful software compositor. Never treat container timing as interchangeable with native timing. Container runs are rootless, networkless, read-only, capability-dropped, no-new-privileges, sandbox-required executions; their records retain identity and relative artifacts rather than full inspect, environment, or argv data. See `docs/archive/cas-333-container-benchmarks.md`.

Publication, rollback, dashboard isolation, and capture locking can be checked
without compiling Rust or collecting measurements:

```bash
python3 scripts/benchmarks/test-publication.py
```

Valgrind and `gungraun-runner` are intentionally not installed by repository scripts. Install the matching runner with `cargo install gungraun-runner --version 0.19.4 --locked`. On unsupported or unprepared hosts, compile the harness but report deterministic and heap metrics as unavailable rather than substituting Criterion timing numbers.
