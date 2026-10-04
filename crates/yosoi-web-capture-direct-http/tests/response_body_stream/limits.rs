use std::time::Duration;

use tokio_util::sync::CancellationToken;
use yosoi_web_capture_direct_http::{BodyTerminal, ResponseBodyOutcome};

use super::support::{brotli, consume, gzip, retained, wire, zlib};

const fn terminal(outcome: &ResponseBodyOutcome) -> BodyTerminal {
    outcome.terminal()
}

#[tokio::test]
async fn encoded_exact_limit_completes_after_eof_probe() {
    let payload = b"exact";
    let response = wire(None, payload);
    retained(
        consume(
            vec![(response, Duration::ZERO)],
            payload.len() as u64,
            100,
            2_000_000,
            CancellationToken::new(),
        )
        .await
        .0,
        payload,
        payload.len(),
        BodyTerminal::Complete,
    );
}

#[tokio::test]
async fn encoded_one_over_in_separate_chunk_retains_prefix() {
    let head = b"HTTP/1.1 200 OK\r\nContent-Length: 6\r\n\r\n".to_vec();
    let parts = vec![
        (head, Duration::ZERO),
        (b"12345".to_vec(), Duration::ZERO),
        (b"6".to_vec(), Duration::ZERO),
    ];
    retained(
        consume(parts, 5, 100, 2_000_000, CancellationToken::new())
            .await
            .0,
        b"12345",
        6,
        BodyTerminal::ContentCodedLimit,
    );
}

#[tokio::test]
async fn valid_compressed_content_coding_exact_and_one_over_limits() {
    let payload = b"content-coded limit classification payload";
    let cases = [
        ("gzip", gzip(payload).await),
        ("br", brotli(payload).await),
        ("deflate", zlib(payload).await),
    ];
    for (coding, encoded) in cases {
        let encoded_len = encoded.len();
        retained(
            consume(
                vec![(wire(Some(coding), &encoded), Duration::ZERO)],
                encoded_len as u64,
                1_000,
                2_000_000,
                CancellationToken::new(),
            )
            .await
            .0,
            payload,
            encoded_len,
            BodyTerminal::Complete,
        );

        let outcome = consume(
            vec![(wire(Some(coding), &encoded), Duration::ZERO)],
            encoded_len.saturating_sub(1) as u64,
            1_000,
            2_000_000,
            CancellationToken::new(),
        )
        .await
        .0;
        assert_eq!(terminal(&outcome), BodyTerminal::ContentCodedLimit);
    }
}

#[tokio::test]
async fn valid_stacked_coding_one_over_is_content_coded_limit() {
    let payload = b"stacked coding payload";
    let gzip_encoded = gzip(payload).await;
    let encoded = brotli(&gzip_encoded).await;
    let outcome = consume(
        vec![(wire(Some("gzip, br"), &encoded), Duration::ZERO)],
        encoded.len().saturating_sub(1) as u64,
        1_000,
        2_000_000,
        CancellationToken::new(),
    )
    .await
    .0;
    assert_eq!(terminal(&outcome), BodyTerminal::ContentCodedLimit);
}

#[tokio::test]
async fn compressed_representation_exact_limit_completes() {
    let payload = b"12345";
    let encoded = gzip(payload).await;
    let encoded_len = encoded.len();
    retained(
        consume(
            vec![(wire(Some("gzip"), &encoded), Duration::ZERO)],
            1_000,
            payload.len() as u64,
            2_000_000,
            CancellationToken::new(),
        )
        .await
        .0,
        payload,
        encoded_len,
        BodyTerminal::Complete,
    );
}

#[tokio::test]
async fn compressed_representation_one_over_retains_exact_prefix() {
    let payload = b"123456";
    let encoded = gzip(payload).await;
    let encoded_len = encoded.len();
    retained(
        consume(
            vec![(wire(Some("gzip"), &encoded), Duration::ZERO)],
            1_000,
            5,
            2_000_000,
            CancellationToken::new(),
        )
        .await
        .0,
        b"12345",
        encoded_len,
        BodyTerminal::RepresentationLimit,
    );
}

#[tokio::test]
async fn content_coded_limit_wins_when_both_limits_are_crossed() {
    let payload = b"123456";
    retained(
        consume(
            vec![(wire(None, payload), Duration::ZERO)],
            5,
            5,
            2_000_000,
            CancellationToken::new(),
        )
        .await
        .0,
        b"12345",
        6,
        BodyTerminal::ContentCodedLimit,
    );
}

#[tokio::test]
async fn high_expansion_is_bounded_to_exact_prefix() {
    let payload = vec![b'x'; 1_000_000];
    let encoded = gzip(&payload).await;
    let encoded_len = encoded.len();
    retained(
        consume(
            vec![(wire(Some("gzip"), &encoded), Duration::ZERO)],
            encoded_len as u64 + 1,
            31,
            2_000_000,
            CancellationToken::new(),
        )
        .await
        .0,
        &payload[..31],
        encoded_len,
        BodyTerminal::RepresentationLimit,
    );
}
