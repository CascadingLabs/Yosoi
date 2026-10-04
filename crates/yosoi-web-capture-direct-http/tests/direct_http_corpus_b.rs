#![allow(
    clippy::unwrap_used,
    clippy::panic,
    reason = "deterministic fixture assertions"
)]
#[path = "support/direct_http_corpus.rs"]
mod corpus;
#[path = "support/direct_http_fixture.rs"]
mod fixture;

use chrono::{DateTime, Utc};
use corpus::*;
use fixture::{FixtureService, Protocol, Response};
use std::iter::once;
use tokio_util::sync::CancellationToken;
use yosoi_types::{ArtifactAvailability, Schema, SchemaId, SchemaVersion};
use yosoi_web_capture_direct_http::*;

fn schema(name: &str) -> Schema {
    Schema::new(
        SchemaId::new(name).unwrap(),
        SchemaVersion::try_from(1).unwrap(),
    )
}

fn spec(url: &str, encoded: u64, representation: u64) -> ResolvedDirectHttpCaptureSpec {
    let seed =
        WebCaptureWire::from_json(include_bytes!("fixtures/web-capture/complete-v1.json")).unwrap();
    let request = WebCaptureRequest::new(
        seed.id(),
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
            ByteLimit::try_from(encoded).unwrap(),
            ByteLimit::try_from(representation).unwrap(),
            ByteLimit::try_from(1_000_000_u64).unwrap(),
        ),
        DirectHttpRedirectPolicy::Disabled,
        AcceptedSourceFormats::new([AcceptedSourceFormat::PlainText]).unwrap(),
        UnsupportedSourceFormatBehavior::RetainAndReport,
        SourceRetentionPolicy::RepresentationAndUnicodeView,
        wreq_adapter_producer().unwrap(),
        seed.acquisition().receipt().receipt().operation().clone(),
        DirectHttpOutputSchemas::new(
            schema("com.cascadinglabs.yosoi.corpus-b-source"),
            schema("com.cascadinglabs.yosoi.corpus-b-source-representation"),
            Some(schema("com.cascadinglabs.yosoi.corpus-b-network")),
            Some(schema("com.cascadinglabs.yosoi.corpus-b-decoded")),
        ),
    )
    .unwrap()
}

const fn at() -> DateTime<Utc> {
    DateTime::from_timestamp(1_700_000_000, 0).unwrap()
}

fn coded(bytes: &[u8], encoding: Option<&str>, splits: &[usize]) -> Response {
    let mut raw_headers = vec![b"Content-Type: text/plain; charset=utf-8".to_vec()];
    if let Some(value) = encoding {
        raw_headers.push(format!("Content-Encoding: {value}").into_bytes());
    }
    raw_headers.push(format!("Content-Length: {}", bytes.len()).into_bytes());
    let mut chunks = Vec::new();
    let mut start = 0;
    for end in splits.iter().copied().chain(once(bytes.len())) {
        chunks.push(bytes.get(start..end).unwrap().to_vec());
        start = end;
    }
    Response {
        raw_headers,
        chunks,
        ..Response::bytes(200, None, b"")
    }
}

fn source(capture: &DirectHttpCapture) -> (&SourceArtifact, &[u8]) {
    let artifact = capture
        .bundle()
        .capture()
        .artifacts()
        .results()
        .source()
        .artifacts()
        .unwrap()
        .first()
        .unwrap();
    let payload = capture
        .bundle()
        .payload(artifact.reference().into())
        .unwrap();
    (artifact, payload)
}

#[tokio::test]
async fn fixed_content_codings_decode_to_independent_representation() {
    let cases = [
        ("identity", CODING_PLAIN, Some("identity"), &[][..]),
        ("gzip", CODING_GZIP, Some("gzip"), &[1, 9, 31][..]),
        ("br", CODING_BR, Some("br"), &[1, 4, 17][..]),
        ("zlib", CODING_ZLIB, Some("deflate"), &[2, 13, 29][..]),
        (
            "stacked",
            CODING_STACKED,
            Some("br, deflate"),
            &[1, 7, 23, 40][..],
        ),
        ("absent", CODING_PLAIN, None, &[3, 11][..]),
    ];
    let service = FixtureService::start(
        Protocol::Http,
        cases.iter().map(|(name, bytes, coding, splits)| {
            (format!("/{name}"), coded(bytes, *coding, splits))
        }),
    )
    .await;
    for (name, encoded_bytes, _, _) in cases {
        let capture = capture_direct_http_at(
            spec(
                &service.url(&format!("/{name}")),
                u64::try_from(encoded_bytes.len()).unwrap(),
                u64::try_from(CODING_PLAIN.len()).unwrap(),
            ),
            &CancellationToken::new(),
            at(),
        )
        .await
        .unwrap();
        let (artifact, payload) = source(&capture);
        assert_eq!(payload, CODING_PLAIN, "{name} representation");
        assert_eq!(
            artifact.metadata().content_digest().unwrap().to_string(),
            CODING_PLAIN_SHA256
        );
        assert_eq!(
            artifact.metadata().record().availability(),
            ArtifactAvailability::Retained
        );
        assert_eq!(capture.response().status(), 200);
    }
    service.shutdown().await;
}

