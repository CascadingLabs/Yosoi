#![allow(
    clippy::panic_in_result_fn,
    reason = "Test assertions describe the contract; setup failures propagate as errors."
)]
//! Independent protocol-peer fixtures exercise the observable transport contract.

use super::*;
use async_tungstenite::tokio::accept_async;
use std::error as std_error;
use std::net as std_net;
use tokio::net::TcpListener;

type TestError = Box<dyn std_error::Error + Send + Sync>;
type TestResult = Result<(), TestError>;

fn deadline() -> Result<Instant, BidiError> {
    Instant::now()
        .checked_add(Duration::from_secs(10))
        .ok_or(BidiError::Deadline)
}

async fn listener() -> Result<(TcpListener, String), TestError> {
    let listener = TcpListener::bind((std_net::Ipv4Addr::LOCALHOST, 0)).await?;
    let endpoint = format!("ws://{}/session", listener.local_addr()?);
    Ok((listener, endpoint))
}

#[tokio::test]
async fn correlates_reversed_replies_and_keeps_an_event_before_the_waiter() -> TestResult {
    let (listener, endpoint) = listener().await?;
    let (event_sent, event_observed) = oneshot::channel();
    let peer = tokio::spawn(async move {
        let (stream, _) = listener.accept().await?;
        let mut socket = accept_async(stream).await?;
        socket.send(Message::Text(json!({"type":"event","method":"browsingContext.load","params":{"url":"https://example.test/"}}).to_string().into())).await?;
        let _ = event_sent.send(());
        let mut calls = Vec::new();
        for _ in 0..2 {
            let raw = socket.next().await.ok_or(BidiError::Closed)??;
            calls.push(serde_json::from_str::<Value>(raw.to_text()?)?);
        }
        for call in calls.into_iter().rev() {
            socket.send(Message::Text(json!({"type":"success","id":call.get("id"),"result":{"echo":call.get("method")}}).to_string().into())).await?;
        }
        while let Some(message) = socket.next().await {
            if matches!(message?, Message::Close(_)) {
                break;
            }
        }
        Ok::<(), TestError>(())
    });
    let cancellation = CancellationToken::new();
    let client = BidiConnection::connect(
        &endpoint,
        TransportLimits::default(),
        &cancellation,
        deadline()?,
    )
    .await?;
    event_observed.await?;
    let mut events = client.subscribe()?;
    let first = client.command("script.first", json!({}), &cancellation, deadline()?);
    let second = client.command("script.second", json!({}), &cancellation, deadline()?);
    let (first, second) = tokio::join!(first, second);
    assert_eq!(
        first?.get("echo").and_then(Value::as_str),
        Some("script.first")
    );
    assert_eq!(
        second?.get("echo").and_then(Value::as_str),
        Some("script.second")
    );
    let event = events.next(&cancellation, deadline()?).await?;
    assert_eq!(event.method, "browsingContext.load");
    assert_eq!(event.sequence, 1);
    assert_eq!(client.event_sequence(), event.sequence);
    client.close().await?;
    drop(client);
    peer.await??;
    Ok(())
}

#[tokio::test]
async fn cancellation_after_observed_dispatch_fences_the_connection() -> TestResult {
    let (listener, endpoint) = listener().await?;
    let (dispatched, observed) = oneshot::channel();
    let peer = tokio::spawn(async move {
        let (stream, _) = listener.accept().await?;
        let mut socket = accept_async(stream).await?;
        let message = socket.next().await.ok_or(BidiError::Closed)??;
        assert!(message.is_text());
        let _ = dispatched.send(());
        while let Some(message) = socket.next().await {
            if matches!(message?, Message::Close(_)) {
                break;
            }
        }
        Ok::<(), TestError>(())
    });
    let cancellation = CancellationToken::new();
    let client = BidiConnection::connect(
        &endpoint,
        TransportLimits::default(),
        &cancellation,
        deadline()?,
    )
    .await?;
    let caller = {
        let client = client.clone();
        let cancellation = cancellation.clone();
        tokio::spawn(async move {
            client
                .command(
                    "input.performActions",
                    json!({}),
                    &cancellation,
                    deadline()?,
                )
                .await
        })
    };
    observed.await?;
    cancellation.cancel();
    assert!(matches!(caller.await?, Err(BidiError::Cancelled)));
    assert!(client.is_closed());
    client.close().await?;
    drop(client);
    peer.await??;
    Ok(())
}

