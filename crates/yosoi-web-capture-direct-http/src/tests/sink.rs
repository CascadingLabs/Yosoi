use std::fmt;

use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;
use tokio_util::sync::CancellationToken;
use yosoi_types::{ActivityOutcome, Sha256Digest};

use super::super::body::{PayloadSink, SinkError, consume_with_sink};
use super::super::{consume_response_body, execute_direct_http_at};
use super::{spec, spec_with_byte_limit, wall_clock};
use crate::direct_http_orchestration::capture_direct_http_with_sink_at;
use crate::{BodyTerminal, CaptureTermination, DirectHttpCaptureError, ResponseBodyError};

async fn plain_server(body: &'static [u8]) -> String {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let mut request = [0; 1024];
        let _ = stream.read(&mut request).await;
        let head = format!("HTTP/1.1 200 OK\r\nContent-Length: {}\r\n\r\n", body.len());
        stream.write_all(head.as_bytes()).await.unwrap();
        stream.write_all(body).await.unwrap();
    });
    format!("http://{address}/")
}

struct FailingWriteSink;
impl fmt::Debug for FailingWriteSink {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("FailingWriteSink")
    }
}
impl PayloadSink for FailingWriteSink {
    fn write(&mut self, _bytes: &[u8]) -> Result<(), SinkError> {
        Err(SinkError::Operation)
    }
    fn commit(self: Box<Self>) -> Result<Vec<u8>, SinkError> {
        Err(SinkError::Operation)
    }
}

#[derive(Debug)]
struct FailingCommitSink(Vec<u8>);
impl PayloadSink for FailingCommitSink {
    fn write(&mut self, bytes: &[u8]) -> Result<(), SinkError> {
        self.0.extend_from_slice(bytes);
        Ok(())
    }
    fn commit(self: Box<Self>) -> Result<Vec<u8>, SinkError> {
        if self.0 == b"private until commit" {
            Err(SinkError::Operation)
        } else {
            Ok(self.0)
        }
    }
}

async fn assert_sink_failure(sink: Box<dyn PayloadSink>) {
    let url = plain_server(b"private until commit").await;
    let pending = execute_direct_http_at(spec(&url), &CancellationToken::new(), wall_clock())
        .await
        .unwrap();
    let retained_events_before = pending.lifecycle().retained_events();
    let retained_bytes_before = pending.lifecycle().retained_bytes();
    let cancellation = CancellationToken::new();
    let (outcome, lifecycle, _, _, _) = Box::pin(consume_with_sink(pending, &cancellation, sink))
        .await
        .unwrap();
    assert!(matches!(
        outcome.payload().state(),
        crate::AcquiredPayloadState::Unavailable { .. }
    ));
    assert_eq!(outcome.content_coded_bytes(), 20);
    assert_eq!(outcome.terminal(), BodyTerminal::SinkFailure);
    assert!(matches!(
        lifecycle.termination(),
        Some(CaptureTermination::Interrupted(_))
    ));
    let admitted_events = lifecycle.admitted_events();
    let retained_events = lifecycle.retained_events();
    let admitted_bytes = lifecycle.admitted_bytes();
    let retained_bytes = lifecycle.retained_bytes();
    assert_eq!(retained_events, retained_events_before);
    assert_eq!(retained_bytes, retained_bytes_before);
    assert!(admitted_events > 0);
    assert_eq!(admitted_bytes, 20);
}

#[tokio::test]
async fn failing_write_sink_publishes_no_bytes_and_stops_unsuccessfully() {
    assert_sink_failure(Box::new(FailingWriteSink)).await;
}

#[tokio::test]
async fn failing_commit_sink_publishes_no_bytes_and_stops_unsuccessfully() {
    assert_sink_failure(Box::new(FailingCommitSink(Vec::new()))).await;
}

