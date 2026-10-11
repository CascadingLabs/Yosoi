#![allow(
    clippy::unwrap_used,
    clippy::panic,
    reason = "deterministic local fixture"
)]
use crate::internal::test_support::direct_http_fixture as fixture;
use crate::internal::types as internal_types;

use crate::internal::direct_http::*;
use crate::internal::types::{ArtifactAvailability, Schema, SchemaId, SchemaVersion};
use chrono::DateTime;
use fixture::{FixtureService, Protocol, Response};
use std::fs;
use tokio_util::sync::CancellationToken;

fn schema(name: &str) -> Schema {
    Schema::new(
        SchemaId::new(name).unwrap(),
        SchemaVersion::try_from(1).unwrap(),
    )
}
fn spec(url: &str, limit: u64) -> ResolvedDirectHttpCaptureSpec {
    spec_with_retention(
        url,
        limit,
        SourceRetentionPolicy::RepresentationAndUnicodeView,
    )
}

fn spec_with_retention(
    url: &str,
    limit: u64,
    retention: SourceRetentionPolicy,
) -> ResolvedDirectHttpCaptureSpec {
    let bytes = fs::read(format!(
        "{}/src/internal/direct_http/integration_tests/fixtures/web-capture/complete-v1.json",
        env!("CARGO_MANIFEST_DIR")
    ))
    .unwrap();
    let fixture = WebCaptureWire::from_json(&bytes).unwrap();
    let request = WebCaptureRequest::new(
        fixture.id(),
        RequestedWebTarget::parse(url).unwrap(),
        WebAcquisitionStrategy::DirectHttp(DirectHttpAcquisition::new(
            DirectHttpTransportProfile::Standard,
            HttpSessionUse::Isolated,
        )),
    );
    ResolvedDirectHttpCaptureSpec::new(
        request,
        WebArtifactRequestSet::new(
            ArtifactRequest::Required,
            ArtifactRequest::NotRequested,
            ArtifactRequest::NotRequested,
            ArtifactRequest::Optional,
            ArtifactRequest::NotRequested,
            ArtifactRequest::NotRequested,
            ArtifactRequest::NotRequested,
            ArtifactRequest::NotRequested,
            ArtifactRequest::NotRequested,
        ),
        ObservationPolicy::new(
            ObservationLimits::new(CaptureDeadline::try_from(2_000_000).unwrap(), None, None),
            SettlementPolicy::Disabled,
        ),
        DirectHttpContentLimits::new(
            ByteLimit::try_from(1_000_000_u64).unwrap(),
            ByteLimit::try_from(limit).unwrap(),
            ByteLimit::try_from(1_000_000_u64).unwrap(),
        ),
        DirectHttpRedirectPolicy::Disabled,
        AcceptedSourceFormats::new([
            AcceptedSourceFormat::Html,
            AcceptedSourceFormat::Json,
            AcceptedSourceFormat::Xml(XmlSourceProfile::Generic),
            AcceptedSourceFormat::PlainText,
        ])
        .unwrap(),
        UnsupportedSourceFormatBehavior::RetainAndReport,
        retention,
        wreq_adapter_producer().unwrap(),
        fixture
            .acquisition()
            .receipt()
            .receipt()
            .operation()
            .clone(),
        DirectHttpOutputSchemas::new(
            schema("com.cascadinglabs.yosoi.source"),
            schema("com.cascadinglabs.yosoi.source-representation"),
            Some(schema("com.cascadinglabs.yosoi.network")),
            matches!(
                retention,
                SourceRetentionPolicy::RepresentationAndUnicodeView
            )
            .then(|| schema("com.cascadinglabs.yosoi.unicode-view")),
        ),
    )
    .unwrap()
}

