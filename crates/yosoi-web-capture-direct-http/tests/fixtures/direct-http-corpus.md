# CAS-306 direct HTTP corpus inventory

All integration traffic uses `tests/support/direct_http_fixture.rs`, which binds and validates
IPv4 loopback endpoints and validates absolute redirect destinations. The fixture records ordered
raw request lines plus parsed method/path, accepts complete raw malformed responses or raw heads,
provides durable pre-head/per-chunk/final-connection coordination, cancels blocked connections at
shutdown, and joins the listener and every accepted connection task.

## Matrix

| CAS-306 behavior | Named verification |
|---|---|
| HTML, JavaScript shell, XML/Atom/XHTML, JSON/problem JSON, plain text, unsupported binary/CSV, BOM/in-band charset, empty and 404/500 bodies | `direct_http_corpus::{public_orchestrator_corpus_preserves_independently_fixed_source_evidence,javascript_shell_stays_source_only_without_browser_artifacts}` |
| Duplicate/malformed Content-Type remains observable | `direct_http_corpus::raw_duplicate_and_malformed_content_type_observations_are_not_normalized` |
| identity/gzip/Brotli/zlib/stacked coding and adversarial splits | `direct_http_corpus_b::fixed_content_codings_decode_to_independent_representation` |
| exact and plus-one encoded/representation limits, including high expansion | `direct_http_corpus_b::encoded_and_representation_limits_have_exact_boundaries` |
| malformed/unsupported coding before/after output | `direct_http_corpus_b::malformed_and_unsupported_codings_are_terminal_values_without_a_bundle_leak`; `direct_http_outcome_corpus::lifecycle::malformed_and_unsupported_coding_preserve_before_after_distinction` |
| HTTPS rejection and redaction | `direct_http_corpus_b::fixture_https_exercises_public_untrusted_certificate_failure_path`; `direct_http_redirect_corpus::transport::untrusted_loopback_https_is_a_redacted_provider_failure` |
| 301/302/303/307/308 continuous traversal, every wire request exactly GET | `direct_http_redirect_corpus::redirects::all_follow_statuses_form_one_continuous_chain_and_resolve_references` |
| disabled/non-follow statuses, references, fragments/query, cross-origin tuple update | `redirects::{disabled_and_non_follow_statuses_are_final_captures,fragment_loop_is_rejected_but_changed_query_is_allowed,absolute_cross_origin_updates_final_url_and_tuple_origin}` |
| exact hop limit and plus one; malformed/missing/credential/scheme/loop refusal | `redirects::{redirect_rejections_and_exact_hop_boundary_preserve_non_lossy_evidence,fragment_loop_is_rejected_but_changed_query_is_allowed}` |
| redirect error kind, structured category/code, stable summary, `into_parts`, partial evidence, redaction | `redirects::redirect_rejections_and_exact_hop_boundary_preserve_non_lossy_evidence` |
| one absolute deadline across hops | `redirects::one_absolute_deadline_applies_after_a_hop` |
| malformed raw HTTP maps Protocol | `transport::malformed_raw_http_is_a_protocol_failure` |
| cancellation after exactly one hop maps Cancelled with exact partial resolution | `transport::cancellation_after_exactly_one_hop_is_cancelled_with_partial_resolution` |
| provider failure after a hop, pre-cancel, connection refusal | `transport::{provider_failure_after_hop_keeps_partial_chain_and_current_url,pre_cancelled_and_connection_refusal_have_stable_terminal_evidence}` |
| empty/disconnect before and after bytes; exact lifecycle accounting | `direct_http_outcome_corpus::lifecycle::complete_empty_and_disconnect_before_or_after_output_map_exactly` |
| encoded/representation terminal evidence and byte/event accounting | `lifecycle::representation_and_content_coded_limits_have_exact_accounting` |
| cancellation before head and after an exact chunk, no extra retained reads, all fixture children joined | `lifecycle::cancellation_before_head_and_after_output_is_coordinated_and_quiescent` |
| retain/report versus fail-attempt, no fabricated decoded artifact/bundle | `policy_replay::{retain_and_report_keeps_source_facts_but_never_fabricates_decoded_output,fail_attempt_preserves_evidence_and_publishes_no_bundle}` |
| non-2xx independence and requested/not-requested network state | `policy_replay::non_2xx_is_independent_and_network_request_state_is_exact` |
| replay exactness and constructible wrong-size/wrong-digest metadata | `policy_replay::replay_is_exact_and_rejects_wrong_length_or_digest` |
| deterministic timestamps and invalid ordering | `policy_replay::injected_timestamps_are_exact_and_invalid_orders_publish_no_bundle` |

## Intentional lower-layer coverage and genuine public gaps

* Same-origin redirect refusal is covered by crate test
  `direct_http::redirect_protocol_tests::same_origin_rejects_cross_origin_redirect_without_requesting_it`.
  The public orchestrator intentionally resolves `AllowHttpAndHttps`; CAS-306 has no target-policy
  field. No production seam is added.
* Successful pinned HTTPS remains crate-level because the public API has no trust-root injection.
* `RetainedBody::from_artifact_payload` wrong size and digest are publicly constructible and tested
  above. `BytesUnavailable` cannot be paired with a `SourceArtifact` through public bundle
  constructors: unavailable families contain no artifact and there is no mutation API. The branch
  remains defensive validation, not a fabricated integration state.
* Source representation facts are supplemental to `DirectHttpCapture` and intentionally absent
  from `WebCaptureWire`; a bundle-only round trip cannot verify those facts.

No other CAS-306 matrix gap remains.
