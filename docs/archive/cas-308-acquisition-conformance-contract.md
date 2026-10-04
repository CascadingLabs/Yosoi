# CAS-308 minimum acquisition producer contract

This is a normative scenario contract, not a Rust provider trait. A producer MAY use any transport/runtime but MUST satisfy every applicable observable invariant.

| Scenario / requirement | Normative minimum | Direct HTTP evidence |
|---|---|---|
| identity | Allocate one stable `CaptureId`; request, receipt, artifacts and references MUST share its activity | `bounded_lifecycle::finalization::final_capture_preserves_identity_and_accounting`; `acquisition_conformance::provider_neutral_core_enforces_deadline_and_exact_accounting` |
| resolved request | Validate target, strategy, requested families, limits and schemas before acquisition | `direct_http_spec::valid_spec_exposes_all_resolved_decisions`; wrong-strategy/family cases in same target |
| monotonic time | Event offsets MUST never decrease; terminal offset MUST equal observed offset | `bounded_lifecycle::admission::lower_offsets_are_non_monotonic_and_equal_offsets_are_allowed`; finalization terminal tests |
| deadline/cancel | Deadline wins at or beyond its exact boundary; earlier caller cancellation is classified caller-interrupted | `bounded_lifecycle::admission::offers_before_deadline_admit_while_at_and_after_deadline_do_not`; `direct_http_transport` cancellation/deadline tests |
| accounting | Admission is atomic. Admitted, retained and measured dropped event/byte counts MUST reconcile exactly, including partial final events | `bounded_lifecycle::admission::exact_event_boundary_and_simultaneous_precedence_preserve_partial_byte_facts`; byte-boundary test; remediation sink tests |
| complete | Successful terminal completion MUST retain requested evidence and truthful capabilities | `direct_http_outcome_corpus::lifecycle::complete_capture_has_truthful_identity_accounting_and_capabilities` |
| truncated | A hard limit MUST publish partial/truncated metadata with exact retained extent/digest | `direct_http_outcome_corpus::lifecycle::truncated_capture_preserves_exact_partial_evidence` |
| unavailable/failure | Missing bytes MUST be unavailable, never empty retained evidence; errors MUST be typed and safe | `direct_http_outcome_corpus::lifecycle::sink_failure_is_unavailable`; `response_body_stream::failures::*` |
| redirects | Resolution MUST preserve ordered hops and enforce the configured exact hop boundary | `direct_http_redirect_corpus::redirects::*` |
| capability truth | Produced/requested/unavailable families MUST match declared provider capability | `web_artifacts::capabilities::*`; Direct HTTP outcome lifecycle tests |
| source vs derived | HTTP source is response representation; script shell MUST NOT be called rendered DOM | `source_representation::identity::*`; `source_pipeline::decoding::*small_js_shell*` |
| provenance/schema/lineage | Every artifact MUST have declared schema, producer provenance and typed derivation lineage | `bounded_lifecycle::finalization::schema_*`; `web_artifacts::metadata::*`; source decoded-lineage tests |
| atomic publication | Producer MUST validate capture and every retained/truncated payload before exposing a bundle; bundle is last | `capture_bundle::missing_payload_fails_closed`; lifecycle finalization tests |
| durable handoff | Current pre-release v1 capture JSON plus exact `(WebArtifactRef, bytes)` pairs MUST reconstruct offline; altered bytes MUST fail digest/size validation. **WARNING:** this is payload-integrity conformance only until source representation facts receive a typed durable replay/derived-evidence artifact. | `acquisition_conformance::durable_handoff_reconstructs_exact_bundle_offline_and_rejects_tampering` |
| fixture discipline | Network tests MUST use the shared loopback fixture/corpus, exact bytes and deterministic synchronization; no public network | Direct HTTP corpus, redirect corpus, benchmark contract |

A producer that cannot produce a requested family MUST report capability/outcome truthfully rather than fabricate it. Source artifacts are acquired facts; decoded source/rendered DOM/accessibility are distinct derived/acquired families. Errors MUST not include secret header/cookie/body values. Publication is bundle-last: metadata alone may be serialized, but a payload-bearing result is not valid until `CaptureBundleBuilder::finalize` succeeds.

## CAS-325 ownership and test placement

The normative conformance contract belongs to `yosoi-web-capture`, independently of any provider. Its tests own `BoundedAcquisitionLifecycle`, canonical `WebCaptureWire` plus `CaptureBundle` subprocess handoff and tamper rejection, architecture direction, source/wire properties, and browser contracts. `yosoi-web-capture-direct-http` additionally runs producer conformance and HTTP transport/header/coding/redirect cases. There is deliberately no provider trait and no reverse compatibility reexport. The pre-release import migration for Direct HTTP symbols is `yosoi_web_capture` to `yosoi_web_capture_direct_http`.