#[tokio::test]
async fn event_overflow_is_explicit_instead_of_silent_complete_evidence() -> TestResult {
    let (listener, endpoint) = listener().await?;
    let peer = tokio::spawn(async move {
        let (stream, _) = listener.accept().await?;
        let mut socket = accept_async(stream).await?;
        let raw = socket.next().await.ok_or(BidiError::Closed)??;
        let call: Value = serde_json::from_str(raw.to_text()?)?;
        for n in 0..3 {
            socket
                .send(Message::Text(
                    json!({"type":"event","method":"log.entryAdded","params":{"number":n}})
                        .to_string()
                        .into(),
                ))
                .await?;
        }
        socket
            .send(Message::Text(
                json!({"type":"success","id":call.get("id"),"result":{}})
                    .to_string()
                    .into(),
            ))
            .await?;
        while let Some(message) = socket.next().await {
            if matches!(message?, Message::Close(_)) {
                break;
            }
        }
        Ok::<(), TestError>(())
    });
    let cancellation = CancellationToken::new();
    let limits = TransportLimits {
        event_capacity: 1,
        ..TransportLimits::default()
    };
    let client = BidiConnection::connect(&endpoint, limits, &cancellation, deadline()?).await?;
    let mut events = client.subscribe()?;
    client
        .command("session.status", json!({}), &cancellation, deadline()?)
        .await?;
    assert!(matches!(
        events.next(&cancellation, deadline()?).await,
        Err(BidiError::EventOverflow)
    ));
    assert!(client.is_closed());
    client.close().await?;
    drop(client);
    peer.await??;
    Ok(())
}

#[tokio::test]
async fn malformed_reply_fails_all_pending_work_and_redacts_diagnostics() -> TestResult {
    let (listener, endpoint) = listener().await?;
    let peer = tokio::spawn(async move {
        let (stream, _) = listener.accept().await?;
        let mut socket = accept_async(stream).await?;
        let raw = socket.next().await.ok_or(BidiError::Closed)??;
        let call: Value = serde_json::from_str(raw.to_text()?)?;
        socket
            .send(Message::Text(
                json!({"type":"success","id":call.get("id")})
                    .to_string()
                    .into(),
            ))
            .await?;
        while let Some(message) = socket.next().await {
            if matches!(message?, Message::Close(_)) {
                break;
            }
        }
        Ok::<(), TestError>(())
    });
    let cancellation = CancellationToken::new();
    let client = BidiConnection::connect(
        &endpoint,
        TransportLimits::default(),
        &cancellation,
        deadline()?,
    )
    .await?;
    assert!(matches!(
        client
            .command("session.status", json!({}), &cancellation, deadline()?)
            .await,
        Err(BidiError::InvalidMessage)
    ));
    client.close().await?;
    drop(client);
    peer.await??;
    let error = BidiError::Protocol {
        code: "unknown error".into(),
        message: "secret-cookie".into(),
    };
    assert!(!format!("{error:?}: {error}").contains("secret-cookie"));
    Ok(())
}

#[test]
fn queue_bounds_reject_zero_and_arithmetic_exhaustion() {
    assert!(
        TransportLimits {
            event_capacity: 0,
            ..TransportLimits::default()
        }
        .validate()
        .is_err()
    );
    assert!(
        TransportLimits {
            max_message_bytes: usize::MAX,
            ..TransportLimits::default()
        }
        .validate()
        .is_err()
    );
    assert!(TransportLimits::default().validate().is_ok());
}

