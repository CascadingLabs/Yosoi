#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    reason = "static test fixtures"
)]

use std::{error::Error, sync::Arc, time::Duration};

use chrono::{DateTime, Utc};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
    task::yield_now,
    time::sleep,
};
use tokio_rustls::{
    TlsAcceptor,
    rustls::{
        ServerConfig,
        pki_types::{CertificateDer, PrivateKeyDer, PrivatePkcs8KeyDer},
    },
};
use tokio_util::sync::CancellationToken;
use wreq::{redirect::Policy, tls::trust::CertStore};
use yosoi_types::{Schema, SchemaId, SchemaVersion};

use crate::{
    AcceptedSourceFormat, AcceptedSourceFormats, ArtifactRequest, ByteLimit, CaptureDeadline,
    DirectHttpAcquisition, DirectHttpContentLimits, DirectHttpOutputSchemas,
    DirectHttpRedirectPolicy, DirectHttpTransportProfile, HttpSessionUse, ObservationLimits,
    ObservationPolicy, ObservedContentLength, ObservedHeaderValue, RequestedWebTarget,
    ResolvedDirectHttpCaptureSpec, SettlementPolicy, SourceRetentionPolicy,
    UnsupportedSourceFormatBehavior, WebAcquisitionStrategy, WebArtifactRequestSet,
    WebCaptureRequest, WebCaptureWire,
};

use super::{execute_direct_http_with_client_at, wreq_adapter_producer};
use crate::direct_http_orchestration::capture_direct_http_with_client_at;

#[path = "tests/sink.rs"]
mod sink_tests;

const CERT: &[u8] = include_bytes!("../tests/fixtures/direct-http-tls/cert.der");
const KEY: &[u8] = include_bytes!("../tests/fixtures/direct-http-tls/key.der");

fn named_schema(name: &str) -> Schema {
    Schema::new(
        SchemaId::new(name).unwrap(),
        SchemaVersion::try_from(1).unwrap(),
    )
}

pub(super) fn spec(url: &str) -> ResolvedDirectHttpCaptureSpec {
    spec_with_options(url, DirectHttpRedirectPolicy::Disabled, 2_000_000, None)
}

pub(super) fn spec_with_redirects(
    url: &str,
    redirects: DirectHttpRedirectPolicy,
    maximum_elapsed: u64,
) -> ResolvedDirectHttpCaptureSpec {
    spec_with_options(url, redirects, maximum_elapsed, None)
}

pub(super) fn spec_with_byte_limit(
    url: &str,
    byte_limit: Option<u64>,
) -> ResolvedDirectHttpCaptureSpec {
    spec_with_options(
        url,
        DirectHttpRedirectPolicy::Disabled,
        2_000_000,
        byte_limit,
    )
}

fn spec_with_options(
    url: &str,
    redirects: DirectHttpRedirectPolicy,
    maximum_elapsed: u64,
    byte_limit: Option<u64>,
) -> ResolvedDirectHttpCaptureSpec {
    let capture = WebCaptureWire::from_json(include_bytes!(
        "../tests/fixtures/web-capture/complete-v1.json"
    ))
    .unwrap();
    let request = WebCaptureRequest::new(
        capture.acquisition().request().capture_id(),
        RequestedWebTarget::parse(url).unwrap(),
        WebAcquisitionStrategy::DirectHttp(DirectHttpAcquisition::new(
            DirectHttpTransportProfile::Standard,
            HttpSessionUse::Isolated,
        )),
    );
    let artifacts = WebArtifactRequestSet::new(
        ArtifactRequest::Required,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
    );
    let limit = ByteLimit::try_from(1_000_000_u64).unwrap();
    let schema = Schema::new(
        SchemaId::new("com.cascadinglabs.yosoi.web-source").unwrap(),
        SchemaVersion::try_from(1).unwrap(),
    );
    ResolvedDirectHttpCaptureSpec::new(
        request,
        artifacts,
        ObservationPolicy::new(
            ObservationLimits::new(
                CaptureDeadline::try_from(maximum_elapsed).unwrap(),
                None,
                byte_limit.map(|value| ByteLimit::try_from(value).unwrap()),
            ),
            SettlementPolicy::Disabled,
        ),
        DirectHttpContentLimits::new(limit, limit, limit),
        redirects,
        AcceptedSourceFormats::new([AcceptedSourceFormat::Html]).unwrap(),
        UnsupportedSourceFormatBehavior::RetainAndReport,
        SourceRetentionPolicy::Representation,
        wreq_adapter_producer().unwrap(),
        capture
            .acquisition()
            .receipt()
            .receipt()
            .operation()
            .clone(),
        DirectHttpOutputSchemas::new(
            schema,
            named_schema("com.cascadinglabs.yosoi.test-source-representation"),
            None,
            None,
        ),
    )
    .unwrap()
}

