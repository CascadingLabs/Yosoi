# CAS-416: Local Archive certification

Status: implementation-complete candidate for independent verification

Linear: [CAS-416](https://linear.app/cascadinglabs/issue/CAS-416/certify-fresh-process-offline-archive-replay)

## Plain English

One process can make a real request, archive its evidence and normalized
Documents, and exit. Another process can reopen only typed Archive references,
recover locator and Contract results, or rerun the same offline
evaluation without another request or browser.

The decision is **go for the local Archive behavior on the certified Unix
filesystem boundary**. This is not a new browser-version promotion: the browser
exercise used the installed regular Chromium rollback comparison, while the
repository-wide production browser identity remains the separately certified
Chrome 153 tuple in [`chromium-cdp-baseline.md`](../chromium-cdp-baseline.md).

## Certified source and format

| Identity | Certified value |
| --- | --- |
| JJ change | `lqntytvkmtvq` |
| Behavior/evidence snapshot | `23b975a0833d` |
| Reviewed Archive parent | `6fedde0cf931` |
| Archive format | `1`, rooted at `.yosoi/archive/v1` |
| Automatic writer | `yosoi-archive` `0.1.0` from Cargo package metadata |
| Record schemas | Policy, Capture, Plan, ContractSchema, Document, RequestRun, EvaluationRun, and LocatorRun schema `1`; ContractRun schema `2` |
| Platform | Linux x86-64, kernel `7.2.5-3-omarchy` |
| Filesystem | btrfs, 4096-byte block size |
| Toolchain | Rust `1.98.0` (`88d9e12ae`), Cargo `1.98.0` |

ContractRun schema 2 adds the embedded ContractSchema snapshot used by typed
`values()` recovery. Schema 1 is rejected as migration-required before value
decoding; Archive format 1 and every other record schema remain unchanged.
The behavior snapshot includes this SDK cleanup and its final serial validation;
later changes are limited to certification, Linear, and JJ bookkeeping.

## Browser evidence identity

| Identity | Observed value |
| --- | --- |
| Distribution | regular Arch Linux `chromium` package, not Chrome for Testing |
| Package | `chromium 152.0.7977.82-1` |
| Executable | `/usr/bin/chromium` |
| Executable SHA-256 | `78f94ee05d5d6fd1bd8239b9700d3cf54d540911febad4c7cea01080273943f9` |
| Chromiumoxide | vendored `0.9.1` with the repository patch queue |
| Generated CDP | `chromiumoxide_cdp 0.10.0-yosoi.m153.1`, schema `r1681091` |
| Headful isolation | Xvfb `1920x1080x24`, executable SHA-256 `567a9b39284e303522fdc178059fe60d0e9917b811bd5066fb63260fd198a97c` |

Chromium 152 is the documented rollback/comparison executable in the browser
baseline. Its successful Archive exercise proves the Archive integration, not a
new security or production-browser certification. Chrome 153 remains the
production tuple; CAS-416 does not weaken that decision.

## Certified user journeys

### Request writer to targetless reader

The writer performs one Direct HTTP request and publishes, in order:

1. authored Policy;
2. exact CaptureBundle metadata and retained payloads;
3. normalized Document bytes;
4. RequestRunRecord.

It exits after writing the serialized reference. A separate reader receives no
request target, client, executor, browser context, or cancellation token. It
reopens RequestRun, Capture, Policy, and Document and locates against the
archived Document offline.

### Browser writer to browser-free reader

A real regular Chromium writer navigates a loopback page and requests the
response Document, rendered DOM, and accessibility tree. It archives the
Capture before projection, then archives all three normalized Documents and
exits. A separate reader receives no target and launches no browser. It reopens
all values and verifies that DOM and accessibility Document bytes are distinct
from their raw Capture artifacts.

The same source revision also passed a regular-Chromium headless capture and an
isolated-Xvfb headful capture with typed cleanup evidence.

### Stored results and offline equality

LocatorRunRecord persists the exact LocateOutcome, including values, order,
coordinates, lineage, completeness, and terminal state. The golden result
reopens `author → John Doe`.

ContractRunRecord persists a code-free, schema-checked representation of validated
String and USD Money fields, required/optional/many cardinality, candidate
evidence, record issues, extraction diagnostics, and rejection states. One
reader path uses no compiled Contract type. A second offline reader explicitly
reruns locate/extract/validate with the matching Contract and proves equality
with the stored LocatorRun and ContractRun outcomes. `ContractRunRecord::values`
checks the embedded and compiled ContractSchema identities before restoring the
Rust values; callers do not handle a codec or separately pass a schema.

## Serial validation evidence

All expensive commands used one Cargo build job and ran serially.

```text
CARGO_BUILD_JOBS=1 cargo test -p yosoi-archive -- --test-threads=1
CARGO_BUILD_JOBS=1 cargo test -p yosoi --test archived_request --test archived_request_process -- --test-threads=1
CARGO_BUILD_JOBS=1 cargo test -p yosoi --test archived_evaluation_results -- --test-threads=1
CARGO_BUILD_JOBS=1 cargo test -p yosoi --test contracts --test contracts_pipeline --test contracts_pipeline_architecture -- --test-threads=1
CARGO_BUILD_JOBS=1 cargo test -p yosoi --test request_architecture -- --test-threads=1
CARGO_BUILD_JOBS=1 cargo clippy -p yosoi-archive -p yosoi --all-targets -- -D warnings
cargo deny check
CARGO_BUILD_JOBS=1 cargo test -p yosoi --features browser --test policy_capture_browser sdk_browser_capture_headless_finalizes_policy_evidence_and_cleanup -- --exact --test-threads=1 --nocapture
CARGO_BUILD_JOBS=1 cargo test -p yosoi --features browser --test policy_capture_browser archived_browser_request_crosses_process_boundary_with_dom_and_ax -- --exact --test-threads=1 --nocapture
xvfb-run -a -s '-screen 0 1920x1080x24' env CARGO_BUILD_JOBS=1 cargo test -p yosoi --features browser --test policy_capture_browser sdk_browser_capture_headful_finalizes_policy_evidence_and_cleanup -- --exact --test-threads=1 --nocapture
```

Results:

- complete `yosoi-archive` suite passed, including subprocess Capture,
  EvaluationRun, LocatorRun, and ContractRun coverage;
- request writer/reader, ordinary-send isolation, typed publication failure,
  result writer/code-free reader/offline replay reader, and browser
  writer/reader process tests passed;
- existing Contract and Extractor architecture/behavior tests passed;
- warnings-denied all-target Clippy passed;
- cargo-deny advisories, bans, licenses, and sources passed; existing duplicate-version findings remained warnings;
- every changed Rust file was formatted directly and `git diff --check` passed;
- the public Direct HTTP example made a real `https://example.com` request and
  reopened a 559-byte SourceHtml Document;
- the public result example made a real HTTPS request and archived/reopened its
  LocatorRun and ContractRun terminal states.

## Bounds and storage observations

| Bound | Value |
| --- | --- |
| JSON record | 16 MiB |
| Capture retained payloads | 4,096 |
| Capture materialization | 256 MiB |
| One archived Document | 256 MiB |
| Request attempts | 3 |
| EvaluationRun Documents | 64 |

The limits are safety ceilings, not recommended working-set sizes or SLAs.
Current reads materialize one bounded Capture or Document in memory.

One live Direct HTTP request Archive occupied 11,887 bytes on this btrfs host.
A repeated live result demonstration occupied 25,120 bytes across 18 immutable
records. These are descriptive fixtures, not performance or storage targets.

## Integrity and failure evidence

The suite covers:

- automatic writer provenance and independently versioned record schemas;
- wrong format, kind, key, future schema, malformed value, and record-size
  rejection before domain decoding;
- no-follow private paths, permissions, non-regular files, and no-clobber
  publication;
- same-key Capture idempotence and immutable conflicts;
- missing, shortened, and same-length digest-corrupt payloads;
- payload-first/record-last publication and non-cancellable rename/sync critical
  sections;
- typed partial-progress receipts when Document publication fails after Policy
  and Capture commit;
- Policy/attempt ordering, authorship, document selection, termination, artifact
  family, Document class, browser epoch, and referenced-record agreement;
- Contract schema/cardinality/value-type, candidate-evidence, issue-evidence,
  region, terminal-state, and LocatorRun provenance checks on write and read;
- redacted RequestRun, LocatorRun, and ContractRun Debug output.

## Explicitly deferred

- SQLite, Turso, catalogs, indexing, search, tags, and general queries;
- S3, MinIO, remote providers, replication, and data-lake operations;
- automatic acquisition replay, workers, queues, and schedules;
- mandatory content-addressing, deduplication, compression, packing,
  compaction, and garbage collection;
- whole-root scanning, export/import, repair, retention, authorization, and
  CAS-415's optional non-mutating verifier;
- arbitrary JSON Contract values. The first archived value vocabulary is deliberately
  closed to String and USD Money; new value types require explicit versioned
  support.

## Known limitations

- Workspace-wide `cargo fmt --all --check` cannot resolve the nested vendored
  Chromiumoxide manifest from this JJ workspace because Cargo points it at the
  original checkout's workspace root. No source-format failure was observed;
  changed files were checked directly with rustfmt instead.
- Payload-first failures can leave unreferenced private payloads. They remain
  invisible without a committed record; garbage collection is deferred.
- Failed record staging writes may leave invisible staging files for a future
  verifier/cleanup workflow.
- Same-owner mutation inside the private Archive tree is outside the threat
  model, but reads detect structural, length, digest, schema, and referential
  corruption.
- The code-free result reader shares a test executable with the writer harness,
  but its inspection path uses only ContractRunRecord and the `archived::*` views.
  Recovering application values is the separate typed `values()` path.
- Browser Archive behavior was exercised with regular Chromium 152 because the
  exact Chrome 153 production executable was not installed on this host. No
  browser baseline was changed or inferred from that run.

## Decision

The minimal local Archive is ready for independent verification and Andrew's
single-pass Final Boss review once the stacked CAS-474 result revision is
accepted. CAS-415 is useful future integrity work but is not a release blocker.