#[tokio::test]
async fn fenced_session_closes_only_its_owned_scope_and_ignores_late_action_reply() -> TestResult {
    let (listener, endpoint) = listener().await?;
    let (dispatched, observed) = oneshot::channel();
    let peer = tokio::spawn(async move {
        let (stream, _) = listener.accept().await?;
        let mut socket = accept_async(stream).await?;
        for (expected, result) in [
            (
                "session.new",
                json!({"sessionId":"logical-session","capabilities":{}}),
            ),
            (
                "browser.createUserContext",
                json!({"userContext":"owned-scope"}),
            ),
            ("browsingContext.create", json!({"context":"owned-tab"})),
        ] {
            let raw = socket.next().await.ok_or(BidiError::Closed)??;
            let call: Value = serde_json::from_str(raw.to_text()?)?;
            assert_eq!(call.get("method").and_then(Value::as_str), Some(expected));
            socket
                .send(Message::Text(
                    json!({"type":"success","id":call.get("id"),"result":result})
                        .to_string()
                        .into(),
                ))
                .await?;
        }
        // A foreign context notification is not ownership authority.
        socket.send(Message::Text(json!({"type":"event","method":"browsingContext.contextCreated","params":{"context":"foreign-tab"}}).to_string().into())).await?;
        let action: Value =
            serde_json::from_str(socket.next().await.ok_or(BidiError::Closed)??.to_text()?)?;
        let _ = dispatched.send(());
        for (method, key, expected) in [
            ("browsingContext.close", Some("context"), Some("owned-tab")),
            (
                "browser.removeUserContext",
                Some("userContext"),
                Some("owned-scope"),
            ),
            ("session.end", None, None),
        ] {
            let raw = socket.next().await.ok_or(BidiError::Closed)??;
            let call: Value = serde_json::from_str(raw.to_text()?)?;
            assert_eq!(call.get("method").and_then(Value::as_str), Some(method));
            assert!(
                call.get("id")
                    .and_then(Value::as_u64)
                    .is_some_and(|id| id > MAX_COMMAND_ID)
            );
            if let Some(key) = key {
                assert_eq!(
                    call.get("params")
                        .and_then(|p| p.get(key))
                        .and_then(Value::as_str),
                    expected
                );
            }
            if method == "browsingContext.close" {
                socket
                    .send(Message::Text(
                        json!({"type":"success","id":action.get("id"),"result":{"late":true}})
                            .to_string()
                            .into(),
                    ))
                    .await?;
            }
            socket
                .send(Message::Text(
                    json!({"type":"success","id":call.get("id"),"result":{}})
                        .to_string()
                        .into(),
                ))
                .await?;
        }
        while let Some(message) = socket.next().await {
            if matches!(message?, Message::Close(_)) {
                break;
            }
        }
        Ok::<(), TestError>(())
    });
    let cancellation = CancellationToken::new();
    let client = BidiConnection::connect(
        &endpoint,
        TransportLimits::default(),
        &cancellation,
        deadline()?,
    )
    .await?;
    client
        .command(
            "session.new",
            json!({"capabilities":{}}),
            &cancellation,
            deadline()?,
        )
        .await?;
    client
        .command(
            "browser.createUserContext",
            json!({}),
            &cancellation,
            deadline()?,
        )
        .await?;
    client
        .command(
            "browsingContext.create",
            json!({"type":"tab","userContext":"owned-scope"}),
            &cancellation,
            deadline()?,
        )
        .await?;
    let caller = {
        let client = client.clone();
        let cancellation = cancellation.clone();
        tokio::spawn(async move {
            client
                .command(
                    "input.performActions",
                    json!({}),
                    &cancellation,
                    deadline()?,
                )
                .await
        })
    };
    observed.await?;
    cancellation.cancel();
    assert!(matches!(caller.await?, Err(BidiError::Cancelled)));
    client.close().await?;
    assert!(matches!(
        client
            .command(
                "session.status",
                json!({}),
                &CancellationToken::new(),
                deadline()?
            )
            .await,
        Err(BidiError::Closed)
    ));
    drop(client);
    peer.await??;
    Ok(())
}
