use std::time::Duration;
use tokio::time::timeout;

use tokio::{net::TcpListener, sync::oneshot};
use tokio_util::sync::CancellationToken;

use super::{execute_direct_http_with_client_at, pinned_client, spec, wall_clock};
use crate::{DirectHttpRedirectTargetPolicy, DirectHttpTransportErrorKind};

#[tokio::test]
async fn cancellation_wins_while_tls_request_is_pending() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let (accepted_tx, accepted_rx) = oneshot::channel();
    let (release_tx, release_rx) = oneshot::channel();
    let server = tokio::spawn(async move {
        let (stream, _) = listener.accept().await.unwrap();
        let _ = accepted_tx.send(());
        let _ = release_rx.await;
        drop(stream);
    });
    let token = CancellationToken::new();
    let request_token = token.clone();
    let request = tokio::spawn(async move {
        execute_direct_http_with_client_at(
            spec(&format!("https://localhost:{}/pending", address.port())),
            &request_token,
            wall_clock(),
            pinned_client(),
            DirectHttpRedirectTargetPolicy::AllowHttpAndHttps,
        )
        .await
    });
    timeout(Duration::from_secs(5), accepted_rx)
        .await
        .unwrap()
        .unwrap();
    token.cancel();
    let failure = timeout(Duration::from_secs(5), request)
        .await
        .unwrap()
        .unwrap()
        .unwrap_err();
    let _ = release_tx.send(());
    server.await.unwrap();
    assert_eq!(
        failure.error().kind(),
        DirectHttpTransportErrorKind::Cancelled
    );
    assert!(failure.lifecycle().termination().is_some());
}
