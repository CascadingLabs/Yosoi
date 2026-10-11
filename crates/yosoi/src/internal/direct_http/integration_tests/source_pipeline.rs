#![allow(
    clippy::absolute_paths,
    clippy::as_conversions,
    clippy::large_futures,
    clippy::missing_const_for_fn,
    clippy::panic,
    clippy::type_complexity,
    clippy::unwrap_used,
    reason = "black-box fixtures use validated constants and compact assertions"
)]

use crate::internal::direct_http::{
    AcceptedSourceFormat, AcceptedSourceFormats, ArtifactByteExtent, ArtifactRequest,
    ArtifactSensitivity, BodyTerminal, ByteCount, ByteLimit, CaptureDeadline,
    CharacterDecodingOutcome, ClassificationExtent, DecodedOutputIdentity,
    DecodedSourceArtifactRef, DecodingErrorCode, DirectHttpAcquisition, DirectHttpContentLimits,
    DirectHttpOutputSchemas, DirectHttpRedirectPolicy, DirectHttpResponseFacts,
    DirectHttpTransportProfile, HttpSessionUse, MeasuredCount, MediaDeclaration,
    MediaDeclarationIssue, MediaType, ObservationLimits, ObservationPolicy, ObservedHeaderValue,
    RequestedWebTarget, ResolvedDirectHttpCaptureSpec, ResponseBodyOutcome, RetainedSource,
    RetainedSourceExtent, SettlementPolicy, SourceArtifact, SourceClassificationOutcome,
    SourceRetentionPolicy, UnsupportedSourceFormatBehavior, ValidatedSourceBinding,
    WebAcquisitionStrategy, WebArtifactMetadata, WebArtifactRequestSet, WebCaptureRequest,
    WebCaptureWire, classify_and_decode, consume_response_body, execute_direct_http_at,
};
use crate::internal::types::{
    ActivityId, ArtifactAvailability, ArtifactId, ArtifactRecord, ArtifactRef, Producer,
    ProducerId, ProducerVersion, Provenance, Schema, SchemaId, SchemaVersion, Sha256Digest,
};
use chrono::DateTime;
use std::{
    io::{Read, Write},
    net::TcpListener,
    thread,
};
use tokio_util::sync::CancellationToken;

fn serve(headers: &str, body: &[u8]) -> String {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    let response = format!(
        "HTTP/1.1 200 OK\r\n{headers}Content-Length: {}\r\n\r\n",
        body.len()
    );
    let mut wire = response.into_bytes();
    wire.extend_from_slice(body);
    thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        let mut request = [0; 1024];
        let _ = stream.read(&mut request);
        stream.write_all(&wire).unwrap();
    });
    format!("http://{address}/source?canary=URL_CANARY")
}

fn named_schema(name: &str) -> Schema {
    Schema::new(
        SchemaId::new(name).unwrap(),
        SchemaVersion::try_from(1).unwrap(),
    )
}
fn producer(name: &str) -> Producer {
    Producer::new(
        ProducerId::new(name).unwrap(),
        ProducerVersion::new("1.0.0").unwrap(),
    )
}
fn spec(url: &str, limit: u64) -> ResolvedDirectHttpCaptureSpec {
    let fixture = std::fs::read(format!(
        "{}/src/internal/direct_http/integration_tests/fixtures/web-capture/complete-v1.json",
        env!("CARGO_MANIFEST_DIR")
    ))
    .unwrap();
    let capture = WebCaptureWire::from_json(&fixture).unwrap();
    let request = WebCaptureRequest::new(
        capture.acquisition().request().capture_id(),
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
            ArtifactRequest::NotRequested,
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
            ByteLimit::try_from(limit).unwrap(),
        ),
        DirectHttpRedirectPolicy::Disabled,
        AcceptedSourceFormats::new([AcceptedSourceFormat::Html]).unwrap(),
        UnsupportedSourceFormatBehavior::RetainAndReport,
        SourceRetentionPolicy::Representation,
        crate::internal::direct_http::wreq_adapter_producer().unwrap(),
        capture
            .acquisition()
            .receipt()
            .receipt()
            .operation()
            .clone(),
        DirectHttpOutputSchemas::new(
            named_schema("com.cascadinglabs.yosoi.web-source"),
            named_schema("com.cascadinglabs.yosoi.source-representation"),
            None,
            None,
        ),
    )
    .unwrap()
}

