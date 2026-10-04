# CAS-323 Direct HTTP fuzz and property hardening

## Stable property layer

`crates/yosoi-web-capture/tests/property_hardening.rs` runs 128 deterministic property cases per target under the ordinary stable workspace gate. It covers:

- arbitrary Web Capture v1 bytes: accepted values must canonicalize and round-trip;
- arbitrary durable source-representation evidence: accepted values must canonicalize and round-trip;
- bounded arbitrary header/URL text: Content-Encoding, media declaration, and target parsing must be deterministic;
- bounded lifecycle operation sequences: retained counts never exceed admitted counts, byte/deadline ceilings hold, and stopped transitions remain explicit.

Shrinking is bounded to 2,048 iterations. Minimized failures are written to `tests/property-regressions/property_hardening.txt`; reviewed seeds are committed after the underlying defect is fixed.

## LibFuzzer layer

`fuzz/` is a separate nightly Cargo workspace. `libfuzzer-sys` and its unsafe runtime do not enter production crates or the normal stable dependency graph. Targets are loopback/network-free:

| Target | Maximum smoke input | Oracle |
|---|---:|---|
| `wire-and-evidence` | 16 KiB | no crash; successful parses canonicalize and round-trip |
| `http-input-boundaries` | 4 KiB | no crash; parsing is deterministic and fail closed |
| `bounded-lifecycle` | 2.5 KiB / 512 operations | accounting, deadline, and byte invariants always hold |

Run all smoke targets with 2,000 executions each:

```bash
cargo xtask fuzz
```

Long campaigns are explicit local operations documented in `fuzz/README.md`. Generated corpus and crash directories are ignored. A real minimized failure is promoted into a reviewed deterministic regression fixture/test before the issue closes.

## Dependency boundary

`proptest = 1.11.0` is a dev-only workspace dependency with defaults disabled and only `std`; it provides deterministic structured generation and shrinking on Rust 1.85+, below the repository MSRV. `cargo-fuzz = 0.13.1` is an external developer command. `libfuzzer-sys = 0.4.13` exists only in the independent `fuzz/` workspace and links LLVM libFuzzer/AddressSanitizer; its permissive MIT/Apache-2.0 and NCSA licensing and unsafe runtime do not enter production artifacts or the stable workspace dependency graph.

## Deferred decoder target

Content-decoding mutation is already covered by deterministic malformed gzip/Brotli/zlib, chunk-split, high-expansion, exact-limit, one-over, disconnect, and truncation tests. The production decoder currently consumes a provider-owned `wreq::Response`; constructing a parallel fuzz-only decoder would test different code. A byte-stream decompression fuzz target remains deferred until the decoder has a provider-independent input boundary demonstrated by another producer.

## CAS-325 property ownership

Stable arbitrary Web Capture wire/source-evidence and bounded lifecycle properties run from `crates/yosoi-web-capture/tests/property_hardening.rs`. Only HTTP header and content-coding properties remain in `crates/yosoi-web-capture-direct-http/tests/property_hardening.rs`. Fuzz targets import concrete HTTP parsing from the producer crate and provider-neutral models from the foundation; this follows `direct-http -> foundation -> types` without a compatibility reexport.
