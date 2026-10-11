# Benchmarking conventions

Yosoi measures performance with specialized tools rather than attempting to collect every metric in one benchmark run. Instrumentation changes the program being measured, and measurements from different machines or build configurations are not directly comparable.

Repository-wide benchmark harnesses, fixed fixtures, and retained results live
under `benchmarks/`. The `yosoi-benchmarks` workspace member owns capture and
browser measurements; `yosoi-document-locator-benchmarks` owns offline Documents
and Locators measurements without browser dependencies. Production crates expose
behavior through public APIs but do not own measurement-tool dependencies. Add
workloads to the appropriate benchmark package. See
[`benchmarks/README.md`](../benchmarks/README.md) for commands and layout.

## Measurement layers

Yosoi and cooperating acquisition repositories use three explicit layers:

- **L0 — in-process Rust:** Criterion wall-clock/throughput, Gungraun modeled instructions/cache, and narrowly scoped Divan allocation evidence for synchronous benchmark threads.
- **L1 — fresh Yosoi process:** GNU time, perf, and Massif around a stable loopback-only executable. These measure the Yosoi process boundary, not a future browser process tree.
- **L2 — browser/CDP system:** deterministic browser fixtures plus browser, renderer, GPU, and helper-process accounting. Whole-browser memory requires cgroup v2 or bounded PID-tree sampling with RSS and preferably PSS; `/usr/bin/time -v` on the controller alone is insufficient.

The layers share fixture identity, environment metadata, result vocabulary, and publication conventions while retaining repository-owned workloads. Yosoi owns capture/finalization/decoding scenarios; a browser provider owns CDP lifecycle, process cleanup, and pool/concurrency scenarios.

## Measurement classes

Use the narrowest measurement class that answers the question.

### Wall-clock latency and throughput