async fn acquire(
    headers: &str,
    full: &[u8],
    limit: u64,
) -> (ResponseBodyOutcome, DirectHttpResponseFacts) {
    let url = serve(headers, full);
    let pending = execute_direct_http_at(
        spec(&url, limit),
        &CancellationToken::new(),
        DateTime::from_timestamp(1_700_000_000, 0).unwrap(),
    )
    .await
    .unwrap();
    assert!(!format!("{pending:?}").contains("URL_CANARY"));
    let (outcome, _, facts, _, _) = consume_response_body(pending, &CancellationToken::new())
        .await
        .unwrap();
    assert!(outcome.payload().retained_source().is_some());
    (outcome, facts)
}

fn retained(body: &ResponseBodyOutcome) -> &RetainedSource {
    body.payload().retained_source().unwrap()
}

fn identities(
    body: &ResponseBodyOutcome,
    complete_size: u64,
) -> (SourceArtifact, DecodedOutputIdentity) {
    let retained = retained(body);
    let activity = ActivityId::random();
    let extent = match retained.extent() {
        RetainedSourceExtent::Complete => ArtifactByteExtent::Complete {
            retained_bytes: ByteCount::new(retained.bytes().len() as u64),
        },
        RetainedSourceExtent::Truncated => ArtifactByteExtent::truncated(
            ByteCount::new(retained.bytes().len() as u64),
            MeasuredCount::Known(ByteCount::new(complete_size)),
        )
        .unwrap(),
    };
    let availability = if retained.extent() == RetainedSourceExtent::Complete {
        ArtifactAvailability::Retained
    } else {
        ArtifactAvailability::Truncated
    };
    let reason = (availability == ArtifactAvailability::Truncated)
        .then(|| crate::internal::types::ReasonCode::new("test.source_truncated").unwrap());
    let provenance = Provenance::new(
        activity,
        producer("com.cascadinglabs.tests.source"),
        named_schema("com.cascadinglabs.tests.source"),
        "2026-01-01T00:00:00Z".parse().unwrap(),
        Vec::new(),
    );
    let record = ArtifactRecord::new(
        ArtifactId::try_from(1).unwrap(),
        Some(retained.digest()),
        availability,
        reason,
        provenance,
    )
    .unwrap();
    let metadata = WebArtifactMetadata::new(
        record,
        MediaType::new("application/octet-stream").unwrap(),
        extent,
        ArtifactSensitivity::NonSensitive,
    )
    .unwrap();
    let source = SourceArtifact::new(metadata);
    let output_ref = DecodedSourceArtifactRef::from_untyped(ArtifactRef::new(
        activity,
        ArtifactId::try_from(2).unwrap(),
    ));
    let identity = DecodedOutputIdentity::new(
        output_ref,
        producer("com.cascadinglabs.tests.decoder"),
        named_schema("com.cascadinglabs.tests.decoded"),
        vec![source.reference().as_untyped()],
        source.reference(),
    )
    .unwrap();
    (source, identity)
}

fn extent(outcome: &SourceClassificationOutcome) -> ClassificationExtent {
    match outcome {
        SourceClassificationOutcome::Classified(value) => value.extent(),
        SourceClassificationOutcome::Unknown { extent, .. }
        | SourceClassificationOutcome::Unsupported { extent, .. }
        | SourceClassificationOutcome::Ambiguous { extent, .. } => *extent,
    }
}
fn decoded(outcome: &CharacterDecodingOutcome) -> &crate::internal::direct_http::DecodedSourceView {
    match outcome {
        CharacterDecodingOutcome::Complete(view)
        | CharacterDecodingOutcome::OutputTruncated(view) => view,
        other => panic!("expected view, got {other:?}"),
    }
}
fn classify(
    body: &ResponseBodyOutcome,
    facts: &DirectHttpResponseFacts,
    complete: usize,
) -> crate::internal::direct_http::SourceRepresentationFacts {
    let (source, identity) = identities(body, complete as u64);
    let retained = retained(body);
    classify_and_decode(
        ValidatedSourceBinding::new(retained, &source).unwrap(),
        &facts.source_media_type(),
        &identity,
        1_000_000,
    )
}

