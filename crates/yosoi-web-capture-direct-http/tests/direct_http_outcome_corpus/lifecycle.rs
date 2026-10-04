use crate::{
    fixture::{FixtureService, Protocol, Response, ResponseControl},
    support::*,
};
use std::sync::Arc;
use tokio::task::yield_now;
use tokio_util::sync::CancellationToken;
use yosoi_types::{ActivityOutcome, ArtifactAvailability, RetryDisposition};
use yosoi_web_capture_direct_http::*;

fn reason(family: &ArtifactFamilyResult<SourceArtifact>) -> Option<String> {
    match family {
        ArtifactFamilyResult::Partial { reason, .. }
        | ArtifactFamilyResult::Unavailable { reason } => Some(reason.to_string()),
        _ => None,
    }
}
fn terminal(capture: &DirectHttpCapture, expected: &str) {
    let web = capture.bundle().capture();
    assert_eq!(web.completeness(), CaptureCompleteness::Incomplete);
    assert_eq!(
        reason(web.artifacts().results().source()).as_deref(),
        Some(expected)
    );
    let receipt = web.acquisition().receipt().receipt();
    let signal = receipt.signal().unwrap();
    if expected == "web_capture.body.cancelled" {
        assert_eq!(receipt.outcome(), ActivityOutcome::Cancelled);
        assert_eq!(signal.retry(), RetryDisposition::Unknown);
    } else {
        assert_eq!(receipt.outcome(), ActivityOutcome::Partial);
        assert_eq!(signal.retry(), RetryDisposition::Retryable);
    }
    assert!(signal.code().as_str().starts_with("web_capture."));
    let state = web.observation().terminal_state();
    let difference = state
        .bytes()
        .admitted()
        .get()
        .checked_sub(state.bytes().retained().get())
        .unwrap();
    assert!(
        matches!(state.bytes().dropped(), MeasuredCount::Known(value) if value.get() == difference)
    );
    assert!(matches!(state.events().dropped(), MeasuredCount::Known(value) if value.get() == 0));
    assert_eq!(
        state.observed_through().as_microseconds(),
        web.observation().window().elapsed().as_microseconds()
    );
}

#[tokio::test]
async fn complete_empty_and_disconnect_before_or_after_output_map_exactly() {
    let disconnected = Response {
        raw_headers: vec![
            b"Content-Type: text/plain".to_vec(),
            b"Content-Length: 20".to_vec(),
        ],
        chunks: vec![b"prefix".to_vec()],
        close_after_chunks: Some(1),
        ..response(b"", None)
    };
    let before = Response {
        close_after_chunks: Some(0),
        ..disconnected.clone()
    };
    let service = FixtureService::start(
        Protocol::Http,
        [
            ("/empty".into(), response(b"", Some("text/plain"))),
            ("/before".into(), before),
            ("/after".into(), disconnected),
        ],
    )
    .await;
    let empty = capture_direct_http_at(
        spec(&service.url("/empty"), Options::default()),
        &CancellationToken::new(),
        at(),
    )
    .await
    .unwrap();
    assert_eq!(source(&empty).1, b"");
    assert!(matches!(
        empty.bundle().capture().artifacts().results().source(),
        ArtifactFamilyResult::Complete { .. }
    ));
    assert!(empty.source_representation_evidence().is_ok());
    let before = capture_direct_http_at(
        spec(&service.url("/before"), Options::default()),
        &CancellationToken::new(),
        at(),
    )
    .await
    .unwrap();
    assert!(matches!(
        before.bundle().capture().artifacts().results().source(),
        ArtifactFamilyResult::Unavailable { .. }
    ));
    assert!(matches!(
        before
            .bundle()
            .capture()
            .artifacts()
            .results()
            .source_representation(),
        ArtifactFamilyResult::Unavailable { .. }
    ));
    assert!(matches!(
        before.source_representation_evidence(),
        Err(DirectHttpReplayError::SourceRepresentationUnavailable)
    ));
    terminal(&before, "web_capture.body.disconnect");
    let after = capture_direct_http_at(
        spec(&service.url("/after"), Options::default()),
        &CancellationToken::new(),
        at(),
    )
    .await
    .unwrap();
    assert_eq!(source(&after).1, b"prefix");
    assert_eq!(
        source(&after).0.metadata().record().availability(),
        ArtifactAvailability::Truncated
    );
    assert!(after.source_representation_evidence().is_ok());
    terminal(&after, "web_capture.body.disconnect");
    service.shutdown().await;
}

