#![allow(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Assertions describe the contract; settled owners intentionally remain live for post-settlement checks."
)]

use super::*;
use crate::browser::{BrowserConfig, BrowserEngine};
use crate::internal::browser::bidi::session::Session;
use crate::internal::browser::{
    NavigationCapture, NavigationCaptureOptions, ObservationEventKind, ObservationOptions,
    ObservationScope, ResponseBodyState,
};
use flate2::{Compression, write::GzEncoder};
use std::io::Write as _;
use std::{error::Error, io::Error as IoError, sync::Arc, time::Duration};
use tokio::time::timeout;
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
};

const BINARY_BODY: &[u8] = b"\0\xff\xe9native";
const UNICODE_BODY: &[u8] = "é漢".as_bytes();

#[test]
fn response_bytes_preserve_binary_extent_and_bound_retention() -> Result<(), SessionError> {
    let body = decode_body(&json!({"bytes":{"type":"base64","value":"AP9hYmM="}}), 2)?;
    assert_eq!(body.bytes, [0, 255]);
    assert_eq!(body.complete_bytes, 5);
    let body = decode_body(&json!({"bytes":{"type":"string","value":"é"}}), 1)?;
    assert_eq!(body.bytes, [0xc3]);
    assert_eq!(body.complete_bytes, 2);
    assert!(decode_body(&json!({"bytes":{"type":"base64","value":"invalid!"}}), 8).is_err());
    assert!(decode_body(&json!({"bytes":{"type":"other","value":"secret"}}), 8).is_err());
    Ok(())
}

async fn native_network(engine: BrowserEngine) -> Result<(), Box<dyn Error + Send + Sync>> {
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let origin = format!("http://{}", listener.local_addr()?);
    let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
    encoder.write_all(BINARY_BODY)?;
    let gzip = encoder.finish()?;
    let server = tokio::spawn(async move {
        while let Ok((mut socket, _)) = listener.accept().await {
            let mut request = Vec::new();
            let head = timeout(Duration::from_secs(3), async {
                let mut chunk = [0u8; 1024];
                while request.len() < 8192 {
                    let count = socket.read(&mut chunk).await?;
                    if count == 0 {
                        return Ok::<_, IoError>(false);
                    }
                    request.extend_from_slice(chunk.get(..count).unwrap_or_default());
                    if request.windows(4).any(|part| part == b"\r\n\r\n") {
                        return Ok(true);
                    }
                }
                Ok(false)
            })
            .await;
            if !matches!(head, Ok(Ok(true))) {
                continue;
            }
            let body: &[u8] = if request.starts_with(b"GET /gzip ") {
                &gzip
            } else if request.starts_with(b"GET /unicode ") {
                UNICODE_BODY
            } else if request.starts_with(b"GET /binary ")
                || request.starts_with(b"GET /charset ")
                || request.starts_with(b"GET /invalid-text ")
            {
                BINARY_BODY
            } else if request.starts_with(b"GET /api-peer ") {
                b"peer isolated body"
            } else {
                b"<!doctype html><title>network source</title>body"
            };
            let headers = if request.starts_with(b"GET /gzip ") {
                "Content-Type: application/octet-stream\r\nContent-Encoding: gzip"
            } else if request.starts_with(b"GET /charset ") {
                "Content-Type: text/plain; charset=windows-1252"
            } else if request.starts_with(b"GET /binary ") {
                "Content-Type: application/octet-stream"
            } else {
                "Content-Type: text/html"
            };
            let response = format!(
                "HTTP/1.1 200 OK\r\n{headers}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                body.len()
            );
            let _ = socket.write_all(response.as_bytes()).await;
            let _ = socket.write_all(body).await;
            let _ = socket.shutdown().await;
        }
    });
    let token = CancellationToken::new();
    let deadline = Instant::now()
        .checked_add(Duration::from_secs(30))
        .ok_or("deadline")?;
    let session = Session::launch(
        BrowserConfig {
            engine,
            moli_allow_private_networks: engine == BrowserEngine::Moli,
            ..BrowserConfig::default()
        },
        false,
        &token,
        deadline,
    )
    .await?;
    let result = async {
        let owner = session.new_user_context(&token, deadline).await?;
        let page = session.new_page(&owner, &token, deadline).await?;
        if engine == BrowserEngine::Moli {
            moli_subresources(&session, &page, &origin, &token, deadline).await?;
            encoded_bodies(&page, &token, deadline).await?;
            page.close(&token, deadline).await?;
            session
                .remove_user_context(&owner, &token, deadline)
                .await?;
            return Ok(());
        }
        let mut capture = page.arm_network(&token, deadline).await?;
        page.navigate(&origin, "complete", &token, deadline).await?;
        let request = loop {
            let event = capture.next(&token, deadline).await?;
            if event.method == "network.responseCompleted"
                && event
                    .params
                    .pointer("/response/url")
                    .and_then(Value::as_str)
                    == Some(format!("{origin}/").as_str())
            {
                assert_eq!(
                    event
                        .params
                        .pointer("/response/status")
                        .and_then(Value::as_u64),
                    Some(200)
                );
                break identifier(event.params.get("request").ok_or("request")?, "request")?;
            }
        };
        let body = capture
            .response_body(&request, 20, &token, deadline)
            .await?;
        assert_eq!(body.bytes, b"<!doctype html><titl");
        assert_eq!(body.complete_bytes, 48);
        capture.close(&token, deadline).await?;
        // Collector ownership is gone; a later capture must not inherit it.
        assert!(
            capture
                .response_body(&request, 20, &token, deadline)
                .await
                .is_err()
        );
        encoded_bodies(&page, &token, deadline).await?;
        let navigation = NavigationCapture::arm_bidi(
            page.clone(),
            NavigationCaptureOptions {
                max_events: 3,
                max_source_bytes: 20,
                ..NavigationCaptureOptions::default()
            },
        )
        .await?;
        page.navigate(&format!("{origin}/second"), "complete", &token, deadline)
            .await?;
        let report = navigation.wait().await?;
        assert!(report.cleanup_complete);
        assert_eq!(report.events.len(), 3);
        assert_eq!(report.resources.len(), 1);
        assert_eq!(
            report
                .resources
                .first()
                .and_then(|resource| resource.status),
            Some(200)
        );
        let source = report.main_document.ok_or("main source")?;
        assert_eq!(source.body(), b"<!doctype html><titl");
        assert_eq!(source.complete_bytes, Some(48));
        assert_eq!(source.body_state, ResponseBodyState::Truncated);
        let mut observation = ObservationScope::arm_bidi(
            page.clone(),
            ObservationOptions {
                collect_network: true,
                collect_console: false,
                collect_exceptions: false,
                ..ObservationOptions::default()
            },
        )
        .await?;
        page.navigate(&format!("{origin}/observed"), "complete", &token, deadline)
            .await?;
        let quiet = observation
            .wait_for_quiet(Duration::from_millis(25), 0, deadline)
            .await?;
        assert_eq!(quiet.relevant_in_flight, 0);
        let observed = observation.finish().await?;
        assert!(observed.cleanup_complete);
        assert!(observed.events.len() >= 3);
        assert!(
            observed
                .events
                .iter()
                .any(|event| event.kind == ObservationEventKind::DocumentRequestStarted)
        );
        assert!(
            observed
                .events
                .iter()
                .any(|event| event.kind == ObservationEventKind::RequestFinished)
        );
        page.close(&token, deadline).await?;
        session
            .remove_user_context(&owner, &token, deadline)
            .await?;
        Ok::<_, Box<dyn Error + Send + Sync>>(())
    }
    .await;
    let cleanup = session.close().await;
    server.abort();
    cleanup?;
    result
}

