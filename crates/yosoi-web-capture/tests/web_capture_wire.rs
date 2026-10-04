#![allow(
    clippy::unwrap_used,
    reason = "test fixtures use deliberately valid constants"
)]

use std::{
    env, fs,
    num::{NonZeroU32, NonZeroU64},
    path::PathBuf,
};

use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use yosoi_types::{
    ActivityId, ActivityOutcome, ActivityReceipt, ActivitySignal, ArtifactAvailability, ArtifactId,
    ArtifactRecord, ArtifactRef, CaptureId, CaptureReceipt, OperationId, Producer, ProducerId,
    ProducerVersion, Provenance, ReasonCode, RetryDisposition, Schema, SchemaId, SchemaVersion,
    Sha256Digest,
};
use yosoi_web_capture::{
    AcquisitionCapabilityProfile, ActivityCount, ArtifactByteExtent, ArtifactCapability,
    ArtifactCollection, ArtifactFamilyResult, ArtifactMultiplicity, ArtifactRequest,
    ArtifactSensitivity, BrowserCleanupDeadline, BrowserContextCleanupDisposition,
    BrowserContextLease, BrowserContextLeaseId, BrowserContextTotalLimit,
    BrowserContextsPerProcessLimit, BrowserExecutionAccountingReceipt,
    BrowserExecutionAdmissionReceipt, BrowserExecutionCleanupReceipt, BrowserExecutionId,
    BrowserExecutionLease, BrowserExecutionLimits, BrowserExecutionManagerId,
    BrowserExecutionReceipt, BrowserExecutionScope, BrowserExecutionTerminalReason,
    BrowserExecutionTerminalReceipt, BrowserProcessCleanupDisposition, BrowserProcessGeneration,
    BrowserProcessLimit, BrowserProcessSlotId, BrowserProcessSlotLease, BrowserQueueDepthLimit,
    BrowserQueueWaitLimit, BrowserRecycleThreshold, BrowserSessionLease, BrowserSessionLeaseId,
    BrowserTabLease, BrowserTabLeaseId, BrowserTabTotalLimit, BrowserTabsPerSessionLimit,
    ByteAccounting, ByteCount, CaptureCompleteness, CaptureDeadline, CaptureDuration,
    CaptureEnvironment, CaptureObservation, CaptureOffset, CaptureResolution, CaptureTermination,
    ControllerStopReason, DirectHttpAcquisition, DirectHttpTransportProfile, EnvironmentValue,
    EventAccounting, EventCount, HttpCaptureEnvironment, HttpSessionUse, InFlightActivity,
    MeasuredCount, MediaType, Observation, ObservationLimits, ObservationPolicy, ObservationWindow,
    RenderedDomArtifact, RequestedWebTarget, SettlementPolicy, SourceArtifact,
    TerminalObservationState, WebAcquisitionRecord, WebArtifactCapabilitySet, WebArtifactManifest,
    WebArtifactRelationship, WebArtifactRequestSet, WebArtifactResults, WebCapture,
    WebCaptureError, WebCaptureRequest, WebCaptureWire, WebCaptureWireError,
    WebProviderCapabilityProfile,
};

#[test]
fn current_v1_goldens_and_new_captures_round_trip_without_migration() {
    let captures = [
        (
            "minimal-v1.json",
            minimal_capture(fixed_capture_id(1), false),
        ),
        (
            "complete-v1.json",
            source_capture(fixed_capture_id(2), false),
        ),
        (
            "partial-v1.json",
            minimal_capture(fixed_capture_id(3), true),
        ),
    ];

    for (fixture_name, capture) in captures {
        let fixture_bytes = fs::read(fixture_path(fixture_name)).unwrap();
        let fixture: Value = serde_json::from_slice(&fixture_bytes).unwrap();
        assert_eq!(fixture["schema_version"], 1);
        assert!(
            fixture
                .pointer("/capture/artifacts/results/decoded_source")
                .is_some()
        );
        assert!(
            fixture
                .pointer("/capture/artifacts/results/source_representation")
                .is_some()
        );
        let decoded_fixture = WebCaptureWire::from_json(&fixture_bytes).unwrap();
        assert!(
            decoded_fixture
                .artifacts()
                .results()
                .decoded_source()
                .is_not_requested()
        );

        let encoded = WebCaptureWire::to_canonical_json(&capture).unwrap();
        let current: Value = serde_json::from_slice(&encoded).unwrap();
        assert_eq!(current["schema_version"], 1);
        let decoded = WebCaptureWire::from_json(&encoded).unwrap();
        assert_eq!(
            WebCaptureWire::to_canonical_json(&decoded).unwrap(),
            encoded
        );
    }
}

