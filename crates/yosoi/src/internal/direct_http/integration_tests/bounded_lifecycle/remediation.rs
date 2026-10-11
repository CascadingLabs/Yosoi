use super::support::*;
use crate::internal::direct_http as internal_direct_http;
use std::fs;

use crate::internal::direct_http::{
    AcceptedSourceFormat, AcceptedSourceFormats, ArtifactRequest, BoundedAcquisitionError,
    ByteCount, ByteLimit, CaptureBundleError, CaptureDeadline, CaptureOffset,
    DirectHttpContentLimits, DirectHttpOutputSchemas, DirectHttpRedirectPolicy, EventCount,
    LifecycleError, LifecycleStop, MeasuredCount, ObservationLimits, ObservationPolicy,
    ResolvedDirectHttpCaptureSpec, SettlementPolicy, SourceRetentionPolicy, StagedPayloads,
    UnsupportedSourceFormatBehavior, WebAcquisitionRecordError, WebArtifactFamily,
    WebArtifactManifest, WebArtifactRef, WebArtifactRelationship, WebArtifactRequestSet,
    WebCapture, WebCaptureError, WebCaptureWire,
};
use crate::internal::types::{ActivityId, ArtifactAvailability, Sha256Digest};
use serde_json::{Value, json};

#[derive(Clone, Copy)]
enum ReceiptState {
    Retained,
    Truncated,
    Discarded,
    Unavailable,
}

fn fixture_value() -> Value {
    serde_json::from_slice(
        &fs::read(format!(
            "{}/src/internal/direct_http/integration_tests/fixtures/web-capture/complete-v1.json",
            env!("CARGO_MANIFEST_DIR")
        ))
        .unwrap(),
    )
    .unwrap()
}

fn state_capture(state: ReceiptState) -> WebCapture {
    let mut value = fixture_value();
    let digest = Sha256Digest::digest(b"fir").to_string();
    let artifact = &mut value["capture"]["artifacts"]["results"]["source"]["artifacts"][0];
    match state {
        ReceiptState::Retained => {}
        ReceiptState::Truncated => {
            artifact["extent"] = json!({"status":"truncated","retained_bytes":3,
                "complete_bytes":{"status":"known","value":5}});
            artifact["record"]["availability"] = json!("truncated");
            artifact["record"]["availability_reason"] = json!("capture.byte-limit");
            artifact["record"]["content_digest"] = json!(digest);
        }
        ReceiptState::Discarded => {
            artifact["extent"] = json!({"status":"discarded",
                "observed_bytes":{"status":"known","value":5}});
            artifact["record"]["availability"] = json!("discarded");
            artifact["record"]["availability_reason"] = json!("capture.policy-discarded");
            artifact["record"]["content_digest"] = Value::Null;
        }
        ReceiptState::Unavailable => {
            artifact["extent"] = json!({"status":"unavailable"});
            artifact["record"]["availability"] = json!("unavailable");
            artifact["record"]["availability_reason"] = json!("capture.body-unavailable");
            artifact["record"]["content_digest"] = Value::Null;
        }
    }
    let changed = artifact["record"].clone();
    value["capture"]["acquisition"]["receipt"]["receipt"]["outputs"][1] = changed;
    if !matches!(state, ReceiptState::Retained) {
        value["capture"]["completeness"] = json!("incomplete");
    }
    WebCaptureWire::from_json(&serde_json::to_vec(&value).unwrap()).unwrap()
}

fn unavailable_source_manifest(capture: &WebCapture) -> WebArtifactManifest {
    let mut value = serde_json::to_value(capture.artifacts()).unwrap();
    value["requests"]["source"] = json!("required");
    value["results"]["source"] = json!({
        "status": "unavailable",
        "reason": "capture.deadline"
    });
    serde_json::from_value(value).unwrap()
}