async fn encoded_bodies(
    page: &Page,
    token: &CancellationToken,
    deadline: Instant,
) -> Result<(), Box<dyn Error + Send + Sync>> {
    let mut capture = page.arm_network(token, deadline).await?;
    for path in ["/binary", "/gzip", "/unicode", "/invalid-text", "/charset"] {
        let expected = if path == "/unicode" {
            UNICODE_BODY
        } else {
            BINARY_BODY
        };
        let source = format!("fetch('{path}').then(r=>r.arrayBuffer()).then(b=>b.byteLength)");
        assert_eq!(
            page.evaluate(&source, token, deadline).await?.0,
            json!(expected.len())
        );
        let request = completed_request(&mut capture, path, token, deadline).await?;
        let prefix = capture
            .retained_response_body(&request, 2, token, deadline)
            .await;
        if page.session.config.engine == BrowserEngine::Firefox
            && matches!(path, "/gzip" | "/invalid-text" | "/charset")
        {
            assert!(
                matches!(
                    prefix,
                    Err(SessionError::Unsupported(
                        "Firefox response body byte fidelity"
                    ))
                ),
                "altered native bytes must be unavailable for {path}: {prefix:?}"
            );
            continue;
        }
        let prefix = prefix?;
        assert_eq!(
            prefix.bytes,
            expected.get(..2).ok_or("prefix")?,
            "binary prefix for {path}"
        );
        assert_eq!(prefix.complete_bytes, expected.len());
        let full = capture
            .retained_response_body(&request, 4096, token, deadline)
            .await?;
        assert_eq!(
            full.bytes, expected,
            "content-decoded bytes must not undergo charset conversion: {path}"
        );
    }
    capture.close(token, deadline).await?;
    Ok(())
}

