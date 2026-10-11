use std::{
    io::{Read, Write},
    net::TcpListener,
    thread,
    time::Duration,
};

use crate::internal::direct_http::{
    AcceptedSourceFormat, AcceptedSourceFormats, ArtifactRequest, BodyTerminal,
    BoundedAcquisitionLifecycle, ByteLimit, CaptureDeadline, DirectHttpAcquisition,
    DirectHttpContentLimits, DirectHttpOutputSchemas, DirectHttpRedirectPolicy,
    DirectHttpTransportProfile, HttpSessionUse, ObservationLimits, ObservationPolicy,
    RequestedWebTarget, ResolvedDirectHttpCaptureSpec, ResponseBodyOutcome, RetainedSourceExtent,
    SettlementPolicy, SourceRetentionPolicy, UnsupportedSourceFormatBehavior,
    WebAcquisitionStrategy, WebArtifactRequestSet, WebCaptureRequest, WebCaptureWire,
    consume_response_body, execute_direct_http_at,
};
use crate::internal::types::{Schema, SchemaId, SchemaVersion, Sha256Digest};
use async_compression::tokio::write::{BrotliEncoder, GzipEncoder, ZlibEncoder};
use chrono::{DateTime, Utc};
use tokio::io::AsyncWriteExt;
use tokio_util::sync::CancellationToken;

fn named_schema(name: &str) -> Schema {
    Schema::new(
        SchemaId::new(name).unwrap(),
        SchemaVersion::try_from(1).unwrap(),
    )
}

pub fn spec(url: &str, encoded: u64, decoded: u64, timeout: u64) -> ResolvedDirectHttpCaptureSpec {
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
    let schema = Schema::new(
        SchemaId::new("com.cascadinglabs.yosoi.web-source").unwrap(),
        SchemaVersion::try_from(1).unwrap(),
    );
    ResolvedDirectHttpCaptureSpec::new(
        request,
        artifacts,
        ObservationPolicy::new(
            ObservationLimits::new(CaptureDeadline::try_from(timeout).unwrap(), None, None),
            SettlementPolicy::Disabled,
        ),
        DirectHttpContentLimits::new(
            ByteLimit::try_from(encoded).unwrap(),
            ByteLimit::try_from(decoded).unwrap(),
            ByteLimit::try_from(decoded).unwrap(),
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
            schema,
            named_schema("com.cascadinglabs.yosoi.body-source-representation"),
            None,
            None,
        ),
    )
    .unwrap()
}

pub fn serve(parts: Vec<(Vec<u8>, Duration)>) -> (String, thread::JoinHandle<usize>) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    let handle = thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        stream
            .set_write_timeout(Some(Duration::from_millis(100)))
            .unwrap();
        let mut request = [0; 1024];
        let _ = stream.read(&mut request);
        let mut writes = 0;
        for (part, delay) in parts {
            thread::sleep(delay);
            if stream.write_all(&part).is_err() {
                break;
            }
            writes += 1;
        }
        writes
    });
    (format!("http://{address}/body"), handle)
}

pub async fn consume(
    parts: Vec<(Vec<u8>, Duration)>,
    encoded: u64,
    decoded: u64,
    timeout: u64,
    cancellation: CancellationToken,
) -> (
    ResponseBodyOutcome,
    BoundedAcquisitionLifecycle,
    thread::JoinHandle<usize>,
) {
    let (url, handle) = serve(parts);
    let pending = execute_direct_http_at(
        spec(&url, encoded, decoded, timeout),
        &CancellationToken::new(),
        DateTime::<Utc>::from_timestamp(1_700_000_000, 0).unwrap(),
    )
    .await
    .unwrap();
    let (outcome, lifecycle, _, _, _) = Box::pin(consume_response_body(pending, &cancellation))
        .await
        .unwrap();
    (outcome, lifecycle, handle)
}

pub fn wire(encoding: Option<&str>, body: &[u8]) -> Vec<u8> {
    let encoding = encoding
        .map(|value| format!("Content-Encoding: {value}\r\n"))
        .unwrap_or_default();
    [
        format!(
            "HTTP/1.1 200 OK\r\n{encoding}Content-Length: {}\r\n\r\n",
            body.len()
        )
        .as_bytes(),
        body,
    ]
    .concat()
}

pub async fn gzip(bytes: &[u8]) -> Vec<u8> {
    let mut encoder = GzipEncoder::new(Vec::new());
    encoder.write_all(bytes).await.unwrap();
    encoder.shutdown().await.unwrap();
    encoder.into_inner()
}

pub async fn brotli(bytes: &[u8]) -> Vec<u8> {
    let mut encoder = BrotliEncoder::new(Vec::new());
    encoder.write_all(bytes).await.unwrap();
    encoder.shutdown().await.unwrap();
    encoder.into_inner()
}

pub async fn zlib(bytes: &[u8]) -> Vec<u8> {
    let mut encoder = ZlibEncoder::new(Vec::new());
    encoder.write_all(bytes).await.unwrap();
    encoder.shutdown().await.unwrap();
    encoder.into_inner()
}

#[allow(
    clippy::needless_pass_by_value,
    reason = "the terminal-outcome assertion consumes its fixture so it cannot be reused after final verification"
)]
pub fn retained(
    outcome: ResponseBodyOutcome,
    expected: &[u8],
    encoded: usize,
    terminal: BodyTerminal,
) {
    let source = outcome.payload().retained_source().unwrap();
    assert_eq!(source.bytes(), expected);
    assert_eq!(source.digest(), Sha256Digest::digest(expected));
    assert_eq!(outcome.content_coded_bytes(), encoded as u64);
    assert_eq!(outcome.terminal(), terminal);
    let expected_extent = if terminal == BodyTerminal::Complete {
        RetainedSourceExtent::Complete
    } else {
        RetainedSourceExtent::Truncated
    };
    assert_eq!(source.extent(), expected_extent);
}