#[tokio::test]
async fn representation_and_content_coded_limits_have_exact_accounting() {
    let service = FixtureService::start(
        Protocol::Http,
        [
            (
                "/representation".into(),
                response(b"abcdef", Some("text/plain")),
            ),
            ("/coded".into(), response(b"abcdef", Some("text/plain"))),
        ],
    )
    .await;
    let representation = capture_direct_http_at(
        spec(
            &service.url("/representation"),
            Options {
                representation: 5,
                ..Options::default()
            },
        ),
        &CancellationToken::new(),
        at(),
    )
    .await
    .unwrap();
    assert_eq!(source(&representation).1, b"abcde");
    terminal(&representation, "web_capture.body.representation_limit");
    let coded = capture_direct_http_at(
        spec(
            &service.url("/coded"),
            Options {
                encoded: 5,
                ..Options::default()
            },
        ),
        &CancellationToken::new(),
        at(),
    )
    .await
    .unwrap();
    assert_eq!(source(&coded).1, b"abcde");
    terminal(&coded, "web_capture.body.content_coded_limit");
    service.shutdown().await;
}

#[tokio::test]
async fn malformed_and_unsupported_coding_preserve_before_after_distinction() {
    let partial_gzip = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03K\xcb\xacHMQH\xceO\xc9";
    let coded = |bytes: &[u8], value: &[u8]| Response {
        raw_headers: vec![
            b"Content-Type: text/plain".to_vec(),
            [b"Content-Encoding: ".as_slice(), value].concat(),
            format!("Content-Length: {}", bytes.len()).into_bytes(),
        ],
        chunks: vec![bytes.to_vec()],
        ..response(b"", None)
    };
    let service = FixtureService::start(
        Protocol::Http,
        [
            ("/malformed".into(), coded(partial_gzip, b"gzip")),
            ("/unsupported".into(), coded(b"abcdef", b"compress")),
            ("/header".into(), coded(b"abcdef", b"gzip,,br")),
        ],
    )
    .await;
    for (path, expected) in [
        ("/malformed", "web_capture.body.malformed_coding"),
        ("/unsupported", "web_capture.body.unsupported_coding"),
        ("/header", "web_capture.body.malformed_header"),
    ] {
        let capture = capture_direct_http_at(
            spec(&service.url(path), Options::default()),
            &CancellationToken::new(),
            at(),
        )
        .await
        .unwrap();
        terminal(&capture, expected);
    }
    service.shutdown().await;
}

#[tokio::test]
async fn cancellation_before_head_and_after_output_is_coordinated_and_quiescent() {
    let before_control = Arc::new(ResponseControl {
        hold_before_head: true,
        ..ResponseControl::default()
    });
    let delayed = Response {
        control: Some(before_control.clone()),
        ..response(b"never", Some("text/plain"))
    };
    let after_control = Arc::new(ResponseControl {
        hold_after_chunks: true,
        ..ResponseControl::default()
    });
    let after = Response {
        raw_headers: vec![
            b"Content-Type: text/plain".to_vec(),
            b"Content-Length: 4".to_vec(),
        ],
        chunks: vec![b"ab".to_vec(), b"cd".to_vec()],
        control: Some(after_control.clone()),
        ..response(b"", None)
    };
    let service = FixtureService::start(
        Protocol::Http,
        [("/before".into(), delayed), ("/after".into(), after)],
    )
    .await;
    let cancellation = CancellationToken::new();
    let child = cancellation.clone();
    let requested = before_control.clone();
    let handle = tokio::spawn(async move {
        requested.requested.wait().await;
        child.cancel();
    });
    let error = capture_direct_http_at(
        spec(&service.url("/before"), Options::default()),
        &cancellation,
        at(),
    )
    .await
    .unwrap_err();
    handle.await.unwrap();
    assert!(matches!(error, DirectHttpCaptureError::Transport(_)));
    before_control.allow_head.signal();

    let cancellation = CancellationToken::new();
    let child = cancellation.clone();
    let written = after_control.clone();
    let handle = tokio::spawn(async move {
        written.chunk_written.wait().await;
        // Let the ready body-reader consume the delivered chunk without wall-clock timing.
        for _ in 0..16 {
            yield_now().await;
        }
        child.cancel();
        written.allow_next_chunk.signal();
    });
    let capture = capture_direct_http_at(
        spec(&service.url("/after"), Options::default()),
        &cancellation,
        at(),
    )
    .await
    .unwrap();
    handle.await.unwrap();
    terminal(&capture, "web_capture.body.cancelled");
    assert_eq!(source(&capture).1, b"ab");
    assert_eq!(service.requests().await.len(), 2);
    service.shutdown().await;
}