#[tokio::test]
async fn encoded_and_representation_limits_have_exact_boundaries() {
    let routes = [
        (
            "/encoded-exact".into(),
            coded(CODING_GZIP, Some("gzip"), &[8, 27]),
        ),
        (
            "/encoded-short".into(),
            coded(CODING_GZIP, Some("gzip"), &[8, 27]),
        ),
        (
            "/representation-exact".into(),
            coded(CODING_GZIP, Some("gzip"), &[8, 27]),
        ),
        (
            "/representation-short".into(),
            coded(CODING_GZIP, Some("gzip"), &[8, 27]),
        ),
    ];
    let service = FixtureService::start(Protocol::Http, routes).await;
    let exact = capture_direct_http_at(
        spec(&service.url("/encoded-exact"), 54, 34),
        &CancellationToken::new(),
        at(),
    )
    .await
    .unwrap();
    assert_eq!(source(&exact).1, CODING_PLAIN);
    let short = capture_direct_http_at(
        spec(&service.url("/encoded-short"), 53, 34),
        &CancellationToken::new(),
        at(),
    )
    .await
    .unwrap();
    assert_eq!(
        source(&short).0.metadata().record().availability(),
        ArtifactAvailability::Truncated
    );
    let exact = capture_direct_http_at(
        spec(&service.url("/representation-exact"), 54, 34),
        &CancellationToken::new(),
        at(),
    )
    .await
    .unwrap();
    assert_eq!(source(&exact).1, CODING_PLAIN);
    let short = capture_direct_http_at(
        spec(&service.url("/representation-short"), 54, 33),
        &CancellationToken::new(),
        at(),
    )
    .await
    .unwrap();
    assert_eq!(
        source(&short).0.metadata().record().availability(),
        ArtifactAvailability::Truncated
    );
    assert_eq!(source(&short).1.len(), 33);
    service.shutdown().await;
}

#[tokio::test]
async fn malformed_and_unsupported_codings_are_terminal_values_without_a_bundle_leak() {
    let malformed = &CODING_GZIP[..CODING_GZIP.len() - 4];
    let service = FixtureService::start(
        Protocol::Http,
        [
            ("/malformed".into(), coded(malformed, Some("gzip"), &[10])),
            (
                "/unsupported".into(),
                coded(CODING_PLAIN, Some("compress"), &[7]),
            ),
            (
                "/bad-header".into(),
                coded(CODING_PLAIN, Some("gzip,,br"), &[7]),
            ),
        ],
    )
    .await;
    for path in ["/malformed", "/unsupported", "/bad-header"] {
        let capture = capture_direct_http_at(
            spec(&service.url(path), 1_000, 1_000),
            &CancellationToken::new(),
            at(),
        )
        .await
        .unwrap();
        assert_eq!(
            capture.bundle().capture().completeness(),
            CaptureCompleteness::Incomplete
        );
        let family = capture.bundle().capture().artifacts().results().source();
        if path == "/malformed" {
            let artifact = family.artifacts().unwrap().first().unwrap();
            assert_eq!(
                artifact.metadata().record().availability(),
                ArtifactAvailability::Truncated
            );
            assert!(
                !source(&capture).1.is_empty(),
                "decoder output before malformed trailer is retained"
            );
        } else {
            assert!(matches!(family, ArtifactFamilyResult::Unavailable { .. }));
            assert!(capture.source_facts().is_none());
        }
    }
    service.shutdown().await;
}

#[tokio::test]
async fn fixture_https_exercises_public_untrusted_certificate_failure_path() {
    let service = FixtureService::start(
        Protocol::Https,
        [(
            "/secure".into(),
            Response::bytes(200, Some("text/plain"), b"secret-canary-body"),
        )],
    )
    .await;
    let error = capture_direct_http_at(
        spec(&service.url("/secure"), 1024, 1024),
        &CancellationToken::new(),
        at(),
    )
    .await
    .unwrap_err();
    let text = format!("{error} {error:?}");
    assert!(!text.contains("secret-canary-body"));
    assert!(matches!(error, DirectHttpCaptureError::Transport(_)));
    service.shutdown().await;
}
