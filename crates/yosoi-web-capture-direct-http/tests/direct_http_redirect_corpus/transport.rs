use crate::{
    fixture::{FixtureService, Protocol, Response, ResponseControl},
    support::*,
};
use std::{
    net::{Ipv4Addr, TcpListener},
    sync::Arc,
};
use tokio_util::sync::CancellationToken;
use yosoi_web_capture_direct_http::*;

fn unused_url(path: &str) -> String {
    let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).unwrap();
    let address = listener.local_addr().unwrap();
    drop(listener);
    format!("http://{address}{path}")
}
fn assert_transport(
    error: DirectHttpCaptureError,
    kind: DirectHttpTransportErrorKind,
    reason: &str,
    has_resolution: bool,
) {
    let failure = transport(error);
    assert_eq!(failure.error().kind(), kind);
    assert_eq!(failure.resolution().is_some(), has_resolution);
    assert!(!failure.has_unconsumed_response());
    assert!(
        matches!(failure.lifecycle().termination(), Some(CaptureTermination::Interrupted(value)) if value.reason().as_str() == reason)
    );
    for text in [
        failure.to_string(),
        format!("{failure:?}"),
        format!("{:?}", failure.error()),
    ] {
        assert!(!text.contains("token=TRANSPORT_SECRET"));
    }
    let (response, resolution, _spec, lifecycle, primary, secondary) = failure.into_parts();
    assert!(response.is_none());
    assert_eq!(resolution.is_some(), has_resolution);
    assert!(lifecycle.termination().is_some());
    assert_eq!(primary.kind(), kind);
    assert!(secondary.is_none());
}

#[tokio::test]
async fn pre_cancelled_and_connection_refusal_have_stable_terminal_evidence() {
    let token = CancellationToken::new();
    token.cancel();
    let url = unused_url("/cancel?token=TRANSPORT_SECRET");
    assert_transport(
        capture(follow(&url, 1, 1_000_000), &token)
            .await
            .unwrap_err(),
        DirectHttpTransportErrorKind::Cancelled,
        "web_capture.direct_http.cancelled",
        false,
    );
    let refused = unused_url("/refused?token=TRANSPORT_SECRET");
    let failure = transport(
        capture(follow(&refused, 1, 1_000_000), &CancellationToken::new())
            .await
            .unwrap_err(),
    );
    assert!(matches!(
        failure.error().kind(),
        DirectHttpTransportErrorKind::Connect | DirectHttpTransportErrorKind::Client
    ));
    assert!(failure.resolution().is_none());
    assert!(!failure.has_unconsumed_response());
    assert!(
        matches!(failure.lifecycle().termination(), Some(CaptureTermination::Interrupted(value)) if value.reason().as_str() == "web_capture.direct_http.provider_failure")
    );
    assert!(!format!("{failure:?}").contains("TRANSPORT_SECRET"));
}

#[tokio::test]
async fn untrusted_loopback_https_is_a_redacted_provider_failure() {
    let service = FixtureService::start(
        Protocol::Https,
        [(
            "/secure?token=TRANSPORT_SECRET".into(),
            Response::bytes(200, Some("text/plain"), b"secret-body"),
        )],
    )
    .await;
    let failure = transport(
        capture(
            follow(&service.url("/secure?token=TRANSPORT_SECRET"), 1, 1_000_000),
            &CancellationToken::new(),
        )
        .await
        .unwrap_err(),
    );
    assert!(matches!(
        failure.error().kind(),
        DirectHttpTransportErrorKind::Tls
            | DirectHttpTransportErrorKind::Connect
            | DirectHttpTransportErrorKind::Client
    ));
    assert!(
        matches!(failure.lifecycle().termination(), Some(CaptureTermination::Interrupted(value)) if value.reason().as_str() == "web_capture.direct_http.provider_failure")
    );
    assert!(!format!("{failure} {failure:?}").contains("TRANSPORT_SECRET"));
    assert!(!format!("{failure:?}").contains("secret-body"));
    service.shutdown().await;
}

#[tokio::test]
async fn malformed_raw_http_is_a_protocol_failure() {
    let service = FixtureService::start(
        Protocol::Http,
        [("/malformed".into(), Response::raw(b"NOT HTTP\r\n\r\n"))],
    )
    .await;
    let failure = transport(
        capture(
            follow(&service.url("/malformed"), 1, 1_000_000),
            &CancellationToken::new(),
        )
        .await
        .unwrap_err(),
    );
    assert_eq!(
        failure.error().kind(),
        DirectHttpTransportErrorKind::Protocol
    );
    assert!(failure.resolution().is_none());
    assert!(!failure.has_unconsumed_response());
    service.shutdown().await;
}

#[tokio::test]
async fn cancellation_after_exactly_one_hop_is_cancelled_with_partial_resolution() {
    let control = Arc::new(ResponseControl {
        hold_before_head: true,
        ..ResponseControl::default()
    });
    let service = FixtureService::start(
        Protocol::Http,
        [
            ("/a".into(), Response::redirect("/b")),
            (
                "/b".into(),
                Response {
                    control: Some(control.clone()),
                    ..Response::bytes(200, Some("text/plain"), b"unread")
                },
            ),
        ],
    )
    .await;
    let cancellation = CancellationToken::new();
    let child_token = cancellation.clone();
    let child_control = control.clone();
    let canceller = tokio::spawn(async move {
        child_control.requested.wait().await;
        child_token.cancel();
    });
    let failure = transport(
        capture(follow(&service.url("/a"), 2, 1_000_000), &cancellation)
            .await
            .unwrap_err(),
    );
    canceller.await.unwrap();
    assert_eq!(
        failure.error().kind(),
        DirectHttpTransportErrorKind::Cancelled
    );
    let resolution = failure.resolution().unwrap();
    let hops = resolution.redirects().as_observed().unwrap();
    assert_eq!(hops.len(), 1);
    assert_eq!(hops[0].from().as_str(), service.url("/a"));
    assert_eq!(hops[0].to().as_str(), service.url("/b"));
    assert_eq!(
        resolution.final_url().as_observed().unwrap().as_str(),
        service.url("/b")
    );
    assert_eq!(
        service
            .requests()
            .await
            .iter()
            .map(|request| request.path.as_str())
            .collect::<Vec<_>>(),
        ["/a", "/b"]
    );
    control.allow_head.signal();
    service.shutdown().await;
}

#[tokio::test]
async fn provider_failure_after_hop_keeps_partial_chain_and_current_url() {
    let closed = unused_url("/closed?token=TRANSPORT_SECRET");
    let service = FixtureService::start(
        Protocol::Http,
        [("/start".into(), {
            let mut value = Response::redirect(&closed);
            value.status = 308;
            value
        })],
    )
    .await;
    let failure = transport(
        capture(
            follow(&service.url("/start"), 2, 1_000_000),
            &CancellationToken::new(),
        )
        .await
        .unwrap_err(),
    );
    let resolution = failure.resolution().unwrap();
    let hops = resolution.redirects().as_observed().unwrap();
    assert_eq!(hops.len(), 1);
    assert_eq!(resolution.final_url().as_observed().unwrap(), hops[0].to());
    assert!(
        matches!(failure.lifecycle().termination(), Some(CaptureTermination::Interrupted(value)) if value.reason().as_str() == "web_capture.direct_http.provider_failure")
    );
    assert!(!format!("{failure:?}").contains("TRANSPORT_SECRET"));
    service.shutdown().await;
}
