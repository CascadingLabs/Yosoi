#![cfg(feature = "browser")]
//! Native Surface ownership, input and shared-pool scheduling against loopback only.
use futures::FutureExt;
use serde_json::{Value, json};
use std::{env, error::Error, io, sync::Arc, time::Duration};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
    sync::{Notify, oneshot},
    task::{JoinHandle, JoinSet},
    time::timeout,
};
use yosoi::{
    browser::surface::consume_session as consume_browser_session,
    policy::{Acquisition, BrowserMode, DocumentRequest, Page, Policy},
    session::{self, ActionKind, ExecutionPool, SessionPolicy},
    surface::{self, SurfaceConnection, SurfacePolicy, browser::BrowserSurface},
};

struct Fixture {
    base: String,
    stop: oneshot::Sender<()>,
    task: JoinHandle<()>,
}
impl Fixture {
    async fn start() -> Result<Self, Box<dyn Error>> {
        let listener = TcpListener::bind("127.0.0.1:0").await?;
        let base = format!("http://{}", listener.local_addr()?);
        let (stop, mut stopped) = oneshot::channel();
        let release = Arc::new(Notify::new());
        let task = tokio::spawn(async move {
            let mut clients = JoinSet::new();
            loop {
                tokio::select! {
                    _ = &mut stopped => break,
                    accepted = listener.accept() => {
                        let Ok((mut stream, _)) = accepted else { break; };
                        let release = Arc::clone(&release);
                        clients.spawn(async move {
                            let mut bytes = [0; 8192];
                            let Ok(count) = stream.read(&mut bytes).await else { return; };
                            let request = String::from_utf8_lossy(bytes.get(..count).unwrap_or_default());
                            let path = request.split_whitespace().nth(1).unwrap_or("/");
                            let body = match path {
                                "/await" => { release.notified().await; "Released A".to_string() },
                                "/release" => { release.notify_one(); "released".to_string() },
                                "/large" => format!("<!doctype html><title>{}</title><h1>Large title destination</h1>", "x".repeat(2000)),
                                "/a" => r#"<!doctype html><h1>Tab A</h1><p>Waiting A</p><script>fetch('/await').then(r=>r.text()).then(text=>document.querySelector('p').textContent=text)</script>"#.to_string(),
                                _ => r#"<!doctype html><h1>Tab B</h1><input aria-label="Message" value="existing content"><button onclick="this.nextElementSibling.textContent='Clicked B';fetch('/release')">Release A</button><p>Ready B</p><input aria-label="Keyboard" onkeydown="if(event.key==='Enter')this.nextElementSibling.textContent='Enter observed'"><p>Waiting for key</p><input aria-label="Steal source" value="original" onkeydown="if(event.key==='a'&&(event.ctrlKey||event.metaKey))this.nextElementSibling.focus()"><input aria-label="Steal destination" value="untouched" oninput="this.nextElementSibling.textContent='Foreign input changed'"><p>Foreign input untouched</p><a href="/large">Large document</a>"#.to_string(),
                            };
                            let response = format!("HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len());
                            let _ = stream.write_all(response.as_bytes()).await;
                        });
                    }
                    Some(_) = clients.join_next(), if !clients.is_empty() => {}
                }
            }
            clients.abort_all();
            while clients.join_next().await.is_some() {}
        });
        Ok(Self { base, stop, task })
    }
    async fn close(self) {
        let _ = self.stop.send(());
        let _ = self.task.await;
    }
}

fn enabled() -> bool {
    let enabled = env::var("YOSOI_BROWSER_TESTS").as_deref() == Ok("1");
    if !enabled {
        eprintln!("SKIPPED native Surface browser proof; set YOSOI_BROWSER_TESTS=1");
    }
    enabled
}

async fn reference(surface: &mut BrowserSurface, query: &str) -> Result<Value, Box<dyn Error>> {
    let result = surface.execute(json!({"op":"find","query":query})).await?;
    let entry = result
        .get("entries")
        .and_then(Value::as_array)
        .and_then(|items| items.first())
        .ok_or_else(|| io::Error::other("fixture target not found"))?;
    let mut reference = entry
        .get("reference")
        .cloned()
        .ok_or_else(|| io::Error::other("missing reference"))?;
    if entry.get("kind").and_then(Value::as_str) == Some("text") {
        reference = surface
            .execute(json!({"op":"parent","reference":reference}))
            .await?;
    }
    Ok(reference)
}

async fn hot(surface: &mut BrowserSurface) -> Result<(), Box<dyn Error>> {
    surface.execute(json!({"op":"attach"})).await?;
    let status = surface.execute(json!({"op":"status"})).await?;
    let root = status
        .get("root")
        .cloned()
        .ok_or_else(|| io::Error::other("status root missing"))?;
    surface
        .execute(json!({"op":"focus","reference":root}))
        .await?;
    surface.execute(json!({"op":"hot"})).await?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Keep Session and per-tab Work leases alive through the shared-pool interleaving; assertions verify ownership, and every lease is explicitly released before Session close."
)]
async fn consumed_surfaces_share_native_tab_ownership_and_yield_capacity()
-> Result<(), Box<dyn Error>> {
    if !enabled() {
        return Ok(());
    }
    let fixture = Fixture::start().await?;
    let policy = Policy {
        page: Page::new(vec![
            Acquisition::Browser(BrowserMode::Headless).documents([DocumentRequest::RenderedDom]),
        ])?,
        ..Policy::default()
    };
    let pool = ExecutionPool::new(1, 8)?;
    let native = session::new()
        .bind(&policy)
        .configure(SessionPolicy {
            maximum_tabs: 2,
            operation_timeout_ms: 10000,
            ..SessionPolicy::default()
        })
        .execution_pool(&pool)
        .acquire()
        .await?;
    let proof = Box::pin(async {
        let first = Box::pin(native.work()).await?;
        first.navigate(&format!("{}/a", fixture.base)).await?;
        let second = native.new_tab().await?;
        let work = second.work().await?;
        work.navigate(&format!("{}/b", fixture.base)).await?;
        let original_b = work.observe().await?;
        work.release().await?;
        let mut a = BrowserSurface::consume_work(first, SurfacePolicy::default()).await?;
        let mut b = BrowserSurface::consume_tab(&second, SurfacePolicy {
            archive: surface::ArchivePolicy::Enabled,
            ..SurfacePolicy::default()
        }).await?;
        hot(&mut a).await?;
        hot(&mut b).await?;
        assert!(Box::pin(native.work()).now_or_never().is_none(), "Surface must retain the existing tab's single Work owner");
        let mut events = pool.subscribe();
        let mut wait_a = Box::pin(a.execute(json!({"op":"wait","text":"Released A","present":true})));
        timeout(Duration::from_secs(5), async {
            loop {
                tokio::select! {
                    value = &mut wait_a => return Err(io::Error::other(format!("wait unexpectedly completed before sibling action: {value:?}"))),
                    _ = events.recv() => { if pool.snapshot().parked > 0 { return Ok(()); } }
                }
            }
        }).await??;
        let button = reference(&mut b, "Release A").await?;
        let clicked = b.execute(json!({"op":"click","reference":button,"expect":{"kind":"text","text":"Clicked B","present":true}})).await?;
        if clicked["receipt"]["status"] != "Confirmed" {
            drop(wait_a);
            a.close().await?;
            b.close().await?;
            return Err(io::Error::other(format!("native click did not confirm: {clicked:#}")).into());
        }
        assert!(clicked["outcome"]["native_receipt_id"].is_string());
        let waited = timeout(Duration::from_secs(5), &mut wait_a).await??;
        assert_eq!(waited["condition"]["state"], "text_matched");
        drop(wait_a);
        a.close().await?;
        let reacquired = Box::pin(native.work()).await?;
        reacquired.release().await?;
        let mut facade = surface::consume_session(native.clone(), SurfacePolicy::default()).await?;
        let old = facade.ready()?;
        assert_eq!(old["source"]["backend"], "native_session");
        facade.close().await?;
        let mut rebound = consume_browser_session(native.clone(), SurfacePolicy::default()).await?;
        let fresh = rebound.ready()?;
        assert_ne!(old["state"]["root"]["capture"], fresh["state"]["root"]["capture"],
            "reconnecting unchanged native evidence must not revive foreign binding references");
        assert!(rebound.execute(json!({"op":"inspect","reference":old["state"]["root"]})).await.is_err());
        rebound.close().await?;
        let message = reference(&mut b, "Message").await?;
        let filled = b.execute(json!({"op":"fill","reference":message,"text":"native input"})).await?;
        assert_eq!(filled["receipt"]["status"], "Confirmed");
        assert!(b.execute(json!({"op":"eligibility","reference":message})).await.is_err(), "pre-effect capture reference must become stale");
        let key = reference(&mut b, "Keyboard").await?;
        let keyed = b.execute(json!({"op":"key","reference":key,"key":"Enter","expect":{"kind":"text","text":"Enter observed","present":true}})).await?;
        assert_eq!(keyed["receipt"]["status"], "Confirmed");
        let ax = b.observe(surface::browser::BrowserRepresentation::Ax).await?;
        assert!(!ax.descriptor.controllable);
        let outcome = b.close().await?.ok_or_else(|| io::Error::other("native archive outcome missing"))?;
        assert!(outcome.record.observations().iter().all(|observation|
            observation.session_id == original_b.session_id && observation.tab_id == original_b.tab_id
                && observation.document_epoch == original_b.document_epoch));
        let released = outcome.record.operations().iter().find(|operation| operation.kind == "surface.released")
            .ok_or_else(|| io::Error::other("native release receipt missing"))?;
        assert_eq!(released.result.as_ref().and_then(|value|value.get("browser_closed_by_surface")), Some(&Value::Bool(false)));
        let rerun = surface::browser::archive::rerun(&outcome, SurfacePolicy { archive: surface::ArchivePolicy::Enabled, ..SurfacePolicy::default() }, 1, true).await;
        assert!(rerun.err().is_some_and(|error| error.to_string().contains("native Session/Work")),
            "generic rerun must not replace the consumed Session policy with a fresh driver");
        let work = second.work().await?;
        assert_eq!(work.observe().await?.document_epoch, original_b.document_epoch);
        work.release().await?;
        assert_eq!(pool.snapshot().active, 0);
        assert_eq!(pool.snapshot().parked, 0);
        Ok::<(), Box<dyn Error>>(())
    })
    .await;
    let closed = native.close().await;
    fixture.close().await;
    proof?;
    closed?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Keep Session, Work, and Surface owners alive while verifying archive cleanup, result bounds, and focus fencing; each is explicitly released before Session close."
)]
async fn native_setup_failure_finalizes_archive_and_focus_loss_stops_typing()
-> Result<(), Box<dyn Error>> {
    if !enabled() {
        return Ok(());
    }
    let fixture = Fixture::start().await?;
    let policy = Policy {
        page: Page::new(vec![
            Acquisition::Browser(BrowserMode::Headless).documents([DocumentRequest::RenderedDom]),
        ])?,
        ..Policy::default()
    };
    let native = session::new()
        .bind(&policy)
        .configure(SessionPolicy {
            maximum_result_bytes: 1024,
            ..SessionPolicy::default()
        })
        .acquire()
        .await?;
    let proof = Box::pin(async {
        let work = Box::pin(native.work()).await?;
        work.navigate(&format!("{}/b", fixture.base)).await?;
        let output = tempfile::tempdir()?;
        let mut constrained = SurfacePolicy {
            archive: surface::ArchivePolicy::Enabled,
            output: Some(output.path().join("output")),
            archive_root: Some(output.path().join("archive")),
            ..SurfacePolicy::default()
        };
        constrained.documents.dom.max_nodes = 1;
        let failed = BrowserSurface::consume_work(work, constrained).await;
        let error = match failed {
            Err(error) => error,
            Ok(mut source) => {
                source.close().await?;
                return Err(
                    io::Error::other("over-limit initial capture unexpectedly succeeded").into(),
                );
            }
        };
        let surface::ExecutionError::Execution { outcomes, .. } = error else {
            return Err(io::Error::other(
                "failed setup did not retain its partial archive outcome",
            )
            .into());
        };
        let outcome = outcomes
            .first()
            .ok_or_else(|| io::Error::other("partial setup outcome missing"))?;
        assert!(outcome.sealed);
        assert!(
            outcome
                .record
                .operations()
                .iter()
                .any(|operation| operation.kind == "surface.released")
        );
        let work = Box::pin(native.work()).await?;
        work.release().await?;
        let mut source = surface::consume_session(native.clone(), SurfacePolicy::default()).await?;
        hot(&mut source).await?;
        let field = reference(&mut source, "Message").await?;
        let replaced = source
            .execute(json!({"op":"fill","reference":field,"text":"replacement"}))
            .await?;
        assert_eq!(replaced["receipt"]["status"], "Confirmed");
        assert_eq!(replaced["outcome"]["value"]["characters"], 11);
        let field = reference(&mut source, "Steal source").await?;
        let stopped = source
            .execute(json!({"op":"fill","reference":field,"text":"must not reach another input"}))
            .await?;
        assert_eq!(stopped["receipt"]["status"], "Unconfirmed");
        let changed = source
            .execute(json!({"op":"find","query":"Foreign input changed"}))
            .await?;
        assert!(
            changed["entries"]
                .as_array()
                .ok_or_else(|| io::Error::other("find entries missing"))?
                .iter()
                .all(|entry| entry["kind"] != "text")
        );
        source.execute(json!({"op":"refresh"})).await?;
        let link = reference(&mut source, "Large document").await?;
        let bounded = source
            .execute(json!({"op":"click","reference":link,"expect":{"kind":"navigation"}}))
            .await?;
        assert_eq!(bounded["receipt"]["status"], "Unconfirmed");
        assert!(
            bounded["outcome"]["error"]
                .as_str()
                .is_some_and(|message| message.contains("byte limit")),
            "wait result must honor the native Session result limit: {bounded:#}"
        );
        source.close().await?;
        let work = Box::pin(native.work()).await?;
        assert_eq!(
            work.observe().await?.url.as_deref(),
            Some(format!("{}/large", fixture.base).as_str())
        );
        work.release().await?;
        Ok::<(), Box<dyn Error>>(())
    })
    .await;
    let closed = native.close().await;
    fixture.close().await;
    proof?;
    closed?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Keep the native Session and transferred Work alive for policy-denial checks, then explicitly release Work and close the shared Session."
)]
async fn consumed_surface_preserves_native_policy_without_arbitrary_javascript()
-> Result<(), Box<dyn Error>> {
    if !enabled() {
        return Ok(());
    }
    let fixture = Fixture::start().await?;
    let policy = Policy {
        page: Page::new(vec![
            Acquisition::Browser(BrowserMode::Headless).documents([DocumentRequest::RenderedDom]),
        ])?,
        ..Policy::default()
    };
    let mut settings = SessionPolicy::default();
    settings
        .allowed_actions
        .retain(|kind| !matches!(kind, ActionKind::EnterText | ActionKind::Scroll));
    let native = session::new()
        .bind(&policy)
        .configure(settings)
        .acquire()
        .await?;
    let proof = Box::pin(async {
        let work = Box::pin(native.work()).await?;
        assert!(matches!(
            work.evaluate("1").await,
            Err(session::SessionError::Denied)
        ));
        work.navigate(&format!("{}/b", fixture.base)).await?;
        work.release().await?;
        let mut source =
            surface::browser::consume_session(native.clone(), SurfacePolicy::default()).await?;
        hot(&mut source).await?;
        let field = reference(&mut source, "Message").await?;
        let denied = source
            .execute(json!({"op":"fill","reference":field,"text":"denied"}))
            .await?;
        assert_eq!(denied["receipt"]["status"], "Rejected");
        assert_eq!(denied["receipt"]["dispatched"], false);
        let status = source.execute(json!({"op":"status"})).await?;
        let root = status
            .get("root")
            .cloned()
            .ok_or_else(|| io::Error::other("status root missing"))?;
        let denied = source
            .execute(json!({"op":"scroll","reference":root,"delta_y":100}))
            .await?;
        assert_eq!(denied["receipt"]["status"], "Rejected");
        assert_eq!(denied["receipt"]["dispatched"], false);
        source.close().await?;
        let work = Box::pin(native.work()).await?;
        assert!(matches!(
            work.evaluate("1").await,
            Err(session::SessionError::Denied)
        ));
        work.release().await?;
        Ok::<(), Box<dyn Error>>(())
    })
    .await;
    let closed = native.close().await;
    fixture.close().await;
    proof?;
    closed?;
    Ok(())
}