#[tokio::test]
async fn public_orchestrator_finalizes_four_formats_and_exact_payloads() {
    for (media, bytes) in [
        (
            "text/html; charset=utf-8",
            &b"<!doctype html><title>x</title>"[..],
        ),
        ("application/json", &b"{\"x\":1}"[..]),
        ("application/xml", &b"<?xml version=\"1.0\"?><x/>"[..]),
        ("text/plain; charset=utf-8", &b"hello"[..]),
    ] {
        let service = FixtureService::start(
            Protocol::Http,
            [("/fixture".into(), Response::bytes(200, Some(media), bytes))],
        )
        .await;
        let bundle = capture_direct_http_at(
            spec(&service.url("/fixture"), 1024),
            &CancellationToken::new(),
            DateTime::from_timestamp(1_700_000_000, 0).unwrap(),
        )
        .await
        .unwrap();
        let artifact = bundle
            .capture()
            .artifacts()
            .results()
            .source()
            .artifacts()
            .unwrap()
            .first()
            .unwrap();
        assert_eq!(
            artifact.metadata().record().availability(),
            ArtifactAvailability::Retained
        );
        assert_eq!(bundle.payload(artifact.reference().into()), Some(bytes));
        let representation = bundle
            .capture()
            .artifacts()
            .results()
            .source_representation()
            .artifacts()
            .unwrap()
            .first()
            .unwrap();
        assert_eq!(representation.source(), artifact.reference());
        assert_eq!(
            representation.metadata().provenance().derived_from(),
            [artifact.reference().as_untyped()]
        );
        let evidence = bundle.source_representation_evidence().unwrap();
        assert_eq!(evidence.source(), artifact.reference());
        assert_eq!(
            evidence,
            SourceRepresentationEvidence::from_facts(
                artifact.reference(),
                bundle
                    .capture()
                    .artifacts()
                    .results()
                    .decoded_source()
                    .artifacts()
                    .and_then(<[DecodedSourceArtifact]>::first)
                    .map(DecodedSourceArtifact::reference),
                bundle.source_facts().unwrap()
            )
            .unwrap()
        );
        let evidence_bytes = bundle.payload(representation.reference().into()).unwrap();
        let evidence_json: serde_json::Value = serde_json::from_slice(evidence_bytes).unwrap();
        assert!(evidence_json.pointer("/decoding/utf8").is_none());
        assert_eq!(evidence.to_canonical_json().unwrap(), evidence_bytes);
        if media.starts_with("text/html") {
            let mut unknown = evidence_json.clone();
            unknown["unknown"] = serde_json::json!(true);
            assert!(matches!(
                SourceRepresentationEvidence::from_json(&serde_json::to_vec(&unknown).unwrap()),
                Err(SourceRepresentationEvidenceError::InvalidJson(_))
            ));
            let mut future = evidence_json;
            future["schema_version"] = serde_json::json!(2);
            assert!(matches!(
                SourceRepresentationEvidence::from_json(&serde_json::to_vec(&future).unwrap()),
                Err(SourceRepresentationEvidenceError::UnsupportedVersion { found: 2 })
            ));
        }
        assert!(matches!(
            bundle.capture().artifacts().results().network(),
            ArtifactFamilyResult::Unavailable { .. }
        ));
        assert_eq!(bundle.capture().id(), fixture_id());
        service.shutdown().await;
    }
}

#[tokio::test]
async fn public_orchestrator_publishes_exact_truncated_prefix() {
    let full = b"abcdefgh";
    let service = FixtureService::start(
        Protocol::Http,
        [(
            "/fixture".into(),
            Response::bytes(200, Some("text/plain; charset=utf-8"), full),
        )],
    )
    .await;
    let bundle = capture_direct_http_at(
        spec(&service.url("/fixture"), 3),
        &CancellationToken::new(),
        DateTime::from_timestamp(1_700_000_000, 0).unwrap(),
    )
    .await
    .unwrap();
    let artifact = bundle
        .capture()
        .artifacts()
        .results()
        .source()
        .artifacts()
        .unwrap()
        .first()
        .unwrap();
    assert_eq!(
        artifact.metadata().record().availability(),
        ArtifactAvailability::Truncated
    );
    assert_eq!(
        bundle.payload(artifact.reference().into()),
        Some(&b"abc"[..])
    );
    assert_eq!(
        bundle.capture().completeness(),
        CaptureCompleteness::Incomplete
    );
    let evidence = bundle.source_representation_evidence().unwrap();
    assert!(matches!(
        evidence.classification(),
        SourceClassificationOutcome::Classified(classified)
            if classified.extent() == ClassificationExtent::RetainedPrefix
    ));
    service.shutdown().await;
}

