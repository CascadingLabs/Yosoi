# Direct HTTP fuzzing

This independent nightly workspace keeps libFuzzer dependencies and unsafe runtime implementation outside production crates and the normal stable workspace.

## Targets

- `wire-and-evidence`: arbitrary Web Capture v1 and source-representation evidence bytes; successful parses must canonicalize and round-trip.
- `http-input-boundaries`: arbitrary bounded header/URL text; Content-Encoding, media declaration, and target validation must remain deterministic and fail closed.
- `bounded-lifecycle`: bounded structured event streams; retained/admitted accounting and deadline/byte ceilings must remain invariant.

No target performs network I/O. Source/body decompression behavior remains covered by deterministic streaming and expansion-limit tests; a future byte-stream decoder fuzz target should call the production decoder only after it has a provider-independent input boundary.

Run the deterministic smoke profile:

```bash
scripts/fuzz/run-cas-323-fuzz-smoke.sh
```

Run a longer local campaign:

```bash
cd fuzz
cargo +nightly fuzz run wire-and-evidence -- -max_len=16384 -max_total_time=3600
cargo +nightly fuzz run http-input-boundaries -- -max_len=4096 -max_total_time=3600
cargo +nightly fuzz run bounded-lifecycle -- -max_len=2560 -max_total_time=3600
```

`fuzz/corpus/` and `fuzz/artifacts/` are Git-ignored. When a crash represents a real defect, minimize it, add a deterministic regression test or copy the minimized input into a reviewed tracked regression-fixture directory, then retain it permanently.
