#![allow(clippy::unwrap_used, reason = "deterministic local fixtures")]

use std::sync::Arc;

use chrono::{DateTime, Utc};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
    sync::Mutex,
};
use tokio_util::sync::CancellationToken;

use super::{
    DirectHttpRedirectErrorKind, execute_direct_http_at,
    redirect_test_assertions::assert_terminal_redirect_failure, tests::spec_with_redirects,
};
use crate::{DirectHttpRedirectPolicy, Observation};

fn wall_clock() -> DateTime<Utc> {
    DateTime::from_timestamp(1_700_000_000, 0).unwrap()
}
fn follow(url: &str, hops: u32) -> crate::ResolvedDirectHttpCaptureSpec {
    spec_with_redirects(
        url,
        DirectHttpRedirectPolicy::follow(crate::RedirectHopLimit::try_from(hops).unwrap()),
        2_000_000,
    )
}

async fn recording_server(routes: Vec<Vec<u8>>) -> (String, Arc<Mutex<Vec<String>>>) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let routes = Arc::new(Mutex::new(routes.into_iter()));
    let requests = Arc::new(Mutex::new(Vec::new()));
    let recorded = Arc::clone(&requests);
    tokio::spawn(async move {
        loop {
            let Ok((mut stream, _)) = listener.accept().await else {
                return;
            };
            let mut request = [0_u8; 2048];
            let Ok(size) = stream.read(&mut request).await else {
                continue;
            };
            let line = String::from_utf8_lossy(&request[..size])
                .lines()
                .next()
                .unwrap_or("")
                .to_owned();
            recorded.lock().await.push(line);
            let Some(response) = routes.lock().await.next() else {
                continue;
            };
            let _ = stream.write_all(&response).await;
        }
    });
    (
        format!("http://{address}/start?initial=yes#fragment"),
        requests,
    )
}

#[tokio::test]
async fn every_followed_status_sends_get_and_forms_a_continuous_chain() {
    let mut routes = [301, 302, 303, 307, 308].into_iter().enumerate().map(|(index, status)| {
        format!("HTTP/1.1 {status} Redirect\r\nLocation: /p{index}?q={index}#f{index}\r\nContent-Length: 0\r\n\r\n").into_bytes()
    }).collect::<Vec<_>>();
    routes.push(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n".to_vec());
    let (url, requests) = recording_server(routes).await;
    let pending = execute_direct_http_at(follow(&url, 5), &CancellationToken::new(), wall_clock())
        .await
        .unwrap();
    let hops = pending.resolution().redirects().as_observed().unwrap();
    assert_eq!(hops.len(), 5);
    for pair in hops.windows(2) {
        assert_eq!(pair[0].to(), pair[1].from());
    }
    let requests = requests.lock().await.clone();
    assert_eq!(requests.len(), 6);
    assert!(
        requests
            .iter()
            .all(|line| line.starts_with("GET ") && line.ends_with(" HTTP/1.1"))
    );
}

#[tokio::test]
async fn invalid_header_encoding_is_a_malformed_location_terminal_failure() {
    let mut response = b"HTTP/1.1 302 Found\r\nLocation: /bad".to_vec();
    response.push(0xff);
    response.extend_from_slice(b"\r\nContent-Length: 9\r\n\r\nunconsumed");
    let (url, _) = recording_server(vec![response]).await;
    let failure = execute_direct_http_at(follow(&url, 1), &CancellationToken::new(), wall_clock())
        .await
        .unwrap_err();
    assert_terminal_redirect_failure(
        &failure,
        DirectHttpRedirectErrorKind::MalformedLocation,
        &url,
        &[],
        &["initial=yes", "unconsumed"],
    );
}

#[tokio::test]
async fn changed_query_and_path_are_not_false_positive_loops() {
    let routes = vec![
        b"HTTP/1.1 302 Found\r\nLocation: /start?initial=no#other\r\nContent-Length: 0\r\n\r\n"
            .to_vec(),
        b"HTTP/1.1 302 Found\r\nLocation: /different?initial=no#other\r\nContent-Length: 0\r\n\r\n"
            .to_vec(),
        b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n".to_vec(),
    ];
    let (url, _) = recording_server(routes).await;
    let pending = execute_direct_http_at(follow(&url, 2), &CancellationToken::new(), wall_clock())
        .await
        .unwrap();
    assert!(
        matches!(pending.resolution().redirects(), Observation::Observed(hops) if hops.len() == 2)
    );
}