fn finalized_with(
    capture: &WebCapture,
    payloads: StagedPayloads,
) -> Result<internal_direct_http::CaptureBundle, LifecycleError> {
    let (_, lifecycle) = stopped();
    lifecycle.finalize(input(
        capture,
        MeasuredCount::Known(EventCount::new(0)),
        MeasuredCount::Known(ByteCount::new(0)),
        payloads,
    ))
}

#[test]
fn lifecycle_receipt_outputs_truthfully_preserve_all_artifact_availabilities() {
    for (state, expected) in [
        (ReceiptState::Retained, ArtifactAvailability::Retained),
        (ReceiptState::Truncated, ArtifactAvailability::Truncated),
        (ReceiptState::Discarded, ArtifactAvailability::Discarded),
        (ReceiptState::Unavailable, ArtifactAvailability::Unavailable),
    ] {
        let capture = state_capture(state);
        let mut payloads = StagedPayloads::default();
        let artifacts = capture.artifacts().results().source().artifacts().unwrap();
        if matches!(state, ReceiptState::Retained) {
            payloads
                .insert(artifacts[0].reference().into(), FIRST.to_vec())
                .unwrap();
        } else if matches!(state, ReceiptState::Truncated) {
            payloads
                .insert(artifacts[0].reference().into(), b"fir".to_vec())
                .unwrap();
        }
        payloads
            .insert(artifacts[1].reference().into(), SECOND.to_vec())
            .unwrap();
        let bundle = finalized_with(&capture, payloads).unwrap();
        let output = bundle
            .capture()
            .acquisition()
            .receipt()
            .receipt()
            .outputs()
            .iter()
            .find(|output| output.id().get() == 1)
            .unwrap();
        assert_eq!(output.availability(), expected);
    }
}

#[test]
fn nested_bundle_errors_cover_foreign_orphan_discarded_and_unavailable_staged_refs() {
    for (kind, expected) in [
        ("foreign", CaptureBundleError::ForeignReference),
        ("orphan", CaptureBundleError::Orphaned),
    ] {
        let capture = fixture();
        let activity = if kind == "foreign" {
            ActivityId::random()
        } else {
            capture.id().activity_id()
        };
        let id = if kind == "foreign" { 1 } else { 99 };
        let reference: WebArtifactRef =
            serde_json::from_value(json!({"family":"source","reference":{
            "activity_id":activity,"artifact_id":id}}))
            .unwrap();
        let mut payloads = valid_payloads(&capture);
        payloads.insert(reference, FIRST.to_vec()).unwrap();
        assert!(
            matches!(finalized_with(&capture, payloads), Err(LifecycleError::Bundle(error)) if error == expected)
        );
    }
    for (state, expected) in [
        (ReceiptState::Discarded, CaptureBundleError::Discarded),
        (ReceiptState::Unavailable, CaptureBundleError::Unavailable),
    ] {
        let capture = state_capture(state);
        let artifacts = capture.artifacts().results().source().artifacts().unwrap();
        let mut payloads = StagedPayloads::default();
        payloads
            .insert(artifacts[0].reference().into(), FIRST.to_vec())
            .unwrap();
        payloads
            .insert(artifacts[1].reference().into(), SECOND.to_vec())
            .unwrap();
        assert!(
            matches!(finalized_with(&capture, payloads), Err(LifecycleError::Bundle(error)) if error == expected)
        );
    }
}

#[test]
fn deadline_finalization_requires_the_exact_clamped_deadline_offset() {
    for terminal in [99_u64, 100, 101] {
        let (capture, spec) = spec(None, None, 100);
        let mut lifecycle = TestLifecycle::start(spec, started_at(&capture));
        lifecycle
            .observe_through(CaptureOffset::from_microseconds(150))
            .unwrap();
        let mut value = input(
            &capture,
            MeasuredCount::Known(EventCount::new(0)),
            MeasuredCount::Known(ByteCount::new(0)),
            StagedPayloads::default(),
        );
        value.manifest = unavailable_source_manifest(&capture);
        value.terminal_offset = CaptureOffset::from_microseconds(terminal);
        assert!(matches!(
            (terminal, lifecycle.finalize(value)),
            (99, Err(LifecycleError::TerminalOffsetBehind { .. }))
                | (100, Ok(_))
                | (101, Err(LifecycleError::TerminalOffsetMismatch))
        ));
    }
}

