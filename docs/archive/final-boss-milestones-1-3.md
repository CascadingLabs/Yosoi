# Final Boss executive review: acquisition milestones 1–3

Status: staged for Andrew's Final Boss review on 2026-09-14. Final Boss is a human-review queue, not a claim that every acceptance gate has passed. Only Andrew moves work to Done or Released.

## Executive decision

Milestones 1–3 are ready for Final Boss review. Milestone 3's core acquisition consolidation is implemented and reviewable; the remaining runtime and benchmark evidence is recorded below for final review rather than treated as hidden completion evidence.

The main architectural result is sound: Yosoi is the supported acquisition product; `yosoi-web-capture` owns canonical acquisition policy, payloads, lifecycle, finalization, receipts, and bundle publication; Direct HTTP owns concrete HTTP protocol and streaming behavior; VoidCrawl owns low-level Chromium operations and resource safety. The deleted `yosoi-web-capture-voidcrawl` adapter has not been recreated.

## Review inventory

| Milestone | Final Boss issues | Executive assessment |
| --- | --- | --- |
| 1 — Current browser acquisition baseline | CAS-352 | Implementation is present and consolidated. Review browser isolation, capacity, cancellation, deadlines, and cleanup together with CAS-363/CAS-371. Current Chromium-host certification remains incomplete. |
| 2 — VoidCrawl consolidation and deduplication | CAS-356, CAS-363 | Adapter crate is deleted; browser ownership is inside Yosoi; VoidCrawl is the low-level engine; source-size enforcement passes. Ready for human review. |
| 3 — Acquisition deduplication and code polish | CAS-366–CAS-372 | Canonical quantities, payload outcomes, attempt lifecycle, terminal accounting, finalization, and both transport migrations are implemented. Ready for Final Boss with disclosed verification follow-ups. |

## What changed in milestone 3

- Canonical acquisition quantities and browser/environment vocabulary now have one owner. Nineteen compatibility aliases and four obsolete converters were removed.
- `AcquiredPayloadOutcome` and canonical retained-source facts replace the Direct HTTP retained-body mirror.
- `BoundedAcquisitionLifecycle`, `AttemptBoundary`, terminal accounting, activity results, timestamp ordering, and final publication are shared without introducing a provider trait hierarchy.
- Direct HTTP feeds the shared lifecycle/finalization path while keeping redirects, headers, content decoding, streaming limits, sink backpressure, and transport errors concrete.
- Browser capture creates its lifecycle at the real attempt boundary, carries the stopped lifecycle through adapter output, and validates exact accounting agreement before publication.
- Independent review found and drove fixes for a fresh-browser-lifecycle bug, excess Direct HTTP finalizer authority, contradictory sink-limit/error precedence, permissive stopped-accounting validation, and zero-duration attempt boundaries.

## Current validation ledger

Exact review context:

- JJ workspace: the single `default` workspace, change `uwpwswpzuxvzsotxkmlqssnzstnlvmnq`.
- Frozen baseline Git commit: `1974ccd3072b1813ad6a9e2d317a12dc76694da8`.
- Frozen baseline archive SHA-256: `37f796d137a171417bfe97c1f742f52700d826f73192a151498335285aee56d8`.
- Current production-Rust source manifest SHA-256: `1cb8f9b8c7e2774c06c660bab9feb023a784c683ad5c01c89431807cffa51faf`.
- Toolchain: Rust/Cargo 1.98.0; Chromium 152.0.7977.82 on x86_64 Arch Linux.

Current post-integration checks:

- `cargo fmt --all`: passed.
- `git diff --check -- ':!vendor/**'`: passed. Vendored license files retain pre-existing CRLF whitespace noise and were excluded from this repository-owned check.
- `cargo check --offline --workspace --all-targets --all-features --jobs 1`: passed in 19.13 seconds, 710,808 KiB peak RSS, zero command swaps.
- `cargo xtask source-size`: passed; all new/changed production sources satisfy the 400-line target, with 24 explicit grandfathered files.
- Direct HTTP default dependency graph: no VoidCrawl or Chromiumoxide entries.
- Compatibility-alias scan: no remaining declarations for the removed browser byte, duration, environment, resource, or accessibility aliases.

Focused suites passed earlier in the same workspace before the last integration corrections: 28 `yosoi-types` tests, 165 Direct HTTP tests, 25 acquisition/benchmark contract tests, 10 browser capture contract tests, 5 document-identity tests, and 14 byte-control tests. The final all-target/all-feature compile proves the corrected tests build, but the post-correction focused runtime rerun was interrupted and its resource-capped relaunch was rejected by the command approval service. Treat those runtime results as prior evidence, not a fresh final pass.

All expensive work was serialized at one Cargo job. The completed capped checks recorded zero swap activity inside their scopes; no validation jobs were run in parallel.

## Findings Andrew should decide in Final Boss

1. **Production LOC increased, by accepted design choice.** The frozen baseline contains 42,530 production Rust lines under the agreed source-shape method; the current tree contains 43,412, an increase of 882 lines (+2.07%). By area: VoidCrawl +2, `yosoi-types` +302, `yosoi-web-capture` +533, Direct HTTP +45. Andrew clarified on 2026-09-14 that “materially less code” is a direction, not a rule. The enforceable result is therefore architectural: duplicate owners and compatibility layers are gone, new invariants are explicit, and the changed-file source-size gate passes.
2. **The current Chromium-host runtime is not fully certified.** A prior browser library run passed 61 of 64 tests and failed three cases: FIFO queue overflow timed out, real shared-session tabs returned `voidcrawl.navigation.failed`, and runtime shutdown hit `ProcessCloseDeadline`. An isolated FIFO rerun hung and was stopped without leaving a test Chromium process. These may reflect the Chromium/controller compatibility work already assigned to milestone 5, but they also touch milestone-1 execution behavior and need an owner decision.
3. **Fresh performance evidence is incomplete.** The frozen baseline/build evidence exists, but the exact-current Criterion, browser soak, peak-RSS comparison, binary-size comparison, and clean/incremental timing matrix were not completed. No performance improvement is claimed.
4. **Cross-transport semantic parity is characterized but not end-to-end certified.** Shared contract and benchmark tests exercise the common aggregate/finalizer model, but there is not yet a single public-path test comparing a real HTTP capture and a real browser capture after removing only documented transport-specific facts.
5. **Final runtime rerun remains due.** The final all-feature compile is green, but the resource-capped post-integration test launch could not be authorized after interruption. Run the focused suites once the approval service is available before calling CAS-372 Done.

## Suggested Final Boss review order

1. Review CAS-352, CAS-363, and CAS-371 together for process/context/tab ownership, isolation, cancellation, deadlines, accounting, and cleanup.
2. Review CAS-367–CAS-370 for canonical type ownership, payload semantics, terminal precedence, and shared all-or-nothing publication.
3. Review the +2.07% source growth as the cost of explicit invariants and focused modules; do not optimize for deletion if it would weaken the design.
4. Rerun the focused HTTP/shared/browser contract suites and the exact-current benchmark/soak matrix.
5. Keep all milestone 1–3 tickets in Final Boss until Andrew completes the human review; only Andrew advances them to Done or Released.

## Outside this review

Milestone 4 is new feature work: managed-profile workflows, completion-driven tab scheduling, browser action plans, download promotion, JavaScript action receipts, and related enhancements. Milestone 5 owns Chromium/CDP modernization and stealth reevaluation. CAS-355 clean-checkout certification and CAS-364 standalone repository/package retirement remain intentionally unmilestoned owner work and do not block staging milestones 1–3 for review.
