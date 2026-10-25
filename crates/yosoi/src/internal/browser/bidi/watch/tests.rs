#![allow(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Assertions describe acceptance; settled owners intentionally remain live through cleanup assertions."
)]

use super::*;
use crate::browser::{BrowserConfig, MoliProfile};
use crate::internal::browser::{ObservationResponseFilter, bidi::session::Session};
use std::{error::Error, io::Error as IoError, result::Result as StdResult};
use tokio::time::timeout;
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
    time::timeout_at,
};

const JSON_BODY: &[u8] = b"{\"status\":\"loaded\"}";

async fn native_watch(engine: BrowserEngine) -> StdResult<(), Box<dyn Error + Send + Sync>> {
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let origin = format!("http://{}", listener.local_addr()?);
    let server = tokio::spawn(async move {
        while let Ok((mut socket, _)) = listener.accept().await {
            let mut request = Vec::new();
            let read = timeout(Duration::from_secs(3), async {
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
            if !matches!(read, Ok(Ok(true))) {
                continue;
            }
            let (body, mime): (&[u8], &str) = if request.starts_with(b"POST /api ") {
                (JSON_BODY, "application/json")
            } else {
                (b"<!doctype html><title>watch</title><button id='fetch' onclick=\"fetch('/api',{method:'POST'}).then(r=>r.json()).then(j=>{document.querySelector('#result').textContent=j.status})\">Load</button><input id='field'><span id='result'>waiting</span>","text/html")
            };
            let header = format!(
                "HTTP/1.1 200 OK\r\nContent-Type: {mime}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                body.len()
            );
            let _ = socket.write_all(header.as_bytes()).await;
            let _ = socket.write_all(body).await;
            let _ = socket.shutdown().await;
        }
    });
    let token = CancellationToken::new();
    let deadline = Instant::now()
        .checked_add(Duration::from_secs(40))
        .ok_or("deadline")?;
    let session = Session::launch(
        BrowserConfig {
            engine,
            moli_profile: if engine == BrowserEngine::Moli {
                MoliProfile::Layout
            } else {
                MoliProfile::Dom
            },
            moli_allow_private_networks: engine == BrowserEngine::Moli,
            ..BrowserConfig::default()
        },
        false,
        &token,
        deadline,
    )
    .await?;
    let result = async {
        let user = session.new_user_context(&token, deadline).await?;
        let page = session.new_page(&user, &token, deadline).await?;
        page.navigate(&origin, "complete", &token, deadline).await?;
        let options = ObservationWatchOptions {
            observe_dom: true,
            observe_accessibility: false,
            response_filters: vec![ObservationResponseFilter {
                url: format!("{origin}/api"),
                method: Some("POST".to_owned()),
                status: Some(200),
            }],
            max_events: 16,
            max_bytes: 4096,
        };
        let mut watch = page.start_observation_watch(options.clone()).await?;
        assert!(page.start_observation_watch(options.clone()).await.is_err());
        page.click_in_watch("#fetch", &watch).await?;
        let mut candidate = None;
        let mut saw_dom = false;
        while candidate.is_none() || !saw_dom {
            match timeout_at(deadline, watch.next()).await?? {
                ObservationChange::DomChanged { .. } => saw_dom = true,
                ObservationChange::ResponseCompleted(value) => candidate = Some(value),
                ObservationChange::AccessibilityChanged { .. } => {
                    return Err("unexpected synthetic AX notification".into());
                }
            }
        }
        let candidate = candidate.ok_or("candidate")?;
        assert!(candidate.top_level);
        assert!(candidate.started_at_unix_us > 0);
        assert_eq!(candidate.loader_id, None);
        assert_eq!(candidate.epoch, watch.start_scope().epoch);
        let truncated = page
            .capture_observation_response_body(&candidate, 5)
            .await?;
        assert!(!truncated.complete);
        assert_eq!(truncated.bytes(), b"{\"sta");
        let full = page
            .capture_observation_response_body(&candidate, 4096)
            .await?;
        assert!(full.complete);
        assert_eq!(full.bytes(), JSON_BODY);
        watch.settle().await?;
        assert!(watch.next().await.is_err());
        assert!(
            page.capture_observation_response_body(&candidate, 4096)
                .await
                .is_err()
        );

        let mut next = page
            .start_observation_watch(ObservationWatchOptions {
                observe_dom: false,
                ..options
            })
            .await?;
        assert!(
            page.capture_observation_response_body(&candidate, 4096)
                .await
                .is_err()
        );
        page.type_in_watch("#field", "scoped", &next).await?;
        assert_eq!(
            page.evaluate_in_watch("()=>document.querySelector('#field').value", &next)
                .await?,
            json!("scoped")
        );
        page.navigate(
            &format!("{origin}/replacement"),
            "complete",
            &token,
            deadline,
        )
        .await?;
        assert!(
            page.evaluate_in_watch(
                "()=>{document.body.dataset.replayed='bad';return true}",
                &next
            )
            .await
            .is_err()
        );
        assert!(page.click_in_watch("#fetch", &next).await.is_err());
        assert_eq!(
            page.evaluate("document.body.dataset.replayed??null", &token, deadline)
                .await?
                .0,
            Value::Null
        );
        next.settle().await?;
        page.close(&token, deadline).await?;
        session.remove_user_context(&user, &token, deadline).await?;
        Ok::<_, Box<dyn Error + Send + Sync>>(())
    }
    .await;
    let cleanup = session.close().await;
    server.abort();
    let _ = server.await;
    result?;
    cleanup?;
    Ok(())
}

#[tokio::test]
#[ignore = "requires qualified stock Firefox"]
async fn firefox_dom_response_watch_scope_and_cleanup()
-> StdResult<(), Box<dyn Error + Send + Sync>> {
    native_watch(BrowserEngine::Firefox).await
}

#[tokio::test]
#[ignore = "requires pinned Moli layout"]
async fn moli_dom_response_watch_scope_and_cleanup() -> StdResult<(), Box<dyn Error + Send + Sync>>
{
    native_watch(BrowserEngine::Moli).await
}
