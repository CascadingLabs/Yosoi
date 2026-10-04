# CAS-373 build-time and release-artifact-size evidence

`scripts/browser/run-cas-373-build-size-evidence.sh` collects a small, reproducible build evidence bundle for paired CAS-377 old-CDP baseline and CAS-373 candidate runs. It does not benchmark runtime behavior and does not certify a browser or container.

## What is measured

The harness runs one exact Cargo command twice:

```text
cargo build --locked --offline --release --jobs 1 --target <triple> --target-dir <disposable-dir> --package yosoi-benchmarks --no-default-features --bin profile_capture --bin profile_browser --verbose --verbose
```

The first invocation uses an empty target directory and is the clean build. The second is the immediate no-op/incremental build using the same source and target directory. The two elapsed wall-clock measurements are comparable only on the same machine under similar load.

`profile_capture` and `profile_browser` are **benchmark executable proxies**. This repository has no production executable, so their byte sizes and hashes must not be described as production binary size. They are useful only as stable, buildable proxies for comparing the old-CDP baseline with the candidate.

The result records:

- source JJ commit, change, parent, status, and a deterministic source-tree SHA-256 over JJ's non-ignored revision files, including eligible untracked files;
- `Cargo.lock` SHA-256, Cargo and Rust compiler versions, target triple/configuration, release profile, selected package, feature mode, job count, locked/offline mode, and linker-related environment;
- verbose Cargo logs, which preserve the effective compiler and linker command lines;
- clean and immediate no-op/incremental wall time in nanoseconds; and
- each proxy artifact's exact byte size and SHA-256.

The source-tree digest includes each relative path, file kind, executable bit, and file-content or symlink-target SHA-256 in sorted path order. It is computed before the clean build and again after the no-op build; a change aborts publication. Raw source content and diffs are never retained because they may contain secrets. JJ status is retained as the requested human-readable cleanliness context.

## Paired use

Run the harness once against the CAS-377 old-CDP baseline checkout and once against the CAS-373 candidate checkout. `--source-root` allows the candidate's audited harness to measure either checkout, so the old baseline does not need to be modified to contain a copy. Supply fresh destinations outside either source tree. A target directory may be caller-selected, but it must not exist and is deleted by the harness; otherwise the harness uses `mktemp`.

```bash
mkdir -p /tmp/cas-373-comparison

/path/to/cas-373-candidate/scripts/browser/run-cas-373-build-size-evidence.sh \
  /tmp/cas-373-comparison/old-cdp \
  --source-root /path/to/old-baseline \
  --target-dir /tmp/cas-373-old-target

/path/to/cas-373-candidate/scripts/browser/run-cas-373-build-size-evidence.sh \
  /tmp/cas-373-comparison/m153-candidate \
  --source-root /path/to/cas-373-candidate \
  --target-dir /tmp/cas-373-m153-target
```

Use the same explicit `--target <triple>` on both runs when comparing a non-host target. When omitted, the script resolves the compiler host triple once and passes it explicitly to both builds.

Compare `timings.tsv` and `artifacts.tsv`, but retain the complete directories. A useful report names both source identities and source-tree hashes, toolchains, target, flags, machine, and observed load. Do not combine results produced with different feature sets, profiles, target triples, toolchains, linker flags, or materially different system pressure.

## Publication and cleanup guarantees

The destination's parent must already exist and the destination itself must not exist. Evidence is assembled in a sibling staging directory and moved with an atomic, no-clobber, same-filesystem rename only after both builds and artifact checks succeed. A failed, interrupted, or destination-raced run publishes nothing from the harness.

The harness creates and removes only its exact staging and disposable target directories. It never runs `cargo clean`, touches a shared Cargo target directory, replaces an existing result, or edits either checkout.

## Resource caveats

This is bounded to one Cargo job (`--jobs 1` and `CARGO_BUILD_JOBS=1`) and performs no tests, benchmarks, Clippy run, browser launch, or network access. A clean Rust release build can still be CPU- and memory-intensive. The bundle includes preflight `free -h` and process-table snapshots; the process snapshot retains `comm` (the executable basename), never command arguments. `RSS` is resident physical memory, `%MEM` is its share of physical RAM, and `VSZ` is virtual address space rather than RAM usage.

Inspect system pressure before each run and keep the paired runs serial. Stop the build if aggregate compiler/linker RSS, swap pressure, or workstation responsiveness becomes unsafe. Process visibility may be incomplete inside a sandbox or PID namespace, so host-visible monitoring takes precedence. The preflight snapshot describes only the start of the run; it is not peak-resource evidence.