#[tokio::test]
async fn exact_lifecycle_limit_precedes_a_tied_sink_write_failure() {
    let url = plain_server(b"six bytes beyond the lifecycle bound").await;
    let pending = execute_direct_http_at(
        spec_with_byte_limit(&url, Some(3)),
        &CancellationToken::new(),
        wall_clock(),
    )
    .await
    .unwrap();
    let cancellation = CancellationToken::new();
    let (outcome, lifecycle, _, _, _) = Box::pin(consume_with_sink(
        pending,
        &cancellation,
        Box::new(FailingWriteSink),
    ))
    .await
    .unwrap();
    assert!(matches!(
        outcome.payload().state(),
        crate::AcquiredPayloadState::Unavailable { .. }
    ));
    assert_eq!(outcome.terminal(), BodyTerminal::LifecycleLimit);
    assert!(matches!(
        lifecycle.termination(),
        Some(CaptureTermination::ByteLimitReached { byte_limit }) if byte_limit.get() == 3
    ));
    assert_eq!(lifecycle.admitted_bytes(), 3);
    assert_eq!(lifecycle.retained_bytes(), 0);
}

#[tokio::test]
async fn tied_limit_and_sink_failure_finalize_through_the_shared_kernel() {
    let url = plain_server(b"six bytes beyond the lifecycle bound").await;
    let capture = capture_direct_http_with_sink_at(
        spec_with_byte_limit(&url, Some(3)),
        &CancellationToken::new(),
        wall_clock(),
        Box::new(FailingWriteSink),
        false,
    )
    .await
    .unwrap();
    let web = capture.bundle().capture();
    assert!(matches!(
        web.observation().termination(),
        CaptureTermination::ByteLimitReached { byte_limit } if byte_limit.get() == 3
    ));
    assert!(web.artifacts().results().source().artifacts().is_none());
    let receipt = web.acquisition().receipt().receipt();
    assert_eq!(receipt.outcome(), ActivityOutcome::Partial);
    assert_eq!(
        receipt.signal().unwrap().code().as_str(),
        "capture.byte-limit"
    );
}

#[tokio::test]
async fn full_orchestration_maps_sink_failures_to_unavailable_without_payload() {
    let sinks: Vec<Box<dyn PayloadSink>> = vec![
        Box::new(FailingWriteSink),
        Box::new(FailingCommitSink(Vec::new())),
    ];
    for sink in sinks {
        let url = plain_server(b"private until commit").await;
        let capture = capture_direct_http_with_sink_at(
            spec(&url),
            &CancellationToken::new(),
            wall_clock(),
            sink,
            false,
        )
        .await
        .unwrap();
        assert!(
            capture
                .capture()
                .artifacts()
                .results()
                .source()
                .artifacts()
                .is_none()
        );
    }
}

#[tokio::test]
async fn full_orchestration_preserves_redacted_invariant_failure_context() {
    let url = plain_server(b"private until commit").await;
    let error = capture_direct_http_with_sink_at(
        spec(&url),
        &CancellationToken::new(),
        wall_clock(),
        Box::new(FailingCommitSink(Vec::new())),
        true,
    )
    .await
    .unwrap_err();
    let DirectHttpCaptureError::Body(failure) = error else {
        panic!("forced lifecycle failure must remain a body error")
    };
    assert!(matches!(failure.primary(), ResponseBodyError::Lifecycle(_)));
    assert_eq!(failure.facts().status(), 200);
    assert!(!format!("{:?}", failure.resolution()).is_empty());
    assert!(failure.lifecycle().observed_through().as_microseconds() > 0);
    assert!(!format!("{:?}", failure.identity()).is_empty());
    assert_eq!(failure.content_coded_bytes(), 20);
    assert!(failure.response_is_consumed());
    assert!(!failure.staged_body_is_publishable());
    let debug = format!("{failure:?}");
    assert!(!debug.contains("private until commit"));
}

#[tokio::test]
async fn lifecycle_byte_limit_incrementally_admits_only_the_available_prefix() {
    let url = plain_server(b"six bytes beyond the lifecycle bound").await;
    let pending = execute_direct_http_at(
        spec_with_byte_limit(&url, Some(3)),
        &CancellationToken::new(),
        wall_clock(),
    )
    .await
    .unwrap();
    let cancellation = CancellationToken::new();
    let (outcome, lifecycle, _, _, _) = Box::pin(consume_response_body(pending, &cancellation))
        .await
        .unwrap();
    let source = outcome.payload().retained_source().unwrap();
    assert_eq!(source.bytes(), b"six");
    assert_eq!(source.digest(), Sha256Digest::digest(b"six"));
    assert_eq!(outcome.terminal(), BodyTerminal::LifecycleLimit);
    assert!(matches!(
        lifecycle.termination(),
        Some(CaptureTermination::ByteLimitReached { byte_limit }) if byte_limit.get() == 3
    ));
}