#[test]
fn canonical_json_sorts_non_semantic_artifact_and_output_order() {
    let capture_id = fixed_capture_id(4);
    let forward = source_capture(capture_id, false);
    let reversed = source_capture(capture_id, true);

    assert_ne!(
        forward, reversed,
        "ordinary equality preserves represented order"
    );
    assert_eq!(
        WebCaptureWire::to_canonical_json(&forward).unwrap(),
        WebCaptureWire::to_canonical_json(&reversed).unwrap()
    );
}

#[test]
fn semantic_identity_excludes_occurrence_locations_and_wall_clock_times() {
    let first_lineage = ArtifactRef::new(ActivityId::random(), ArtifactId::try_from(90).unwrap());
    let second_lineage = ArtifactRef::new(ActivityId::random(), ArtifactId::try_from(91).unwrap());
    let first = source_capture_with_locations(
        fixed_capture_id(5),
        [1, 2],
        [
            timestamp("2026-09-05T00:00:00.250Z"),
            timestamp("2026-09-05T00:00:00.750Z"),
        ],
        first_lineage,
    );
    let second = source_capture_with_locations(
        fixed_capture_id(6),
        [11, 12],
        [
            timestamp("2026-09-05T00:00:00.100Z"),
            timestamp("2026-09-05T00:00:00.900Z"),
        ],
        second_lineage,
    );

    assert_ne!(first, second);
    assert_ne!(
        WebCaptureWire::to_canonical_json(&first).unwrap(),
        WebCaptureWire::to_canonical_json(&second).unwrap()
    );
    assert_eq!(
        WebCaptureWire::identity_digest(&first).unwrap(),
        WebCaptureWire::identity_digest(&second).unwrap()
    );
}

#[test]
fn unsupported_versions_and_invalid_documents_fail_closed() {
    let unsupported = br#"{"schema_version":2,"capture":{}}"#;
    assert!(matches!(
        WebCaptureWire::from_json(unsupported),
        Err(WebCaptureWireError::UnsupportedSchemaVersion {
            found: 2,
            supported: 1
        })
    ));

    let mut obsolete_v1: Value =
        serde_json::from_slice(&fs::read(fixture_path("minimal-v1.json")).unwrap()).unwrap();
    obsolete_v1["capture"]["artifacts"]["results"]
        .as_object_mut()
        .unwrap()
        .remove("decoded_source");
    assert!(matches!(
        WebCaptureWire::from_json(&serde_json::to_vec(&obsolete_v1).unwrap()),
        Err(WebCaptureWireError::InvalidJson(_))
    ));
    for invalid_version in [
        br#"{"capture":{}}"#.as_slice(),
        br#"{"schema_version":0,"capture":{}}"#.as_slice(),
        br#"{"schema_version":-1,"capture":{}}"#.as_slice(),
        br#"{"schema_version":1.5,"capture":{}}"#.as_slice(),
        br#"{"schema_version":true,"capture":{}}"#.as_slice(),
        br#"{"schema_version":"1","capture":{}}"#.as_slice(),
    ] {
        assert!(matches!(
            WebCaptureWire::from_json(invalid_version),
            Err(WebCaptureWireError::MissingSchemaVersion
                | WebCaptureWireError::InvalidSchemaVersion)
        ));
    }

    let invalid = fixture_path("invalid-v1.json");
    let bytes = fs::read(invalid).unwrap();
    assert!(matches!(
        WebCaptureWire::from_json(&bytes),
        Err(WebCaptureWireError::InvalidJson(_))
    ));
}