fn wall_clock() -> DateTime<Utc> {
    DateTime::from_timestamp(1_700_000_000, 0).unwrap()
}

async fn tls_server(response: Vec<u8>) -> String {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let config = ServerConfig::builder()
        .with_no_client_auth()
        .with_single_cert(
            vec![CertificateDer::from(CERT.to_vec())],
            PrivateKeyDer::Pkcs8(PrivatePkcs8KeyDer::from(KEY.to_vec())),
        )
        .unwrap();
    tokio::spawn(async move {
        let (stream, _) = listener.accept().await.unwrap();
        let mut stream = TlsAcceptor::from(Arc::new(config))
            .accept(stream)
            .await
            .unwrap();
        let mut request = [0_u8; 1024];
        let _ = stream.read(&mut request).await;
        stream.write_all(&response).await.unwrap();
    });
    format!("https://localhost:{}/capture?token=SECRET", address.port())
}

fn pinned_client() -> wreq::Client {
    let cert_store = CertStore::from_der_certs([CERT]).unwrap();
    wreq::Client::builder()
        .redirect(Policy::none())
        .referer(false)
        .no_gzip()
        .no_brotli()
        .no_deflate()
        .no_zstd()
        .tls_cert_store(cert_store)
        .build()
        .unwrap()
}

#[tokio::test]
async fn embedded_certificate_https_runs_full_orchestration_chain() {
    let url = tls_server(
        b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: 13\r\n\r\n<h1>okay</h1>"
            .to_vec(),
    )
    .await;
    let capture = capture_direct_http_with_client_at(
        spec(&url),
        &CancellationToken::new(),
        wall_clock(),
        pinned_client(),
    )
    .await
    .unwrap();
    assert_eq!(capture.response().status(), 200);
    assert_eq!(capture.response().final_url().as_str(), url);
    let source = capture
        .bundle()
        .capture()
        .artifacts()
        .results()
        .source()
        .artifacts()
        .unwrap()
        .first()
        .unwrap();
    assert_eq!(
        capture.bundle().payload(source.reference().into()),
        Some(b"<h1>okay</h1>".as_slice())
    );
}

#[tokio::test]
async fn embedded_certificate_https_executes_without_external_services() {
    let url = tls_server(
        b"HTTP/1.1 201 Created\r\nContent-Type: text/plain\r\nContent-Length: 4\r\n\r\ndata"
            .to_vec(),
    )
    .await;
    let pending = execute_direct_http_with_client_at(
        spec(&url),
        &CancellationToken::new(),
        wall_clock(),
        pinned_client(),
        super::DirectHttpRedirectTargetPolicy::AllowHttpAndHttps,
    )
    .await
    .unwrap();
    assert_eq!(pending.facts().status(), 201);
    assert_eq!(
        pending.facts().content_length(),
        &ObservedContentLength::Value(4)
    );
    assert_eq!(
        pending.facts().protocol(),
        super::DirectHttpProtocol::Http11
    );
    assert!(pending.lifecycle().termination().is_none());
    let producer = wreq_adapter_producer().unwrap();
    assert_eq!(
        producer.id().as_str(),
        "com.cascadinglabs.yosoi.wreq-direct-http"
    );
    assert_eq!(producer.version().as_str(), env!("CARGO_PKG_VERSION"));
    assert_eq!(pending.identity().dependency().crate_name(), "wreq");
    assert_eq!(pending.identity().dependency().version(), "0.16.1");
    assert_eq!(pending.identity().capabilities().producer(), &producer);
    match pending.identity().environment() {
        crate::CaptureEnvironment::Http(environment) => {
            assert_eq!(environment.client(), &producer);
            assert!(matches!(
                environment.user_agent(),
                crate::EnvironmentValue::Unavailable { .. }
            ));
        }
        other @ crate::CaptureEnvironment::Browser(_) => {
            panic!("unexpected environment: {other:?}")
        }
    }
    assert!(!format!("{pending:?}").contains("SECRET"));
    let (response, _, _, resolution, _, _, _) = pending.into_parts();
    assert!(resolution.final_url().as_observed().is_some());
    assert_eq!(response.text().await.unwrap(), "data");
}