#[test]
fn post_stop_deadline_offer_is_already_stopped_not_a_second_deadline_transition() {
    let (capture, spec) = spec(None, None, 100);
    let mut lifecycle = TestLifecycle::start(spec, started_at(&capture));
    lifecycle
        .stop(
            CaptureOffset::from_microseconds(99),
            LifecycleStop::Completed(internal_direct_http::ControllerStopReason::GoalSatisfied),
        )
        .unwrap();
    assert!(matches!(
        lifecycle.admit(event(100, 1, 1, true)),
        Err(BoundedAcquisitionError::AlreadyStopped)
    ));
}

fn unicode_spec(capture: &WebCapture) -> ResolvedDirectHttpCaptureSpec {
    let limit = ByteLimit::try_from(1_000_000_u64).unwrap();
    ResolvedDirectHttpCaptureSpec::new(
        capture.acquisition().request().clone(),
        requests(ArtifactRequest::Required, ArtifactRequest::NotRequested),
        ObservationPolicy::new(
            ObservationLimits::new(CaptureDeadline::try_from(2_000_000).unwrap(), None, None),
            SettlementPolicy::Disabled,
        ),
        DirectHttpContentLimits::new(limit, limit, limit),
        DirectHttpRedirectPolicy::Disabled,
        AcceptedSourceFormats::new([AcceptedSourceFormat::Html]).unwrap(),
        UnsupportedSourceFormatBehavior::RetainAndReport,
        SourceRetentionPolicy::RepresentationAndUnicodeView,
        capture.acquisition().receipt().receipt().producer().clone(),
        capture
            .acquisition()
            .receipt()
            .receipt()
            .operation()
            .clone(),
        DirectHttpOutputSchemas::new(
            schema("com.cascadinglabs.web.source", 1),
            schema("com.cascadinglabs.web.source-representation", 1),
            None,
            Some(schema("com.cascadinglabs.web.unicode", 1)),
        ),
    )
    .unwrap()
}

#[test]
fn unicode_only_source_artifacts_reject_missing_base_representation() {
    let capture = fixture();
    let mut manifest: Value = serde_json::to_value(capture.artifacts()).unwrap();
    manifest["requests"]["source"] = json!("required");
    for artifact in manifest["results"]["source"]["artifacts"]
        .as_array_mut()
        .unwrap()
    {
        artifact["record"]["provenance"]["schema"] =
            json!({"id":"com.cascadinglabs.web.unicode","version":1});
    }
    let manifest: WebArtifactManifest = serde_json::from_value(manifest).unwrap();
    let mut lifecycle = TestLifecycle::start(unicode_spec(&capture), started_at(&capture));
    lifecycle
        .stop(
            CaptureOffset::from_microseconds(1_000_000),
            LifecycleStop::Completed(internal_direct_http::ControllerStopReason::GoalSatisfied),
        )
        .unwrap();
    let mut value = input(
        &capture,
        MeasuredCount::Known(EventCount::new(0)),
        MeasuredCount::Known(ByteCount::new(0)),
        valid_payloads(&capture),
    );
    value.manifest = manifest;
    assert!(matches!(
        lifecycle.finalize(value),
        Err(LifecycleError::SchemaMismatch {
            family: WebArtifactFamily::Source
        })
    ));
}