#[tokio::test]
async fn retain_and_report_preserves_unavailable_unicode_facts_and_into_parts() {
    let service = FixtureService::start(
        Protocol::Http,
        [(
            "/fixture".into(),
            Response::bytes(200, Some("application/pdf"), b"not a supported source"),
        )],
    )
    .await;
    let capture = capture_direct_http_at(
        spec(&service.url("/fixture"), 1024),
        &CancellationToken::new(),
        DateTime::from_timestamp(1_700_000_000, 0).unwrap(),
    )
    .await
    .unwrap();
    assert!(matches!(
        capture.source_facts().unwrap().classification(),
        SourceClassificationOutcome::Unsupported { .. }
    ));
    assert!(matches!(
        capture.source_facts().unwrap().decoding(),
        CharacterDecodingOutcome::NotApplicable(_)
    ));
    let durable = capture.source_representation_evidence().unwrap();
    assert!(matches!(
        durable.classification(),
        SourceClassificationOutcome::Unsupported { .. }
    ));
    assert!(matches!(
        durable.decoding(),
        DurableCharacterDecoding::NotApplicable { .. }
    ));
    assert_eq!(
        capture.bundle().capture().completeness(),
        CaptureCompleteness::Incomplete
    );
    let (bundle, response, source_facts, identity) = capture.into_parts();
    assert!(source_facts.is_some());
    assert_eq!(response.status(), 200);
    assert_eq!(identity.environment(), bundle.capture().environment());
    service.shutdown().await;
}

#[tokio::test]
async fn representation_only_retention_records_decoding_without_a_dangling_decoded_reference() {
    let service = FixtureService::start(
        Protocol::Http,
        [(
            "/fixture".into(),
            Response::bytes(200, Some("text/plain; charset=utf-8"), b"facts only"),
        )],
    )
    .await;
    let capture = capture_direct_http_at(
        spec_with_retention(
            &service.url("/fixture"),
            1024,
            SourceRetentionPolicy::Representation,
        ),
        &CancellationToken::new(),
        DateTime::from_timestamp(1_700_000_000, 0).unwrap(),
    )
    .await
    .unwrap();
    assert!(
        capture
            .capture()
            .artifacts()
            .results()
            .decoded_source()
            .is_not_requested()
    );
    assert!(matches!(
        capture.source_representation_evidence().unwrap().decoding(),
        DurableCharacterDecoding::Complete(view) if view.decoded_source().is_none()
    ));
    service.shutdown().await;
}

#[tokio::test]
async fn durable_source_representation_survives_offline_handoff_and_rejects_tampering() {
    let service = FixtureService::start(
        Protocol::Http,
        [(
            "/fixture".into(),
            Response::bytes(200, Some("text/plain; charset=utf-8"), b"durable facts"),
        )],
    )
    .await;
    let capture = capture_direct_http_at(
        spec(&service.url("/fixture"), 1024),
        &CancellationToken::new(),
        DateTime::from_timestamp(1_700_000_000, 0).unwrap(),
    )
    .await
    .unwrap();
    let (bundle, _, _, _) = capture.into_parts();
    let canonical = WebCaptureWire::to_canonical_json(bundle.capture()).unwrap();
    let (metadata, payloads) = bundle.into_parts();
    let representation = metadata
        .artifacts()
        .results()
        .source_representation()
        .artifacts()
        .unwrap()
        .first()
        .unwrap()
        .clone();
    let representation_ref: WebArtifactRef = representation.reference().into();

    let parsed = WebCaptureWire::from_json(&canonical).unwrap();
    let mut missing = CaptureBundle::builder(parsed);
    for (reference, bytes) in &payloads {
        if *reference != representation_ref {
            missing.insert(*reference, bytes.clone()).unwrap();
        }
    }
    assert_eq!(missing.finalize(), Err(CaptureBundleError::Missing));

    let parsed = WebCaptureWire::from_json(&canonical).unwrap();
    let mut tampered = CaptureBundle::builder(parsed);
    for (reference, bytes) in &payloads {
        let mut supplied = bytes.clone();
        if *reference == representation_ref
            && let Some(first) = supplied.first_mut()
        {
            *first ^= 1;
        }
        let result = tampered.insert(*reference, supplied);
        if *reference == representation_ref {
            assert_eq!(result, Err(CaptureBundleError::DigestMismatch));
        } else {
            result.unwrap();
        }
    }

    let parsed = WebCaptureWire::from_json(&canonical).unwrap();
    let mut rebuilt = CaptureBundle::builder(parsed);
    for (reference, bytes) in payloads {
        rebuilt.insert(reference, bytes).unwrap();
    }
    let rebuilt = rebuilt.finalize().unwrap();
    let payload = rebuilt.payload(representation_ref).unwrap();
    let durable = representation
        .parse_payload_for_capture(rebuilt.capture(), payload)
        .unwrap();
    assert_eq!(durable.source(), representation.source());
    service.shutdown().await;
}