#[tokio::test]
async fn response_head_singleton_observation_drives_redacted_replay() {
    let canary = "HEADER_CANARY";
    for header in [
        format!("Content-Type: text/plain; x={canary}\r\nContent-Type: text/plain; x={canary}\r\n"),
        format!(
            "Content-Type: text/plain; x={canary}\r\nContent-Type: application/json; x={canary}\r\n"
        ),
    ] {
        let (body, facts) = acquire(&header, b"hello", 100).await;
        assert_eq!(facts.content_type(), &ObservedHeaderValue::Duplicate);
        assert!(!format!("{facts:?}").contains(canary));
        let first = classify(&body, &facts, 5);
        let second = classify(&body, &facts, 5);
        assert_eq!(first, second);
        assert_eq!(
            first.declaration(),
            &MediaDeclaration::Malformed(MediaDeclarationIssue::DuplicateField)
        );
        assert!(!format!("{first:?}").contains(canary));
    }
    let long = format!(
        "Content-Type: text/plain; x={}\r\n",
        "HEADER_CANARY".repeat(100)
    );
    let (body, facts) = acquire(&long, b"hello", 100).await;
    assert_eq!(facts.content_type(), &ObservedHeaderValue::TooLong);
    let result = classify(&body, &facts, 5);
    assert_eq!(
        result.declaration(),
        &MediaDeclaration::Malformed(MediaDeclarationIssue::TooLong)
    );
    assert!(!format!("{facts:?}{result:?}").contains("HEADER_CANARY"));
}

#[tokio::test]
async fn real_truncation_propagates_through_all_classification_outcomes() {
    let cases: [(&str, &[u8], usize, fn(&SourceClassificationOutcome) -> bool); 4] = [
        (
            "Content-Type: text/plain\r\n",
            b"abcdef",
            3,
            |v| matches!(v, SourceClassificationOutcome::Classified(c) if c.format() == crate::internal::direct_http::SourceFormat::PlainText),
        ),
        (
            "",
            b"<html>xTAIL",
            7,
            |v| matches!(v, SourceClassificationOutcome::Classified(c) if c.basis() == crate::internal::direct_http::ClassificationBasis::Sniffed),
        ),
        ("", b"zzTAIL", 2, |v| {
            matches!(v, SourceClassificationOutcome::Unknown { .. })
        }),
        (
            "Content-Type: image/png\r\n",
            b"abcdef",
            3,
            |v| matches!(v, SourceClassificationOutcome::Unsupported { essence, .. } if essence == "image/png"),
        ),
    ];
    for (header, full, limit, shape) in cases {
        let (body, facts) = acquire(header, full, limit as u64).await;
        assert_eq!(retained(&body).extent(), RetainedSourceExtent::Truncated);
        assert_eq!(body.terminal(), BodyTerminal::RepresentationLimit);
        let retained_bytes = retained(&body).bytes().to_vec();
        let digest = retained(&body).digest();
        let result = classify(&body, &facts, full.len());
        assert!(shape(result.classification()));
        assert_eq!(
            extent(result.classification()),
            ClassificationExtent::RetainedPrefix
        );
        assert_eq!(retained(&body).bytes(), retained_bytes);
        assert_eq!(retained(&body).digest(), digest);
    }
}

async fn decoding_case(header: &str, retained: &[u8], invalid: bool) {
    let mut full = retained.to_vec();
    full.extend_from_slice(b"TAIL");
    let (body, facts) = acquire(header, &full, retained.len() as u64).await;
    assert_eq!(self::retained(&body).bytes(), retained);
    assert_eq!(
        self::retained(&body).digest(),
        Sha256Digest::digest(retained)
    );
    let (source, identity) = identities(&body, full.len() as u64);
    let retained_source = self::retained(&body);
    let result = classify_and_decode(
        ValidatedSourceBinding::new(retained_source, &source).unwrap(),
        &facts.source_media_type(),
        &identity,
        1_000_000,
    );
    assert_eq!(
        extent(result.classification()),
        ClassificationExtent::RetainedPrefix
    );
    if invalid {
        assert!(matches!(
            result.decoding(),
            CharacterDecodingOutcome::Undecodable(DecodingErrorCode::InvalidSequence)
        ));
        return;
    }
    let view = decoded(result.decoding());
    assert!(matches!(
        result.decoding(),
        CharacterDecodingOutcome::Complete(_)
    ));
    assert!(view.source_truncated());
    assert!(view.incomplete_terminal_sequence());
    assert_eq!(view.artifact().reference(), identity.reference());
    assert_eq!(view.source(), source.reference());
    assert_eq!(view.derived_from(), [source.reference().as_untyped()]);
    assert_eq!(view.producer(), identity.producer());
    assert_eq!(view.schema(), identity.schema());
    assert_eq!(
        view.artifact().metadata().media_type().as_str(),
        crate::internal::direct_http::DECODED_SOURCE_UTF8_MEDIA_TYPE
    );
    assert_eq!(
        view.artifact().metadata().extent(),
        &ArtifactByteExtent::Complete {
            retained_bytes: ByteCount::new(view.bytes().len() as u64)
        }
    );
    assert_eq!(view.digest(), Sha256Digest::digest(view.bytes()));
}

#[path = "source_pipeline/decoding.rs"]
mod decoding;
