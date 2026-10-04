use std::time::Duration;

use chrono::{DateTime, Utc};
use tokio_util::sync::CancellationToken;
use yosoi_types::Sha256Digest;
use yosoi_web_capture_direct_http::{
    BodyTerminal, CaptureTermination, InterruptionInitiator, ResponseBodyOutcome,
    consume_response_body, execute_direct_http_at,
};

use super::support::{brotli, consume, gzip, retained, serve, spec, wire, zlib};

#[allow(
    clippy::needless_pass_by_value,
    reason = "the terminal-outcome assertion consumes its fixture so it cannot be reused after final verification"
)]
fn assert_malformed_after_output(outcome: ResponseBodyOutcome) {
    let source = outcome.payload().retained_source().unwrap();
    assert_ne!(source.bytes().len(), 0);
    assert_eq!(source.digest(), Sha256Digest::digest(source.bytes()));
    assert_eq!(outcome.terminal(), BodyTerminal::MalformedCoding);
}

fn assert_unavailable(outcome: &ResponseBodyOutcome, terminal: BodyTerminal) {
    assert!(matches!(
        outcome.payload().state(),
        yosoi_web_capture_direct_http::AcquiredPayloadState::Unavailable { .. }
    ));
    assert_eq!(outcome.terminal(), terminal);
}

#[tokio::test]
async fn malformed_codings_before_output_are_unavailable() {
    let cases: [(&str, &[u8]); 3] = [
        ("gzip", b"bad gzip"),
        ("br", b"bad brotli"),
        ("deflate", b"bad zlib"),
    ];
    for (coding, bytes) in cases {
        let outcome = consume(
            vec![(wire(Some(coding), bytes), Duration::ZERO)],
            100,
            100,
            2_000_000,
            CancellationToken::new(),
        )
        .await
        .0;
        assert_unavailable(&outcome, BodyTerminal::MalformedCoding);
    }
}

#[tokio::test]
async fn transport_disconnect_before_output_is_unavailable() {
    let response = b"HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\n".to_vec();
    let outcome = consume(
        vec![(response, Duration::ZERO)],
        100,
        100,
        2_000_000,
        CancellationToken::new(),
    )
    .await
    .0;
    assert_unavailable(&outcome, BodyTerminal::Disconnect);
}

#[tokio::test]
async fn complete_empty_body_is_retained() {
    let outcome = consume(
        vec![(wire(None, b""), Duration::ZERO)],
        100,
        100,
        2_000_000,
        CancellationToken::new(),
    )
    .await
    .0;
    retained(outcome, b"", 0, BodyTerminal::Complete);
}

#[tokio::test]
async fn unsupported_coding_is_atomic_unavailable() {
    let outcome = consume(
        vec![(wire(Some("zstd"), b"body"), Duration::ZERO)],
        100,
        100,
        2_000_000,
        CancellationToken::new(),
    )
    .await
    .0;
    assert_unavailable(&outcome, BodyTerminal::UnsupportedCoding);
    assert_eq!(outcome.content_coded_bytes(), 0);
}

#[tokio::test]
async fn malformed_repeated_content_encoding_is_atomic_unavailable() {
    let response = b"HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\nContent-Encoding: \r\nContent-Length: 1\r\n\r\nx".to_vec();
    let outcome = consume(
        vec![(response, Duration::ZERO)],
        100,
        100,
        2_000_000,
        CancellationToken::new(),
    )
    .await
    .0;
    assert_unavailable(&outcome, BodyTerminal::MalformedHeader);
}

#[tokio::test]
async fn malformed_gzip_after_partial_output() {
    let payload = deterministic_payload(200_000);
    let mut encoded = gzip(&payload).await;
    encoded.truncate(encoded.len() - 5);
    let outcome = consume(
        vec![(wire(Some("gzip"), &encoded), Duration::ZERO)],
        500_000,
        500_000,
        2_000_000,
        CancellationToken::new(),
    )
    .await
    .0;
    assert_malformed_after_output(outcome);
}

#[tokio::test]
async fn malformed_brotli_after_partial_output() {
    let payload = deterministic_payload(200_000);
    let mut encoded = brotli(&payload).await;
    encoded.truncate(encoded.len() - 1);
    let outcome = consume(
        vec![(wire(Some("br"), &encoded), Duration::ZERO)],
        500_000,
        500_000,
        2_000_000,
        CancellationToken::new(),
    )
    .await
    .0;
    assert_malformed_after_output(outcome);
}

#[tokio::test]
async fn malformed_zlib_after_partial_output() {
    let payload = deterministic_payload(200_000);
    let mut encoded = zlib(&payload).await;
    encoded.truncate(encoded.len() - 2);
    let outcome = consume(
        vec![(wire(Some("deflate"), &encoded), Duration::ZERO)],
        500_000,
        500_000,
        2_000_000,
        CancellationToken::new(),
    )
    .await
    .0;
    assert_malformed_after_output(outcome);
}

