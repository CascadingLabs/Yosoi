use std::time::Duration;

use tokio_util::sync::CancellationToken;
use yosoi_web_capture_direct_http::BodyTerminal;

use super::support::{brotli, consume, gzip, retained, wire, zlib};

#[tokio::test]
async fn identity_public_success() {
    let body = b"identity";
    retained(
        consume(
            vec![(wire(None, body), Duration::ZERO)],
            100,
            100,
            2_000_000,
            CancellationToken::new(),
        )
        .await
        .0,
        body,
        body.len(),
        BodyTerminal::Complete,
    );
}

macro_rules! coding_success {
    ($name:ident, $coding:literal, $encoder:ident, $payload:literal) => {
        #[tokio::test]
        async fn $name() {
            let payload = $payload;
            let encoded = $encoder(payload).await;
            let encoded_len = encoded.len();
            retained(
                consume(
                    vec![(wire(Some($coding), &encoded), Duration::ZERO)],
                    2_000,
                    2_000,
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
    };
}

coding_success!(gzip_public_success, "gzip", gzip, b"gzip payload");
coding_success!(x_gzip_public_success, "x-gzip", gzip, b"alias");
coding_success!(brotli_public_success, "br", brotli, b"brotli payload");
coding_success!(zlib_public_success, "deflate", zlib, b"deflate payload");

#[tokio::test]
async fn identity_inside_chain_is_noop() {
    let payload = b"chain";
    let encoded = gzip(payload).await;
    let encoded_len = encoded.len();
    retained(
        consume(
            vec![(
                wire(Some("identity, gzip, identity"), &encoded),
                Duration::ZERO,
            )],
            2_000,
            2_000,
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
async fn repeated_encoding_lines_preserve_wire_order() {
    let payload = b"repeated";
    let gzip_bytes = gzip(payload).await;
    let encoded = brotli(&gzip_bytes).await;
    let encoded_len = encoded.len();
    let head = format!(
        "HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\nContent-Encoding: br\r\nContent-Length: {encoded_len}\r\n\r\n"
    );
    retained(
        consume(
            vec![([head.as_bytes(), &encoded].concat(), Duration::ZERO)],
            2_000,
            2_000,
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
async fn compressed_chunk_splits_do_not_change_result() {
    let payload = (0_usize..16_384)
        .map(|index| u8::try_from(index % 251).unwrap())
        .collect::<Vec<_>>();
    let encoded = gzip(&payload).await;
    let encoded_len = encoded.len();
    let response = wire(Some("gzip"), &encoded);
    let split = response.len() / 2;
    let parts = vec![
        (response[..split].to_vec(), Duration::ZERO),
        (response[split..].to_vec(), Duration::ZERO),
    ];
    retained(
        consume(parts, 50_000, 50_000, 2_000_000, CancellationToken::new())
            .await
            .0,
        &payload,
        encoded_len,
        BodyTerminal::Complete,
    );
}