#[tokio::test]
async fn untrusted_certificate_preserves_wreq_connect_classification() {
    let url = tls_server(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n".to_vec()).await;
    let failure =
        super::execute_direct_http_at(spec(&url), &CancellationToken::new(), wall_clock())
            .await
            .unwrap_err();

    assert_eq!(
        failure.error().kind(),
        super::DirectHttpTransportErrorKind::Connect
    );
    assert!(failure.error().source().is_some());
    assert!(failure.lifecycle().termination().is_some());
    assert!(!format!("{failure:?}").contains("SECRET"));
}

#[test]
fn invalid_tls_configuration_maps_wreqs_typed_tls_error() {
    let error = CertStore::builder()
        .add_der_cert(b"not a certificate")
        .build()
        .err()
        .unwrap();
    assert!(error.is_tls());
    let mapped = super::DirectHttpTransportError::from_wreq(error);
    assert_eq!(mapped.kind(), super::DirectHttpTransportErrorKind::Tls);
    assert!(mapped.source().is_some());
}

#[tokio::test]
async fn response_head_observations_are_bounded_and_body_remains_unconsumed() {
    let long = "x".repeat(1_025);
    let response = format!(
        "HTTP/1.1 206 Partial Content\r\nContent-Type: {long}\r\nContent-Encoding: identity\r\nContent-Length: 4\r\n\r\nbody"
    ).into_bytes();
    let url = tls_server(response).await;
    let pending = execute_direct_http_with_client_at(
        spec(&url),
        &CancellationToken::new(),
        wall_clock(),
        pinned_client(),
        super::DirectHttpRedirectTargetPolicy::AllowHttpAndHttps,
    )
    .await
    .unwrap();
    assert_eq!(pending.facts().status(), 206);
    assert_eq!(
        pending.facts().content_type(),
        &ObservedHeaderValue::TooLong
    );
    assert_eq!(
        pending.facts().content_encoding(),
        &ObservedHeaderValue::from_text("identity")
    );
    assert_eq!(
        pending.facts().content_length(),
        &ObservedContentLength::Value(4)
    );
}

#[test]
fn observed_header_debug_redacts_attacker_controlled_values() {
    for attacker in [
        "text/html; token=CONTENT_TYPE_SECRET",
        "gzip; token=ENCODING_SECRET",
    ] {
        let observed = ObservedHeaderValue::from_text(attacker);
        let debug = format!("{observed:?}");
        assert_eq!(debug, "Value([redacted])");
        assert!(!debug.contains(attacker));
    }
}

#[test]
fn invalid_and_too_long_header_values_are_classified_without_copying_them() {
    use wreq::header::{CONTENT_ENCODING, CONTENT_LENGTH, HeaderMap, HeaderValue};

    let mut headers = HeaderMap::new();
    headers.insert(CONTENT_ENCODING, HeaderValue::from_bytes(&[0xff]).unwrap());
    headers.insert(CONTENT_LENGTH, HeaderValue::from_static("not-a-number"));
    assert_eq!(
        super::response::header(&headers, CONTENT_ENCODING),
        ObservedHeaderValue::InvalidEncoding
    );
    assert_eq!(
        super::response::content_length(&headers),
        ObservedContentLength::Invalid
    );
    headers.insert(
        CONTENT_LENGTH,
        HeaderValue::from_static("123456789012345678901"),
    );
    assert_eq!(
        super::response::content_length(&headers),
        ObservedContentLength::TooLong
    );
}

#[tokio::test]
async fn cancellation_wins_while_tls_request_is_pending() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    tokio::spawn(async move {
        let (_stream, _) = listener.accept().await.unwrap();
        sleep(Duration::from_secs(2)).await;
    });
    let token = CancellationToken::new();
    let trigger = token.clone();
    tokio::spawn(async move {
        yield_now().await;
        trigger.cancel();
    });
    let failure = execute_direct_http_with_client_at(
        spec(&format!("https://localhost:{}/pending", address.port())),
        &token,
        wall_clock(),
        pinned_client(),
        super::DirectHttpRedirectTargetPolicy::AllowHttpAndHttps,
    )
    .await
    .unwrap_err();
    assert_eq!(
        failure.error().kind(),
        super::DirectHttpTransportErrorKind::Cancelled
    );
    assert!(failure.lifecycle().termination().is_some());
}