#[test]
fn finalization_rejects_capability_and_receipt_contradictions() {
    let valid = minimal_parts(fixed_capture_id(7), false);
    let wrong_producer = producer("com.cascadinglabs.other");
    let wrong_capabilities = WebProviderCapabilityProfile::new(
        wrong_producer,
        AcquisitionCapabilityProfile::DirectHttp,
        capabilities(ArtifactMultiplicity::Many),
    )
    .unwrap();
    assert_eq!(
        WebCapture::finalize(
            valid.acquisition,
            valid.environment,
            valid.observation,
            wrong_capabilities,
            valid.artifacts,
            Vec::new(),
        ),
        Err(WebCaptureError::CapabilityProducerMismatch)
    );

    let mut complete = source_parts(fixed_capture_id(8), false);
    complete.artifacts = manifest_with_source(ArtifactFamilyResult::Unsupported {
        reason: reason("provider.unsupported"),
    });
    assert!(matches!(
        WebCapture::finalize(
            complete.acquisition,
            complete.environment,
            complete.observation,
            complete.capabilities,
            complete.artifacts,
            Vec::new(),
        ),
        Err(WebCaptureError::CapabilityResultMismatch { .. })
    ));
}

#[test]
fn finalization_rejects_artifact_containment_and_multiplicity_errors() {
    let mut multiplicity = source_parts(fixed_capture_id(7), false);
    multiplicity.capabilities = WebProviderCapabilityProfile::new(
        producer("com.cascadinglabs.http-test"),
        AcquisitionCapabilityProfile::DirectHttp,
        capabilities(ArtifactMultiplicity::ExactlyOne),
    )
    .unwrap();
    assert!(matches!(
        finalize_result(multiplicity, Vec::new()),
        Err(WebCaptureError::ArtifactMultiplicityExceeded { .. })
    ));

    let mut outside_window = source_parts(fixed_capture_id(8), false);
    outside_window.observation = observation(
        timestamp("2026-09-05T00:00:00.500Z"),
        timestamp("2026-09-05T00:00:00.900Z"),
        CaptureDeadline::try_from(2_000_000).unwrap(),
        CaptureTermination::ControllerStopped(ControllerStopReason::GoalSatisfied),
    );
    assert_eq!(
        finalize_result(outside_window, Vec::new()),
        Err(WebCaptureError::ArtifactTimeOutsideWindow)
    );

    let mut receipt_mismatch = source_parts(fixed_capture_id(9), false);
    receipt_mismatch.artifacts = empty_manifest();
    assert_eq!(
        finalize_result(receipt_mismatch, Vec::new()),
        Err(WebCaptureError::ReceiptOutputMismatch)
    );
}

#[test]
fn browser_execution_receipts_are_rejected_for_http_captures_during_attachment_and_deserialization()
{
    let capture = minimal_capture(fixed_capture_id(1), false);
    let receipt = browser_execution_receipt(capture.id());
    assert!(matches!(
        capture.clone().with_browser_execution(receipt.clone()),
        Err(WebCaptureError::BrowserExecutionStrategyMismatch)
    ));

    let mut document: Value =
        serde_json::from_slice(&WebCaptureWire::to_canonical_json(&capture).unwrap()).unwrap();
    document["capture"]["browser_execution"] = serde_json::to_value(receipt).unwrap();
    assert!(matches!(
        WebCaptureWire::from_json(&serde_json::to_vec(&document).unwrap()),
        Err(WebCaptureWireError::InvalidJson(_))
    ));
}

#[test]
fn finalization_rejects_foreign_relationship_endpoints() {
    let parts = source_parts(fixed_capture_id(7), false);
    let source = parts
        .artifacts
        .results()
        .source()
        .artifacts()
        .and_then(<[SourceArtifact]>::first)
        .unwrap()
        .reference();
    let foreign_record = source_record(
        fixed_capture_id(8),
        3,
        b"rendered",
        timestamp("2026-09-05T00:00:00.500Z"),
        Vec::new(),
    );
    let rendered_dom = RenderedDomArtifact::new(source_artifact(foreign_record).into_metadata());
    let relationship = WebArtifactRelationship::RenderedRepresentationOfSource {
        rendered_dom: rendered_dom.reference(),
        source,
    };

    assert_eq!(
        finalize_result(parts, vec![relationship]),
        Err(WebCaptureError::ForeignRelationship)
    );
}

include!("web_capture_wire/model_support.rs");
include!("web_capture_wire/domain_support.rs");
include!("web_capture_wire/fixture_support.rs");
