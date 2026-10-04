use super::support::*;
use yosoi_web_capture_direct_http::{
    ArtifactRequest, ByteCount, CaptureOffset, DirectHttpOutputSchemas, EventCount, LifecycleError,
    MeasuredCount, StagedPayloads, WebArtifactManifest,
};

#[test]
fn manifest_request_mismatch_returns_error_and_no_bundle() {
    let (capture, lifecycle) = stopped();
    let mut value = input(
        &capture,
        MeasuredCount::Known(EventCount::new(0)),
        MeasuredCount::Known(ByteCount::new(0)),
        valid_payloads(&capture),
    );
    value.manifest = WebArtifactManifest::new(
        requests(ArtifactRequest::Optional, ArtifactRequest::NotRequested),
        capture.artifacts().results().clone(),
    )
    .unwrap();
    assert!(matches!(
        lifecycle.finalize(value),
        Err(LifecycleError::ManifestMismatch)
    ));
}

#[test]
fn wrong_source_schema_identity_returns_error_and_no_bundle() {
    let schemas = DirectHttpOutputSchemas::new(
        schema("example.wrong-source", 1),
        schema("example.source-representation", 1),
        None,
        None,
    );
    let (capture, spec) = spec_with_schemas(None, None, 2_000_000, schemas);
    let mut lifecycle = TestLifecycle::start(spec, started_at(&capture));
    lifecycle
        .stop(
            CaptureOffset::from_microseconds(1_000_000),
            yosoi_web_capture_direct_http::LifecycleStop::Completed(
                yosoi_web_capture_direct_http::ControllerStopReason::GoalSatisfied,
            ),
        )
        .unwrap();
    assert!(matches!(
        lifecycle.finalize(input(
            &capture,
            MeasuredCount::Known(EventCount::new(0)),
            MeasuredCount::Known(ByteCount::new(0)),
            valid_payloads(&capture)
        )),
        Err(LifecycleError::SchemaMismatch {
            family: yosoi_web_capture_direct_http::WebArtifactFamily::Source
        })
    ));
}

#[test]
fn wrong_source_schema_version_returns_error_and_no_bundle() {
    let schemas = DirectHttpOutputSchemas::new(
        schema("com.cascadinglabs.web.source", 2),
        schema("com.cascadinglabs.web.source-representation", 1),
        None,
        None,
    );
    let (capture, spec) = spec_with_schemas(None, None, 2_000_000, schemas);
    let mut lifecycle = TestLifecycle::start(spec, started_at(&capture));
    lifecycle
        .stop(
            CaptureOffset::from_microseconds(1_000_000),
            yosoi_web_capture_direct_http::LifecycleStop::Completed(
                yosoi_web_capture_direct_http::ControllerStopReason::GoalSatisfied,
            ),
        )
        .unwrap();
    assert!(matches!(
        lifecycle.finalize(input(
            &capture,
            MeasuredCount::Known(EventCount::new(0)),
            MeasuredCount::Known(ByteCount::new(0)),
            valid_payloads(&capture)
        )),
        Err(LifecycleError::SchemaMismatch {
            family: yosoi_web_capture_direct_http::WebArtifactFamily::Source
        })
    ));
}

#[test]
fn finalization_while_running_returns_error_and_no_bundle() {
    let (capture, spec) = spec(None, None, 2_000_000);
    let lifecycle = TestLifecycle::start(spec, started_at(&capture));
    assert!(matches!(
        lifecycle.finalize(input(
            &capture,
            MeasuredCount::Known(EventCount::new(0)),
            MeasuredCount::Known(ByteCount::new(0)),
            valid_payloads(&capture)
        )),
        Err(LifecycleError::StillRunning)
    ));
}

#[test]
fn successful_finalization_preserves_capture_identity_and_resolution() {
    let (capture, lifecycle) = stopped();
    let expected_id = capture.id();
    let expected_resolution = capture.acquisition().resolution().clone();
    let bundle = lifecycle
        .finalize(input(
            &capture,
            MeasuredCount::Known(EventCount::new(0)),
            MeasuredCount::Known(ByteCount::new(0)),
            valid_payloads(&capture),
        ))
        .unwrap();
    assert_eq!(bundle.capture().id(), expected_id);
    assert_eq!(
        bundle.capture().acquisition().resolution(),
        &expected_resolution
    );
}

#[test]
fn accounting_failure_returns_no_bundle() {
    let (capture, spec) = spec(None, None, 2_000_000);
    let mut lifecycle = TestLifecycle::start(spec, started_at(&capture));
    lifecycle.admit(event(1, 1, 1, false)).unwrap();
    lifecycle
        .stop(
            CaptureOffset::from_microseconds(1_000_000),
            yosoi_web_capture_direct_http::LifecycleStop::Completed(
                yosoi_web_capture_direct_http::ControllerStopReason::GoalSatisfied,
            ),
        )
        .unwrap();
    assert!(matches!(
        lifecycle.finalize(input(
            &capture,
            MeasuredCount::Known(EventCount::new(0)),
            MeasuredCount::Known(ByteCount::new(0)),
            valid_payloads(&capture)
        )),
        Err(LifecycleError::EventAccounting(_))
    ));
}

#[test]
fn no_payloads_are_published_on_manifest_and_offset_errors() {
    let error_cases = ["manifest", "offset"];
    for case in error_cases {
        let (capture, lifecycle) = stopped();
        let mut value = input(
            &capture,
            MeasuredCount::Known(EventCount::new(0)),
            MeasuredCount::Known(ByteCount::new(0)),
            StagedPayloads::default(),
        );
        match case {
            "manifest" => {
                value.manifest = WebArtifactManifest::new(
                    requests(ArtifactRequest::Optional, ArtifactRequest::NotRequested),
                    capture.artifacts().results().clone(),
                )
                .unwrap()
            }
            "offset" => value.terminal_offset = CaptureOffset::from_microseconds(0),
            _ => {}
        }
        assert!(lifecycle.finalize(value).is_err());
    }
}