#[test]
fn acquisition_resolution_initial_redirect_mismatch_returns_no_bundle() {
    let (capture, lifecycle) = stopped();
    let resolution = serde_json::from_value(json!({
        "final_url": {"status":"observed","value":"https://example.com/"},
        "redirects": {"status":"observed","value":[{
            "from":"https://foreign.example/",
            "to":"https://example.com/",
            "cause":{"kind":"http","status":302}
        }]},
        "resource_origin":{"status":"unobserved"},
        "initiator_origin":{"status":"unobserved"}
    }));
    let mut value = input(
        &capture,
        MeasuredCount::Known(EventCount::new(0)),
        MeasuredCount::Known(ByteCount::new(0)),
        valid_payloads(&capture),
    );
    value.resolution = resolution.unwrap();
    assert!(matches!(
        lifecycle.finalize(value),
        Err(LifecycleError::AcquisitionRecord(
            WebAcquisitionRecordError::RedirectInitialUrlMismatch
        ))
    ));
}

#[test]
fn foreign_relationship_is_a_nested_aggregate_error_and_returns_no_bundle() {
    let (capture, lifecycle) = stopped();
    let relationship: WebArtifactRelationship = serde_json::from_value(json!({
        "relation":"rendered_representation_of_source",
        "rendered_dom":{"activity_id":ActivityId::random(),"artifact_id":9},
        "source":{"activity_id":capture.id().activity_id(),"artifact_id":1}
    }))
    .unwrap();
    let mut value = input(
        &capture,
        MeasuredCount::Known(EventCount::new(0)),
        MeasuredCount::Known(ByteCount::new(0)),
        valid_payloads(&capture),
    );
    value.relationships = vec![relationship];
    assert!(matches!(
        lifecycle.finalize(value),
        Err(LifecycleError::WebCapture(
            WebCaptureError::ForeignRelationship
        ))
    ));
}

#[test]
fn unexpected_network_schema_with_valid_network_manifest_returns_no_bundle() {
    let capture = fixture();
    let request_set = WebArtifactRequestSet::new(
        ArtifactRequest::Required,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
        ArtifactRequest::Required,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
    );
    let mut manifest_value = serde_json::to_value(capture.artifacts()).unwrap();
    manifest_value["requests"]["source"] = json!("required");
    manifest_value["requests"]["network"] = json!("required");
    manifest_value["results"]["network"] = manifest_value["results"]["source"].clone();
    let manifest: WebArtifactManifest = serde_json::from_value(manifest_value).unwrap();
    let limit = ByteLimit::try_from(1_000_000_u64).unwrap();
    let spec = ResolvedDirectHttpCaptureSpec::new(
        capture.acquisition().request().clone(),
        request_set,
        ObservationPolicy::new(
            ObservationLimits::new(CaptureDeadline::try_from(2_000_000).unwrap(), None, None),
            SettlementPolicy::Disabled,
        ),
        DirectHttpContentLimits::new(limit, limit, limit),
        DirectHttpRedirectPolicy::Disabled,
        AcceptedSourceFormats::new([AcceptedSourceFormat::Html]).unwrap(),
        UnsupportedSourceFormatBehavior::RetainAndReport,
        SourceRetentionPolicy::Representation,
        capture.acquisition().receipt().receipt().producer().clone(),
        capture
            .acquisition()
            .receipt()
            .receipt()
            .operation()
            .clone(),
        DirectHttpOutputSchemas::new(
            schema("com.cascadinglabs.web.source", 1),
            schema("com.cascadinglabs.web.source-representation", 1),
            Some(schema("com.cascadinglabs.expected-network", 1)),
            None,
        ),
    )
    .unwrap();
    let mut lifecycle = TestLifecycle::start(spec, started_at(&capture));
    lifecycle
        .stop(
            CaptureOffset::from_microseconds(1_000_000),
            LifecycleStop::Completed(internal_direct_http::ControllerStopReason::GoalSatisfied),
        )
        .unwrap();
    let mut value = input(
        &capture,
        MeasuredCount::Known(EventCount::new(0)),
        MeasuredCount::Known(ByteCount::new(0)),
        StagedPayloads::default(),
    );
    value.manifest = manifest;
    assert!(matches!(
        lifecycle.finalize(value),
        Err(LifecycleError::SchemaMismatch {
            family: WebArtifactFamily::Network
        })
    ));
}