#[tokio::test]
async fn identity_http_premature_eof_is_disconnect() {
    let response = b"HTTP/1.1 200 OK\r\nContent-Length: 9\r\n\r\nprefix".to_vec();
    let outcome = consume(
        vec![(response, Duration::ZERO)],
        100,
        100,
        2_000_000,
        CancellationToken::new(),
    )
    .await
    .0;
    retained(outcome, b"prefix", 6, BodyTerminal::Disconnect);
}

#[tokio::test]
async fn zlib_http_premature_eof_is_disconnect() {
    let payload = deterministic_payload(20_000);
    let encoded = zlib(&payload).await;
    let partial = &encoded[..encoded.len() - 2];
    let head = format!(
        "HTTP/1.1 200 OK\r\nContent-Encoding: deflate\r\nContent-Length: {}\r\n\r\n",
        encoded.len()
    );
    let outcome = consume(
        vec![([head.as_bytes(), partial].concat(), Duration::ZERO)],
        100_000,
        100_000,
        2_000_000,
        CancellationToken::new(),
    )
    .await
    .0;
    assert!(outcome.payload().retained_source().is_some());
    assert_eq!(outcome.terminal(), BodyTerminal::Disconnect);
}

#[tokio::test]
async fn complete_length_truncated_zlib_is_malformed_coding() {
    let payload = deterministic_payload(20_000);
    let mut encoded = zlib(&payload).await;
    encoded.truncate(encoded.len() - 2);
    assert_malformed_after_output(
        consume(
            vec![(wire(Some("deflate"), &encoded), Duration::ZERO)],
            100_000,
            100_000,
            2_000_000,
            CancellationToken::new(),
        )
        .await
        .0,
    );
}

#[tokio::test]
async fn cancellation_after_partial_output_stops_reads_and_lifecycle() {
    let token = CancellationToken::new();
    let cancel = token.clone();
    tokio::spawn(async move {
        tokio::time::sleep(Duration::from_millis(40)).await;
        cancel.cancel();
    });
    let head = b"HTTP/1.1 200 OK\r\nContent-Length: 10000002\r\n\r\nab".to_vec();
    let (outcome, lifecycle, server) = consume(
        vec![
            (head, Duration::ZERO),
            (vec![b'x'; 10_000_000], Duration::from_millis(200)),
        ],
        20_000_000,
        20_000_000,
        2_000_000,
        token,
    )
    .await;
    retained(outcome, b"ab", 2, BodyTerminal::Cancelled);
    let Some(CaptureTermination::Interrupted(evidence)) = lifecycle.termination() else {
        panic!("expected interruption")
    };
    assert_eq!(evidence.initiator(), InterruptionInitiator::Caller);
    assert!(lifecycle.observed_through().as_microseconds() < 2_000_000);
    assert_eq!(server.join().unwrap(), 1);
}

#[tokio::test]
async fn simultaneous_ready_deadline_precedes_cancellation_consistently() {
    let (url, server) = serve(vec![(wire(None, b"body"), Duration::ZERO)]);
    let pending = execute_direct_http_at(
        spec(&url, 100, 100, 100_000),
        &CancellationToken::new(),
        DateTime::<Utc>::from_timestamp(1_700_000_000, 0).unwrap(),
    )
    .await
    .unwrap();
    tokio::time::sleep(Duration::from_millis(150)).await;
    let token = CancellationToken::new();
    token.cancel();
    let (outcome, lifecycle, _, _, _) = Box::pin(consume_response_body(pending, &token))
        .await
        .unwrap();
    assert_unavailable(&outcome, BodyTerminal::Deadline);
    assert!(matches!(
        lifecycle.termination(),
        Some(CaptureTermination::DeadlineReached { .. })
    ));
    assert_eq!(lifecycle.observed_through().as_microseconds(), 100_000);
    let _ = server.join();
}

#[tokio::test]
async fn body_deadline_after_partial_output_stops_at_exact_limit() {
    let head = b"HTTP/1.1 200 OK\r\nContent-Length: 10000002\r\n\r\nab".to_vec();
    let (outcome, lifecycle, server) = consume(
        vec![
            (head, Duration::ZERO),
            (vec![b'x'; 10_000_000], Duration::from_millis(200)),
        ],
        20_000_000,
        20_000_000,
        50_000,
        CancellationToken::new(),
    )
    .await;
    retained(outcome, b"ab", 2, BodyTerminal::Deadline);
    assert!(matches!(
        lifecycle.termination(),
        Some(CaptureTermination::DeadlineReached { .. })
    ));
    assert_eq!(lifecycle.observed_through().as_microseconds(), 50_000);
    assert_eq!(server.join().unwrap(), 1);
}

fn deterministic_payload(length: usize) -> Vec<u8> {
    (0..length)
        .map(|index| ((index.wrapping_mul(31).wrapping_add(index / 251)) % 256) as u8)
        .collect()
}
