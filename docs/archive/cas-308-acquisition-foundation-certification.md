# CAS-308 acquisition foundation certification

## Result

**Conformant after a dependency-direction remediation.** Before CAS-308, `AcquisitionLifecycle` owned `ResolvedDirectHttpCaptureSpec`; it was therefore not a browser-reusable, provider-neutral lifecycle. CAS-308 does not disguise that adapter as shared. It extracts `BoundedAcquisitionLifecycle`, a concrete state machine containing only `CaptureId`, `ObservationPolicy`, start time, monotonic offset, termination, and exact event/byte counters. `AcquisitionLifecycle` preserves its public Direct HTTP API and composes/delegates to that core. Direct HTTP schema validation and bundle/capture assembly remain in its finalizer.

## Dependency DAG

| Layer | Physical modules | May depend on |
|---|---|---|
| domain | `yosoi-types`, capture/artifact/observation model | `yosoi-types` |
| bounded foundation | `bounded_acquisition.rs`, `bundle.rs`, `wire.rs` | domain model; no transport |
| Direct HTTP specification | `direct_http_spec.rs` | bounded/domain vocabulary |
| Direct HTTP adapter | `lifecycle.rs`, `lifecycle/finalization.rs` | bounded core plus Direct HTTP spec |
| transport/body/source | `direct_http/**`, `source/**` | adapter/spec and `wreq` where transport requires it |
| orchestration | `direct_http_orchestration/**` | all Direct HTTP layers |
| fixtures/tests/benchmarks | `tests/**`, `benches/**` | production APIs downward only |

`yosoi-types/model → bounded lifecycle + payload bundle + wire → Direct HTTP spec/transport/body/source/orchestrator`.

## HTTP-only inventory

The following are not shared browser foundations: `ResolvedDirectHttpCaptureSpec`, `DirectHttpAcquisition`, redirect policy/hops, HTTP transport/session/impersonation profiles, `wreq::Client`, `wreq::Response`, `PendingDirectHttpResponse`, response headers/status/content coding, `DirectHttpResponseFacts`, body decoding limits, source classification rules, HTTP output schemas, and Direct HTTP artifact/finalization assembly.

## Shared seams and evidence

* `BoundedAcquisitionLifecycle::start/admit/observe_through/stop` supplies identity, deadline precedence, atomic admission, termination and accounting without HTTP types.
* `CaptureBundle::payloads` and `into_parts` expose typed `WebArtifactRef`/exact byte pairs non-lossily. Canonical metadata remains the current pre-release `WebCaptureWire` v1; no bundle/archive format was invented.

> **CAS-324 durability completion:** source declaration, classification, and decoding facts now survive process separation as the typed `SourceRepresentation` derived-evidence artifact. It carries a dedicated schema, producer/version, exact final-source lineage, retained size, and digest; its payload excludes decoded text. Canonical Web Capture v1 metadata plus payload pairs reconstruct and validate it offline.
* `acquisition_conformance::durable_handoff_reconstructs_exact_bundle_offline_and_rejects_tampering` simulates process separation and digest failure.
* The architecture test scans the physical core for forbidden HTTP/wreq types.

## Audit findings/remediation

The original direction was false at the lifecycle boundary and is now explicit composition. Retention rollback, deadline/cancel precedence, counters and public `AcquisitionLifecycle` behavior are preserved. Finalization still validates manifest requests, schemas, timestamps, receipts, relationships and payloads before publication. No provider trait, browser execution, policy engine, extraction, storage or archive was added.

## Evidence

CAS-298–307 contracts, source modules, deterministic fixture service, integration corpus and benchmark baselines were reviewed. Repository-wide results now live under `benchmarks/results/by-change/`, grouped by stable JJ change or Git commit identity; every baseline records the exact source snapshot and all input fixture digests. Criterion, Callgrind, allocations, process RSS/hardware counters, and Massif heap evidence remain exploratory rather than thresholds. Visible stages include body decompression/copying, classification/decoding, canonical JSON/hash work, client construction, and redirect orchestration; CAS-308 makes no optimization claim.

## CAS-325 physical boundary

Certification behavior is owned and executed by the provider-neutral `yosoi-web-capture` foundation. Concrete producer suites may repeat applicable scenarios visibly, but do not replace the foundation's lifecycle, bundle/wire handoff, tamper, source-evidence, architecture, or browser contract tests. The dependency direction is `yosoi-web-capture-direct-http -> yosoi-web-capture -> yosoi-types`.