#[tokio::test]
#[ignore = "requires the qualified regular Firefox executable"]
async fn firefox_network_bodies() -> Result<(), Box<dyn Error + Send + Sync>> {
    native_network(BrowserEngine::Firefox).await
}

async fn completed_request(
    capture: &mut ScopedCapture,
    suffix: &str,
    token: &CancellationToken,
    deadline: Instant,
) -> Result<String, SessionError> {
    loop {
        let event = capture.next(token, deadline).await?;
        if event.method == "network.responseCompleted"
            && event
                .params
                .pointer("/response/url")
                .and_then(Value::as_str)
                .is_some_and(|url| url.ends_with(suffix))
        {
            return identifier(
                event
                    .params
                    .get("request")
                    .ok_or(SessionError::Serialization)?,
                "request",
            );
        }
    }
}

async fn moli_subresources(
    session: &Arc<Session>,
    page: &Page,
    origin: &str,
    token: &CancellationToken,
    deadline: Instant,
) -> Result<(), Box<dyn Error + Send + Sync>> {
    let mut first = page.arm_network(token, deadline).await?;
    page.navigate(origin, "complete", token, deadline).await?;
    page.evaluate("fetch('/api').then(r=>r.text())", token, deadline)
        .await?;
    let first_id = completed_request(&mut first, "/api", token, deadline).await?;
    let peer_owner = session.new_user_context(token, deadline).await?;
    let peer = session.new_page(&peer_owner, token, deadline).await?;
    let mut second = peer.arm_network(token, deadline).await?;
    peer.navigate(origin, "complete", token, deadline).await?;
    peer.evaluate("fetch('/api-peer').then(r=>r.text())", token, deadline)
        .await?;
    let second_id = completed_request(&mut second, "/api-peer", token, deadline).await?;
    assert_ne!(first_id, second_id);
    assert!(
        first
            .response_body(&second_id, 20, token, deadline)
            .await
            .is_err()
    );
    assert!(
        second
            .response_body(&first_id, 20, token, deadline)
            .await
            .is_err()
    );
    for (capture, request, expected, extent) in [
        (&first, &first_id, &b"<!doctype html><titl"[..], 48),
        (&second, &second_id, &b"peer isolated body"[..], 18),
    ] {
        let body = capture.response_body(request, 20, token, deadline).await?;
        assert_eq!(body.bytes, expected);
        assert_eq!(body.complete_bytes, extent);
    }
    first.close(token, deadline).await?;
    second.close(token, deadline).await?;
    peer.close(token, deadline).await?;
    session
        .remove_user_context(&peer_owner, token, deadline)
        .await?;
    moli_graph_and_observation(page, origin, token, deadline).await
}

async fn moli_graph_and_observation(
    page: &Page,
    origin: &str,
    token: &CancellationToken,
    deadline: Instant,
) -> Result<(), Box<dyn Error + Send + Sync>> {
    let graph = NavigationCapture::arm_bidi(
        page.clone(),
        NavigationCaptureOptions {
            max_events: 3,
            ..NavigationCaptureOptions::default()
        },
    )
    .await?;
    page.navigate(&format!("{origin}/next"), "complete", token, deadline)
        .await?;
    page.evaluate("fetch('/graph').then(r=>r.text())", token, deadline)
        .await?;
    let report = graph.wait().await?;
    assert!(report.cleanup_complete);
    assert!(report.additional_loss_unknown);
    assert!(report.main_document.is_none());
    assert_eq!(report.resources.len(), 1);
    assert_eq!(
        report
            .resources
            .first()
            .and_then(|resource| resource.status),
        Some(200)
    );

    let mut observation = ObservationScope::arm_bidi(
        page.clone(),
        ObservationOptions {
            collect_network: true,
            collect_console: false,
            collect_exceptions: false,
            max_events: 3,
            ..ObservationOptions::default()
        },
    )
    .await?;
    assert!(
        observation
            .wait_for_quiet(Duration::from_millis(25), 0, deadline)
            .await
            .is_err()
    );
    page.evaluate("fetch('/observed').then(r=>r.text())", token, deadline)
        .await?;
    let observed = observation.wait().await?;
    assert_eq!(observed.events.len(), 3);
    assert!(observed.cleanup_complete);
    Ok(())
}

#[tokio::test]
#[ignore = "requires the pinned Moli executable"]
async fn moli_subresource_bodies_preserve_isolation() -> Result<(), Box<dyn Error + Send + Sync>> {
    native_network(BrowserEngine::Moli).await
}
