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
cargo xtask benchmark all
```

`check` compiles repository harnesses without collecting measurements. Capture
classes run serially with one Cargo worker. Browser harnesses remain available as
explicit `cargo bench` commands; the legacy native/container certification and
soak script matrices are retired. A new browser certification must still provide
the identities, security checks, regressions, and measurements required by
`docs/chromium-cdp-baseline.md` before promotion.

Gungraun 0.19.4 is pinned by the benchmark package. Its Callgrind metrics include instructions and modeled cache behavior. DHAT heap measurements remain a separate measurement run; allocation count, total allocated bytes, peak live heap, and end-of-process heap must remain distinctly named metrics.

## Local results

`cargo xtask benchmark <class> [output-directory]` owns capture measurement
execution directly in Rust. Each run uses one Cargo worker and the capture lock;
classes run serially. JJ results group by stable change ID, and each run records
the measured source snapshot. Git-only checkouts group by commit ID.

```bash
cargo xtask benchmark result-dir criterion
cargo test -p xtask -- --test-threads=1
```

Capture results contain `metadata.json`, exact command descriptions, separate
stdout/stderr logs and exit statuses, and raw Criterion, Callgrind, perf, or
Massif artifacts. GNU time retains its resource report. Perf failures retain
diagnostics; raw counter files are not asserted to contain usable numeric metrics.
These are local measurements with no inferred regression threshold.

Successful publication keeps the latest result at `<change>/<class>/` and moves
previous runs into `history/<class>/<unique-run>/result/`. Failed publication
restores the previous result. Failed measurement logs remain in their staging
directory. The publication command is also available independently as
`cargo xtask benchmark publish <staging> <destination>`.

The bespoke capture Markdown reports, derived CSV/dashboard, Python summarizers,
and shell benchmark runners are retired. Inspect the raw tool outputs instead.
Existing historical results are retained. Browser profile binaries remain available for explicit development runs.