Use [Criterion.rs](https://bheisler.github.io/criterion.rs/book/) for in-process Rust benchmarks. Criterion provides warm-up, repeated sampling, statistical comparison, and throughput derived from a declared workload size.

Use [hyperfine](https://github.com/sharkdp/hyperfine) when startup, process boundaries, or end-to-end command execution are part of the workload. Use GNU `time -v` separately when a Linux macrobenchmark needs peak resident set size or user and system CPU time.

### Deterministic CPU and memory regressions

Use pinned [Gungraun](https://gungraun.github.io/gungraun/latest/html/index.html) harnesses in `benchmarks/` on Valgrind-supported platforms for instruction counts, modeled CPU cache behavior, DHAT or Massif memory profiles, regression limits, and Callgrind flamegraphs. These measurements are useful in noisy CI environments, but simulated cycle estimates are not substitutes for wall-clock time.

Use Linux `perf` when actual hardware counters, such as cycles, instructions, branches, cache misses, context switches, or page faults, are needed. Results are machine-dependent and belong to a recorded test environment.

Allocation count, allocated bytes, live heap, peak heap, peak process RSS, and proportional set size (PSS) are different metrics. Reports must name the measured quantity rather than referring to an ambiguous "memory usage" value. Thread-local allocation profilers do not cover Tokio worker threads or browser child processes. Massif is highly perturbing and remains diagnostic evidence, especially for sandboxed multi-process browsers.

### Binary size

Use [cargo-bloat](https://github.com/RazrFalcon/cargo-bloat) to explain contributions to a linked executable's size by crate or function. Its symbol attribution is diagnostic and approximate; record the actual artifact size separately.

The optional production `yosoi` CLI binary is enabled by the `cli` feature.
`cargo-bloat` is not installed by `scripts/bootstrap.sh` or enforced in CI.
Pin and install it before collecting binary-size evidence. For example:

```bash
cargo bloat --release -p yosoi --features cli --bin yosoi --crates
cargo bloat --release -p yosoi --features cli --bin yosoi -n 20
cargo bloat --release -p yosoi --features cli --bin yosoi --crates --message-format json
```

Binary-size comparisons must use the same target triple, Rust version, Cargo profile, features, linker, and linker flags.

### GPU and other accelerators

Use API- and vendor-specific tooling for accelerator measurements. Examples include `wgpu` timestamp queries for GPU execution, NVIDIA Nsight, AMD `rocprof`, and RenderDoc. Relevant metrics may include kernel or pass time, device-memory usage, transfer volume, occupancy, bandwidth, utilization, and power.

Host wall-clock time and GPU execution time answer different questions. Utilization and device-memory sampling can miss short-lived peaks, so reports must state the collection method and sampling interval. Accelerator results are comparable only when the device, driver, runtime, API backend, capabilities, and power or clock configuration are recorded.

## Benchmark fixture contract

A committed benchmark fixture must eventually identify:

- a stable fixture name and content digest;
- the operation under measurement and what setup is excluded;
- a meaningful workload size and unit, such as input bytes, records, nodes, or requests;
- warm- or cold-cache expectations and iteration rules;
- required CPU, memory, accelerator, disk, and network capabilities;
- required and optional measurement classes;
- provenance, normalization, and sensitivity information; and
- determinism requirements or explicitly documented sources of variance.

Fixture inputs must be fixed for comparisons. Secrets, credentials, private captures, and sensitive URLs are prohibited. Alpha-derived fixtures may record an external source revision, content digest, acquisition date, and transformation notes, but must not depend on Alpha module names, source paths, classes, or internal architecture.

Do not finalize a serialized fixture metadata schema until the first real benchmark supplies its concrete requirements.

## Environment metadata

Every retained benchmark result must identify enough context to decide whether comparison is valid:

- repository revision and fixture digest;
- benchmark and measurement-tool versions;
- Rust version, target triple, profile, features, and relevant compiler flags;
- operating system, kernel, and architecture;
- CPU model and available core topology;
- installed memory;
- GPU or accelerator model, driver, runtime, backend, and device memory when used; and
- relevant power, frequency, container, virtual-machine, disk, cache, and network conditions.

A result without fixed inputs and environment metadata is exploratory evidence, not a performance trend. Browser results additionally record browser version/flags, headless or headful mode, viewport/device scale, GPU/backend/driver/display state, browser/context/tab/in-flight matrix, warm-up and recycle policy, cgroup mode, and process-tree collection interval. GPU utilization and memory are vendor-specific optional evidence and must never be presented as portable metrics.

## Comparison policy

Run different measurement classes separately. Timing instrumentation, allocation tracking, Valgrind simulation, hardware counters, and GPU profiling can perturb one another.

Prefer wall-clock measurements for user-perceived latency, Gungraun metrics for stable CI regression detection, `perf` for hardware investigation, `cargo-bloat` for executable-size attribution, and accelerator-native tools for device behavior. Retained local results are grouped under `benchmarks/results/by-change/jj/<change-id>/` or the Git-only commit fallback. Start a new JJ change before measuring a code modification; the stable change ID groups measurement classes, while each baseline records the exact source snapshot commit. Capture and browser orchestrator reruns move the previous successful result into a
`history/<destination-name>/` directory beside the destination before publishing the latest result. The
current dashboard reads only the latest result from each class; it does not pool
reruns into a trend. Failed publication restores the previous result. Standalone browser
profile and soak diagnostics retain their existing publication behavior. Compare results only when fixture digests, toolchain, target, profile, features, and relevant environment controls agree.

Store or gate historical results only after the workload and environment are controlled well enough for the claimed comparison.

Rendered-DOM locator measurements use the canonical `yosoi.rendered-dom.v1`
fixture and keep parsing, evaluation of a pre-parsed document, and
parse-plus-evaluation as separately named Criterion cases. Document and plan
setup stays outside each operation. The optional advanced WCAG case reads the
offline materializer's normalized DOM output from the caller-provided
`YOSOI_DOCUMENT_LOCATOR_ADVANCED_DIR`; the benchmark never normalizes raw CDP
data or invokes a browser. Treat timings as uncollected until the representation
and locator results pass their correctness and independent-reference checks.
