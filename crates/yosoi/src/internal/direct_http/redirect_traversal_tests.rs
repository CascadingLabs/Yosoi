#![allow(clippy::unwrap_used, reason = "deterministic local fixtures")]

use crate::internal::direct_http as yosoi_web_capture_direct_http;

use chrono::DateTime;
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
    time::Instant,
};
use tokio_util::sync::CancellationToken;

use super::{execute_direct_http_at, tests::spec_with_redirects};
use crate::internal::direct_http::{DirectHttpRedirectPolicy, Observation};

async fn one_response_server(response: Vec<u8>) -> String {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let mut request = [0_u8; 2048];
        let _ = stream.read(&mut request).await;
        stream.write_all(&response).await.unwrap();
    });
    format!("http://{address}/start?signature=SECRET#fragment")
}

#[tokio::test]
async fn follows_absolute_cross_origin_and_returns_all_exact_evidence() {
    let destination =
        one_response_server(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n".to_vec()).await;
    let initial = one_response_server(
        format!("HTTP/1.1 302 Found\r\nLocation: {destination}\r\nContent-Length: 0\r\n\r\n")
            .into_bytes(),
    )
    .await;
    let spec = spec_with_redirects(
        &initial,
        DirectHttpRedirectPolicy::follow(
            yosoi_web_capture_direct_http::RedirectHopLimit::try_from(1).unwrap(),
        ),
        1_000_000,
    );
    let started_at = DateTime::from_timestamp(1_700_000_000, 0).unwrap();
    let pending = execute_direct_http_at(spec, &CancellationToken::new(), started_at)
        .await
        .unwrap();

    let resolution = pending.resolution();
    let hops = resolution.redirects().as_observed().unwrap();
    assert_eq!(hops.len(), 1);
    assert_eq!(hops[0].from().as_str(), initial);
    assert_eq!(hops[0].to().as_str(), destination);
    assert_eq!(
        resolution.final_url().as_observed().unwrap().as_str(),
        destination
    );
    assert!(matches!(
        resolution.resource_origin(),
        Observation::Observed(yosoi_web_capture_direct_http::ObservedWebOrigin::Tuple(origin))
            if origin == &hops[0].to().origin()
    ));

    let expected_resolution = resolution.clone();
    let expected_deadline = pending.deadline();
    let (response, _spec, facts, resolution, lifecycle, identity, boundary) = pending.into_parts();
    assert_eq!(response.status().as_u16(), 200);
    assert_eq!(
        facts.final_url().as_str(),
        destination.trim_end_matches("#fragment")
    );
    assert_eq!(resolution, expected_resolution);
    assert!(lifecycle.termination().is_none());
    assert_eq!(identity.dependency().crate_name(), "wreq");
    assert_eq!(Instant::from_std(boundary.deadline()), expected_deadline);
}
