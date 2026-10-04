# CAS-307 benchmark suite

## Scope and fixture contract

`benchmarks/fixtures/web-capture/v1/manifest.json` is the versioned, public-synthetic corpus owned by the repository-wide `yosoi-benchmarks` workspace member. It records exact encoded/uncompressed sizes and SHA-256 digests. Contract tests verify every committed byte and the discovery matrix. No benchmark uses a public URL. Fixture reads, runtime construction, server startup, and fixed identity construction are setup, not measured work.

## Criterion groups

Run `cargo bench -p yosoi-benchmarks --bench criterion_capture`. The top-level benchmark package can compose public APIs from any workspace crate and reports these stable groups:

- `sha256_only`: digest-only controls, encoded bytes;
- `yosoi_consume_response_body_pipeline`: the public `execute_direct_http_at` → `consume_response_body` body path for identity, gzip, Brotli, zlib-wrapped `deflate`, high-ratio, and representation-truncated responses. Criterion `iter_custom` creates exactly one fresh `PendingDirectHttpResponse` immediately before each timer, consumes it exactly once, and accumulates only consumption time. The truncated case serves the complete 32,768-byte representation and retains its first 4,096 bytes because of the configured representation limit;
- `source_classification_character_decode`: public validated binding plus `classify_and_decode`, with retained body, source artifact, decoded identity, and response facts preconstructed. It covers the size/format matrix, JS shell, declaration/sniff/unsupported/malformed inputs, UTF-8/windows-1252/UTF-16, complete/truncated bodies, and bounded Unicode output. Throughput is retained representation bytes;
- `capture_finalization_bundle`: `AcquisitionLifecycle::finalize` only. `iter_batched` constructs a stopped lifecycle and valid input outside timing. The current canonical case retains exactly 11 payload bytes in two elements;
- `canonical_web_capture_wire`: canonical serialize and deserialize, with capture construction excluded;
- `local_raw_wreq_construct_request_and_exact_body_consumption`: construct-per-operation raw client with no proxy, redirects, referer, or automatic gzip/Brotli/deflate/zstd decoding, the production timeout, and exact size/SHA-256 checks every iteration;
- `full_capture_direct_http_including_hardened_client_construction`: same medium HTML body, headers, connection-close behavior, runtime warmth, proxy and redirect policy as raw. Its name deliberately states that the public full path constructs its hardened client. A numeric difference must **not** be called pure Yosoi overhead; and
- `full_capture_redirect_chain`: manifest-declared one-, two-, and three-hop successes at their exact limits plus three-hop failure at limit two. Before each case is registered, one untimed capture asserts its exact ordered request paths, count, outcome, and redirect/hop-limit evidence. Logging is then disabled so timed iterations retain only a constant-space atomic request counter. One logical capture is `Throughput::Elements(1)` and the reusable loopback server is joined.

All outputs cross `black_box`. Loopback responses use `Connection: close`, so connection-pool reuse does not distinguish raw and full cases. Server tasks are stopped and joined.

## Baseline and measurement classes

`scripts/benchmarks/run-cas-307-benchmarks.sh [output-directory]` builds a fresh sibling temporary directory, runs every group (`1 s` warm-up, `2 s` measurement, `10` samples), validates required output and estimates, and only then atomically replaces the destination (restoring its backup if replacement fails). It saves console output and complete `target/criterion` estimates and mechanically embeds them in the report. It records the immutable `source_snapshot_commit` and stable `jj_change_id` separately, fixture digest, toolchain/target/profile/features/flags, OS/kernel/architecture, logical CPUs, cores per socket, sockets, CPU model, installed memory, virtualization availability/value, container detection, power/frequency status, and explicit cache/network controls without environment dumps or identifying host data. Generated result files can rewrite JJ's current working-copy commit after measurement; `source_snapshot_commit` identifies the code and fixtures actually measured and is not expected to equal that post-publication commit. Estimate paths are published-root-relative (`criterion-raw/...`) and validated using those eventual publication semantics before the atomic rename.

The repository-wide entry points are:

```bash
cargo xtask benchmark check
cargo xtask benchmark criterion
cargo xtask benchmark deterministic
cargo xtask benchmark allocations
cargo xtask benchmark process
cargo xtask benchmark heap
cargo xtask benchmark all
```

`deterministic` publishes Gungraun/Callgrind instruction and modeled-cache summaries plus raw profiles. `allocations` publishes Divan allocation operation counts, allocated bytes, and maximum simultaneously live allocation count/bytes for synchronous stages; its timing is instrumentation-perturbed. `process` executes full, compressed, redirect, and truncated loopback workloads in fresh processes and records GNU time peak RSS/user/system/utilization evidence plus `perf stat` counters when host permissions allow them. `heap` runs one fresh process/capture per workload under Massif and retains peak heap, allocator-overhead, and stack bytes separately. Peak RSS, process peak heap, maximum live benchmark-thread allocator bytes, total allocated bytes, and Callgrind memory-access metrics remain separate quantities.

Gungraun 0.19.4 currently fails while reopening its own sanitized DHAT output under Valgrind 3.25.1 on this host. Callgrind remains Gungraun-owned; allocation evidence uses Divan rather than hiding the incompatibility or inferring heap facts from timing.

The raw/full comparison includes Yosoi orchestration beyond wreq; their difference is not a pure framework-overhead subtraction. The workspace uses wreq with default features disabled and only `stream`, `tokio-rt`, and `webpki-roots`; proxy discovery is therefore absent, while the raw benchmark additionally calls `no_proxy`. Allocation count, allocated bytes, peak live heap, peak RSS, hardware instructions, and modeled Callgrind instructions are not inferred from Criterion. Reports say “not collected” unless separately measured. Results under `benchmarks/results/` are exploratory, machine-specific evidence, not thresholds.