#[tokio::test]
async fn injected_artifact_timestamps_are_ordered_and_exact() {
    let started_at = DateTime::from_timestamp(1_700_000_000, 0).unwrap();
    let source_generated_at = DateTime::from_timestamp(1_700_000_001, 0).unwrap();
    let decoded_generated_at = DateTime::from_timestamp(1_700_000_002, 0).unwrap();
    let finished_at = DateTime::from_timestamp(1_700_000_003, 0).unwrap();
    let service = FixtureService::start(
        Protocol::Http,
        [
            (
                "/clock".into(),
                Response::bytes(200, Some("text/plain; charset=utf-8"), b"clock"),
            ),
            (
                "/bad-clock".into(),
                Response::bytes(200, Some("text/plain; charset=utf-8"), b"bad-clock"),
            ),
            (
                "/invalid-window".into(),
                Response::bytes(200, Some("text/plain; charset=utf-8"), b"invalid-window"),
            ),
        ],
    )
    .await;
    let capture = capture_direct_http_with_clock(
        spec(&service.url("/clock"), 1024),
        &CancellationToken::new(),
        DirectHttpCaptureTimestamps {
            started_at,
            source_generated_at,
            decoded_generated_at,
            finished_at,
        },
    )
    .await
    .unwrap();
    let results = capture.bundle().capture().artifacts().results();
    let source_at = results
        .source()
        .artifacts()
        .unwrap()
        .iter()
        .next()
        .unwrap()
        .metadata()
        .provenance()
        .generated_at();
    let decoded_at = results
        .decoded_source()
        .artifacts()
        .unwrap()
        .iter()
        .next()
        .unwrap()
        .metadata()
        .provenance()
        .generated_at();
    assert_eq!(*source_at, source_generated_at);
    assert_eq!(*decoded_at, decoded_generated_at);

    let error = capture_direct_http_with_clock(
        spec(&service.url("/bad-clock"), 1024),
        &CancellationToken::new(),
        DirectHttpCaptureTimestamps {
            started_at,
            source_generated_at: decoded_generated_at,
            decoded_generated_at: source_generated_at,
            finished_at,
        },
    )
    .await
    .unwrap_err();
    assert!(matches!(
        error,
        DirectHttpCaptureError::Finalization {
            source: DirectHttpConstructionError::Lifecycle(
                LifecycleError::ArtifactTimestampsUnordered
            ),
            ..
        }
    ));

    let error = capture_direct_http_with_clock(
        spec(&service.url("/invalid-window"), 1024),
        &CancellationToken::new(),
        DirectHttpCaptureTimestamps {
            started_at,
            source_generated_at: decoded_generated_at,
            decoded_generated_at: source_generated_at,
            finished_at: started_at - chrono::TimeDelta::seconds(1),
        },
    )
    .await
    .unwrap_err();
    assert!(matches!(
        error,
        DirectHttpCaptureError::Finalization {
            source: DirectHttpConstructionError::Lifecycle(LifecycleError::ObservationWindow(_)),
            ..
        }
    ));
    service.shutdown().await;
}

fn fixture_id() -> internal_types::CaptureId {
    let bytes = fs::read(format!(
        "{}/src/internal/direct_http/integration_tests/fixtures/web-capture/complete-v1.json",
        env!("CARGO_MANIFEST_DIR")
    ))
    .unwrap();
    WebCaptureWire::from_json(&bytes).unwrap().id()
}
