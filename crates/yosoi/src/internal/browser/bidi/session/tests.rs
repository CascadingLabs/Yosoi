#![allow(
    clippy::panic_in_result_fn,
    reason = "Test assertions describe the contract; setup failures propagate as errors."
)]
use super::*;
use crate::browser as browser_config;
use crate::internal::browser::{CapabilityState, SnapshotState, Viewport};
use crate::policy;
use crate::request;
use crate::session;
use std::error as std_error;
use tokio::sync as tokio_sync;
use tokio::time as tokio_time;

#[test]
fn remote_values_are_strict_and_bounded() -> Result<(), SessionError> {
    assert_eq!(
        remote_json(
            &json!({"type":"object","value":[["a",{"type":"array","value":[{"type":"number","value":2}]}]]}),
            0
        )?,
        json!({"a":[2]})
    );
    assert!(remote_json(&json!({"type":"node","sharedId":"secret"}), 0).is_err());
    assert!(remote_json(&json!({"type":"number","value":"NaN"}), 0).is_err());
    assert!(
        remote_json(
            &json!({"type":"object","value":[["a",{"type":"null"}],["a",{"type":"null"}]]}),
            0
        )
        .is_err()
    );
    assert!(remote_json(&json!({"type":"null"}), 33).is_err());
    Ok(())
}

async fn native(engine: BrowserEngine) -> Result<(), Box<dyn std_error::Error + Send + Sync>> {
    use tokio::{
        io::{AsyncReadExt, AsyncWriteExt},
        net::TcpListener,
    };
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let origin = format!("http://{}", listener.local_addr()?);
    let child_url = format!("http://localhost:{}/frame", listener.local_addr()?.port());
    let page_html = format!(
        "<!doctype html><title>native</title><button id='button' onclick='this.dataset.trusted=String(event.isTrusted)'>Click</button><input id='input' oninput='this.dataset.trusted=String(event.isTrusted)'><p>Hello</p><iframe onload='window.childLoaded=true' src='{child_url}'></iframe><a id='next' href='/after'>Next</a><a id='slow' href='/slow-after'>Slow</a>"
    );
    let (requested, navigation_requested) = tokio_sync::oneshot::channel();
    let (release_navigation, released) = tokio_sync::oneshot::channel();
    let server = tokio::spawn(async move {
        let mut requested = Some(requested);
        let mut released = Some(released);
        for _ in 0..128 {
            let Ok((mut stream, _)) = listener.accept().await else {
                break;
            };
            let mut request = [0u8; 8192];
            let Ok(Ok(count)) =
                tokio_time::timeout(Duration::from_secs(3), stream.read(&mut request)).await
            else {
                continue;
            };
            let request = request.get(..count).unwrap_or_default();
            if request.starts_with(b"GET /slow-after ") {
                if let Some(requested) = requested.take() {
                    let _ = requested.send(());
                }
                if let Some(released) = released.take() {
                    let _ = released.await;
                }
            }
            let body = if request.starts_with(b"GET /frame ") {
                "<title>Child</title><p>frame</p>"
            } else {
                page_html.as_str()
            };
            let response = format!(
                "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                body.len(),
                body
            );
            let _ = stream.write_all(response.as_bytes()).await;
            let _ = stream.shutdown().await;
        }
    });
    let cancellation = CancellationToken::new();
    let deadline = Instant::now()
        .checked_add(Duration::from_secs(30))
        .ok_or("deadline")?;
    let session = Session::launch(
        BrowserConfig {
            engine,
            moli_profile: if engine == BrowserEngine::Moli {
                browser_config::MoliProfile::Layout
            } else {
                browser_config::MoliProfile::Dom
            },
            moli_allow_private_networks: engine == BrowserEngine::Moli,
            ..BrowserConfig::default()
        },
        false,
        None,
        &cancellation,
        deadline,
    )
    .await?;
    let result = async {
        assert!(session.identity.executable.is_some());
        let owner = session.new_user_context(&cancellation, deadline).await?;
        assert!(session.new_page("foreign-context", &cancellation, deadline).await.is_err());
        assert!(session.remove_user_context("foreign-context", &cancellation, deadline).await.is_err());
        let page = session.new_page(&owner, &cancellation, deadline).await?;
        page.set_viewport(Viewport::custom(960, 640), &cancellation, deadline).await?;
        page.set_locale("fr-FR", &cancellation, deadline).await?;
        page.set_timezone("Asia/Tokyo", &cancellation, deadline).await?;
        page.navigate(&format!("{origin}/"), "complete", &cancellation, deadline).await?;
        let environment = page.evaluate("({width:innerWidth,height:innerHeight,locale:new Intl.DateTimeFormat().resolvedOptions().locale,timezone:new Intl.DateTimeFormat().resolvedOptions().timeZone})", &cancellation, deadline).await?.0;
        assert_eq!(environment, json!({"width":960,"height":640,"locale":"fr-FR","timezone":"Asia/Tokyo"}));
        {
            use crate::internal::browser::RenderingPreferences;
            use crate::internal::types::{ColorScheme, ReducedMotion};
            let media = "({dark:matchMedia('(prefers-color-scheme: dark)').matches,reduced:matchMedia('(prefers-reduced-motion: reduce)').matches})";
            let before = page.evaluate(media, &cancellation, deadline).await?.0;
            // The qualified Firefox and Moli releases do not implement this command.
            assert!(matches!(page.set_rendering_preferences(RenderingPreferences::new(Some(ColorScheme::Dark), Some(ReducedMotion::Reduce)), &cancellation, deadline).await, Err(SessionError::Unsupported("emulation.setMediaFeaturesOverride"))));
            assert_eq!(page.evaluate(media, &cancellation, deadline).await?.0, before);
        }
        if engine == BrowserEngine::Firefox {
            let layout = page.layout_snapshot(&cancellation, deadline).await?;
            assert_eq!(layout.layout_viewport.client_width, 960);
            assert_eq!(layout.layout_viewport.client_height, 640);
        }
        {
            use crate::internal::browser::{Bbox, ScreenshotOptions};
            let visual = page.visual_snapshot(ScreenshotOptions::default().viewport_only(), &cancellation, deadline).await?;
            assert_eq!((visual.image_width_pixels, visual.image_height_pixels),(960,640));
            let cropped = page.visual_snapshot(ScreenshotOptions::default().with_bbox(Bbox {x:10,y:10,width:40,height:30}), &cancellation, deadline).await?;
            assert_eq!((cropped.image_width_pixels,cropped.image_height_pixels),(40,30));
            page.evaluate("document.body.style.height='2000px';document.body.style.width='1800px';true",&cancellation,deadline).await?;
            let overflowing=page.visual_snapshot(ScreenshotOptions::default().viewport_only(),&cancellation,deadline).await?;
            assert_eq!((overflowing.image_width_pixels,overflowing.image_height_pixels),(960,640));
            assert_eq!(overflowing.capture_viewport.width_css_pixels().get(),960);
            if engine==BrowserEngine::Firefox {
                let layout=page.layout_snapshot(&cancellation,deadline).await?;
                assert!(layout.layout_viewport.client_width<960);
                assert!(layout.layout_viewport.client_height<640);
                assert!(layout.content_size.width>=1800.0);
                assert!(layout.content_size.height>=2000.0);
            }
            let full=page.visual_snapshot(ScreenshotOptions::default(),&cancellation,deadline).await?;
            assert!(full.image_width_pixels>=1800 && full.image_height_pixels>=2000);
            page.evaluate("document.body.style.height='';document.body.style.width='';true",&cancellation,deadline).await?;
            let mut high=Viewport::custom(960,640);high.device_scale_factor=2.0;
            page.set_viewport(high,&cancellation,deadline).await?;
            let high=page.visual_snapshot(ScreenshotOptions::default().viewport_only(),&cancellation,deadline).await?;
            assert_eq!((high.image_width_pixels,high.image_height_pixels),(1920,1280));
            assert_eq!(high.device_scale_factor,2.0);
            page.set_viewport(Viewport::custom(960,640),&cancellation,deadline).await?;
        }
        let (value, realm) = page.evaluate("({title:document.title, values:[true,null,2]})", &cancellation, deadline).await?;
        assert_eq!(value, json!({"title":"native","values":[true,null,2]}));
        assert_ne!(realm, "");
        assert_eq!(page.evaluate("() => 42", &cancellation, deadline).await?.0, json!(42));
        assert_eq!(page.evaluate("async function () { return Promise.resolve(43); }", &cancellation, deadline).await?.0, json!(43));
        let scope = page.document_scope(&cancellation, deadline).await?;
        let snapshot = page.rendered_dom_snapshot(100_000, &cancellation, deadline).await?;
        assert_eq!(snapshot.scope.epoch, scope.epoch);
        assert!(snapshot.bytes().windows(5).any(|bytes| bytes == b"Hello"));
        assert_eq!(page.rendered_dom_snapshot(10, &cancellation, deadline).await?.state, SnapshotState::Truncated);
        let mut wait = page.start_condition_wait("document.querySelector('#button').dataset.trusted==='true'", Duration::from_secs(5), &cancellation, deadline).await?;
        if engine == BrowserEngine::Moli {
            // The pinned engine rejects the standard BiDi element-origin shape.
            // Qualification uses the declared, revalidated viewport adapter.
            let nodes = page.command("browsingContext.locateNodes", json!({"context":page.context,"locator":{"type":"css","value":"#button"},"maxNodeCount":1}), &cancellation, deadline).await?;
            let shared = nodes.get("nodes").and_then(Value::as_array).and_then(|nodes| nodes.first()).and_then(|node| node.get("sharedId")).and_then(Value::as_str).ok_or("missing native node")?;
            let rejected = page.command("input.performActions", json!({"context":page.context,"actions":[{"type":"pointer","id":"standard-origin-witness","parameters":{"pointerType":"mouse"},"actions":[{"type":"pointerMove","origin":{"type":"element","element":{"sharedId":shared}},"x":0,"y":0},{"type":"pointerDown","button":0},{"type":"pointerUp","button":0}]}]}), &cancellation, deadline).await;
            assert!(matches!(rejected, Err(SessionError::Transport(BidiError::Protocol { code, .. })) if code == "invalid argument"));
            assert_eq!(page.evaluate("document.querySelector('#button').hasAttribute('data-trusted')", &cancellation, deadline).await?.0, json!(false));
        }
        page.click_unique_element("#button", &cancellation, deadline).await?;
        assert!(wait.finish().await?);
        drop(wait);
        page.type_into_unique_element("#input", "BiDi", &cancellation, deadline).await?;
        assert_eq!(page.evaluate("[document.querySelector('#input').value, document.querySelector('#input').dataset.trusted]", &cancellation, deadline).await?.0, json!(["BiDi","true"]));
        assert!(matches!(page.type_into_unique_element("#input", "\u{e007}", &cancellation, deadline).await, Err(SessionError::InvalidInput)));
        assert_eq!(page.evaluate("document.querySelector('#input').value", &cancellation, deadline).await?.0, json!("BiDi"));
        page.type_into_unique_element("#input", "€こんにちは😀", &cancellation, deadline).await?;
        assert_eq!(page.evaluate("document.querySelector('#input').value", &cancellation, deadline).await?.0, json!("BiDi€こんにちは😀"));
        assert!(matches!(page.click_unique_element("iframe", &cancellation, deadline).await, Err(SessionError::Unsupported(_))));
        assert!(page.screenshot_png(&cancellation, deadline).await?.len() > 8);
        let environment = page.environment_snapshot(&cancellation, deadline).await?;
        assert_eq!(environment.capabilities.screenshot, CapabilityState::Supported);
        assert_eq!(page.evaluate_in_frame("/frame", "document.title", &cancellation, deadline).await?, json!("Child"));
        page.click_unique_element("#next", &cancellation, deadline).await?;
        let after = page.document_scope(&cancellation, deadline).await?;
        assert_ne!(after.epoch, scope.epoch);
        assert!(after.url.as_ref().is_some_and(|url| url.as_str().ends_with("/after")));
        let stale = page.evaluate_realm("0", &realm, &cancellation, deadline).await;
        assert!(matches!(stale, Err(SessionError::Transport(error)) if error.remote_target_is_gone()));
        assert_eq!(page.evaluate("document.title", &cancellation, deadline).await?.0, json!("native"));
        page.evaluate("localStorage.removeItem('native-author-runs');true", &cancellation, deadline).await?;
        let clicking_page = page.clone();
        let clicking_token = cancellation.clone();
        let mut clicking = tokio::spawn(async move { clicking_page.click_unique_element("#slow", &clicking_token, deadline).await });
        tokio_time::timeout_at(deadline, navigation_requested).await??;
        if tokio_time::timeout(Duration::from_millis(30), &mut clicking).await.is_ok() {
            let _ = release_navigation.send(());
            return Err("native click completed before its pending document was released".into());
        }
        let evaluating_page = page.clone();
        let evaluating_token = cancellation.clone();
        let mut evaluating = tokio::spawn(async move {
            evaluating_page.evaluate("(()=>{const next=Number(localStorage.getItem('native-author-runs')||0)+1;localStorage.setItem('native-author-runs',String(next));return next})()", &evaluating_token, deadline).await
        });
        if tokio_time::timeout(Duration::from_millis(30), &mut evaluating).await.is_ok() {
            let _ = release_navigation.send(());
            return Err("author script ran against a document with an observed pending navigation".into());
        }
        let _ = release_navigation.send(());
        clicking.await??;
        assert_eq!(evaluating.await??.0, json!(1));
        assert!(page.document_scope(&cancellation, deadline).await?.url.is_some_and(|url| url.as_str().ends_with("/slow-after")));
        page.evaluate("(()=>{const node=document.createElement('button');node.id='moving';node.textContent='Moving';node.style.cssText='position:absolute;left:20px;top:300px;width:100px;height:30px';node.onmouseenter=()=>{node.style.left='300px'};node.onclick=()=>{node.dataset.clicked='yes'};document.body.append(node);return true})()", &cancellation, deadline).await?;
        assert!(matches!(page.click_unique_element("#moving", &cancellation, deadline).await, Err(SessionError::DocumentChanged | SessionError::InvalidInput)));
        assert_eq!(page.evaluate("document.querySelector('#moving').hasAttribute('data-clicked')", &cancellation, deadline).await?.0, json!(false));
        page.evaluate("(()=>{const node=document.createElement('button');node.id='offscreen';node.textContent='Offscreen';node.style.cssText='position:absolute;left:20px;top:2500px;width:100px;height:30px';node.onclick=event=>{node.dataset.trusted=String(event.isTrusted)};document.body.append(node);return true})()", &cancellation, deadline).await?;
        page.click_unique_element("#offscreen", &cancellation, deadline).await.map_err(|error| format!("offscreen input: {error}"))?;
        assert_eq!(page.evaluate("document.querySelector('#offscreen').dataset.trusted", &cancellation, deadline).await?.0, json!("true"));
        page.evaluate("localStorage.setItem('native-shared-scope','same-context');document.cookie='nativeSharedCookie=one; path=/';true", &cancellation, deadline).await?;
        let sibling = session.new_page(&owner, &cancellation, deadline).await?;
        sibling.navigate(&origin, "complete", &cancellation, deadline).await?;
        assert_eq!(sibling.evaluate("localStorage.getItem('native-shared-scope')", &cancellation, deadline).await?.0, json!("same-context"));
        assert_eq!(sibling.evaluate("document.cookie.includes('nativeSharedCookie=one')", &cancellation, deadline).await?.0, json!(true));
        let separate = session.new_user_context(&cancellation, deadline).await?;
        let isolated = session.new_page(&separate, &cancellation, deadline).await?;
        isolated.navigate(&origin, "complete", &cancellation, deadline).await?;
        assert_eq!(isolated.evaluate("localStorage.getItem('native-shared-scope')", &cancellation, deadline).await?.0, Value::Null);
        assert_eq!(isolated.evaluate("document.cookie.includes('nativeSharedCookie=one')", &cancellation, deadline).await?.0, json!(false));
        isolated.close(&cancellation, deadline).await?;
        drop(isolated);
        session.remove_user_context(&separate, &cancellation, deadline).await?;
        sibling.close(&cancellation, deadline).await?;
        drop(sibling);
        let error = page.evaluate("throw new Error('private-detail')", &cancellation, deadline).await;
        assert!(matches!(error, Err(SessionError::Script)));
        page.close(&cancellation, deadline).await?;
        assert!(page.ensure_owned().await.is_err());
        drop(page);
        session.remove_user_context(&owner, &cancellation, deadline).await?;
        Ok::<_, Box<dyn std_error::Error + Send + Sync>>(())
    }.await;
    let cleanup = session.close().await;
    drop(session);
    let sdk = if result.is_ok() && cleanup.is_ok() {
        public_sdk(engine, &origin).await
    } else {
        Ok(())
    };
    server.abort();
    let _ = server.await;
    result?;
    cleanup?;
    sdk?;
    Ok(())
}

#[expect(
    clippy::significant_drop_tightening,
    reason = "Work is consumed by async release before cleanup assertions."
)]
async fn public_sdk(
    engine: BrowserEngine,
    origin: &str,
) -> Result<(), Box<dyn std_error::Error + Send + Sync>> {
    use crate::{
        automation_record::OperationStatus,
        policy::{
            Acquisition, BrowserMode, DocumentRequest, MaximumElapsed, Page as PagePolicy, Policy,
        },
        request::{self, DocumentOutcome},
        session,
    };
    let mut policy = Policy {
        browser: BrowserConfig {
            engine,
            moli_profile: if engine == BrowserEngine::Moli {
                browser_config::MoliProfile::Layout
            } else {
                browser_config::MoliProfile::Dom
            },
            moli_allow_private_networks: engine == BrowserEngine::Moli,
            ..BrowserConfig::default()
        },
        page: PagePolicy::new(vec![
            Acquisition::Browser(BrowserMode::Headless).documents([DocumentRequest::RenderedDom]),
        ])?,
        ..Policy::default()
    };
    policy.request.maximum_elapsed = MaximumElapsed::try_from(30_000_000u64)?;
    let owner = session::new().bind(&policy).acquire().await?;
    let operations = async {
        let work = owner.work().await?;
        assert!(matches!(
            work.evaluate("document.body.dataset.forbidden='bad'").await,
            Err(session::SessionError::Denied)
        ));
        assert_eq!(
            work.navigate(origin).await?.status,
            OperationStatus::Observed
        );
        assert!(
            work.observe()
                .await?
                .html
                .is_some_and(|html| html.contains("Hello"))
        );
        assert_eq!(
            work.click("#missing-target").await?.status,
            OperationStatus::Rejected
        );
        assert_eq!(
            work.click("#button").await?.status,
            OperationStatus::Observed
        );
        assert_eq!(
            work.enter_text("#input", "SDK").await?.status,
            OperationStatus::Observed
        );
        assert_eq!(work.screenshot().await?.status, OperationStatus::Observed);
        assert_eq!(
            work.enter_text("#input", "\u{e007}").await?.status,
            OperationStatus::Rejected
        );
        assert_eq!(work.click("#next").await?.status, OperationStatus::Observed);
        assert!(
            work.observe()
                .await?
                .url
                .is_some_and(|url| url.ends_with("/after"))
        );
        let response = request::new(origin)
            .with_work(&work)
            .bind(&policy)
            .send()
            .await?;
        assert_eq!(response.attempts().len(), 1);
        assert!(
            response
                .attempts()
                .all(|attempt| attempt.state() == request::AttemptState::Completed)
        );
        assert_eq!(
            response
                .attempts()
                .flat_map(request::Attempt::documents)
                .count(),
            1
        );
        assert!(
            response
                .attempts()
                .flat_map(request::Attempt::documents)
                .all(|document| matches!(document.outcome(), DocumentOutcome::Produced(_))),
            "Work-bound DOM request failed: {:?}",
            response
                .attempts()
                .flat_map(request::Attempt::documents)
                .map(request::AttemptDocument::outcome)
                .collect::<Vec<_>>()
        );
        let mut source_policy = policy.clone();
        source_policy.page =
            PagePolicy::new(vec![Acquisition::Browser(BrowserMode::Headless).documents(
                [
                    DocumentRequest::ResponseDocument,
                    DocumentRequest::RenderedDom,
                ],
            )])?;
        if engine == BrowserEngine::Firefox {
            let source_response = request::new(origin)
                .with_work(&work)
                .bind(&source_policy)
                .send()
                .await?;
            assert_eq!(
                source_response
                    .attempts()
                    .flat_map(request::Attempt::documents)
                    .count(),
                2
            );
            assert!(
                source_response
                    .attempts()
                    .all(|attempt| attempt.state() == request::AttemptState::Completed),
                "{source_response:?}"
            );
            assert!(
                source_response
                    .attempts()
                    .flat_map(request::Attempt::documents)
                    .all(|document| matches!(document.outcome(), DocumentOutcome::Produced(_))),
                "{source_response:?}"
            );
        } else {
            let before = work.observe().await?.url;
            let denied = request::new(format!("{origin}/source-denied"))
                .with_work(&work)
                .bind(&source_policy)
                .send()
                .await?;
            assert!(
                denied.attempts().all(|attempt| attempt.state()
                    == request::AttemptState::Failed(
                        request::AttemptFailureKind::PolicyResolution
                    )),
                "{denied:?}"
            );
            assert_eq!(work.observe().await?.url, before);
        }
        let mut limited = policy.clone();
        limited.request.browser.dom_utf8_bytes = policy::AddressableByteLimit::try_from(16u64)?;
        let partial = request::new(origin)
            .with_work(&work)
            .bind(&limited)
            .send()
            .await?;
        assert_eq!(partial.attempts().len(), 1);
        assert!(partial.attempts().any(|attempt| {
            attempt.state() != request::AttemptState::Completed
                || attempt
                    .documents()
                    .any(|document| !matches!(document.outcome(), DocumentOutcome::Produced(_)))
        }));
        let mut queued = Box::pin(owner.work());
        assert!(
            tokio_time::timeout(Duration::from_millis(30), &mut queued)
                .await
                .is_err()
        );
        work.release().await?;
        let next = tokio_time::timeout(Duration::from_secs(2), queued).await??;
        assert!(
            next.observe()
                .await?
                .html
                .is_some_and(|html| html.contains("Hello"))
        );
        next.release().await?;
        Ok::<_, Box<dyn std_error::Error + Send + Sync>>(())
    }
    .await;
    let cleanup = owner.close().await;
    drop(owner);
    operations?;
    cleanup?;
    if engine == BrowserEngine::Moli {
        let settings = session::SessionPolicy {
            allowed_actions: vec![
                session::ActionKind::Navigate,
                session::ActionKind::Click,
                session::ActionKind::EnterText,
            ],
            ..session::SessionPolicy::default()
        };
        let restricted = session::new()
            .bind(&policy)
            .configure(settings)
            .acquire()
            .await?;
        let check = async {
            let work = restricted.work().await?;
            assert_eq!(
                work.navigate(origin).await?.status,
                OperationStatus::Observed
            );
            assert!(matches!(
                work.click("#button").await,
                Err(session::SessionError::Denied)
            ));
            assert!(matches!(
                work.enter_text("#input", "forbidden").await,
                Err(session::SessionError::Denied)
            ));
            assert!(
                work.observe()
                    .await?
                    .html
                    .is_some_and(|html| !html.contains("forbidden"))
            );
            work.release().await?;
            Ok::<_, Box<dyn std_error::Error + Send + Sync>>(())
        }
        .await;
        let cleanup = restricted.close().await;
        drop(restricted);
        check?;
        cleanup?;
        let mut dom_policy = policy.clone();
        dom_policy.browser.moli_profile = browser_config::MoliProfile::Dom;
        let dom_only = session::new().bind(&dom_policy).acquire().await?;
        let check = async {
            let work = dom_only.work().await?;
            assert_eq!(
                work.navigate(origin).await?.status,
                OperationStatus::Observed
            );
            assert_eq!(
                work.click("#button").await?.status,
                OperationStatus::Rejected
            );
            assert!(matches!(
                work.screenshot().await,
                Err(session::SessionError::Unsupported(_))
            ));
            assert!(
                work.observe()
                    .await?
                    .html
                    .is_some_and(|html| html.contains("Hello"))
            );
            work.release().await?;
            Ok::<_, Box<dyn std_error::Error + Send + Sync>>(())
        }
        .await;
        let cleanup = dom_only.close().await;
        drop(dom_only);
        check?;
        cleanup?;
    }
    let response = request::new(origin).bind(&policy).send().await?;
    assert_eq!(response.attempts().len(), 1);
    assert!(
        response
            .attempts()
            .all(|attempt| attempt.state() == request::AttemptState::Completed)
    );
    assert_eq!(
        response
            .attempts()
            .flat_map(request::Attempt::documents)
            .count(),
        1
    );
    assert!(
        response
            .attempts()
            .flat_map(request::Attempt::documents)
            .all(|document| matches!(document.outcome(), DocumentOutcome::Produced(_))),
        "standalone DOM request failed: {response:?}"
    );
    Ok(())
}

#[tokio::test]
#[ignore = "requires explicitly installed pinned Moli"]
async fn native_moli_session() -> Result<(), Box<dyn std_error::Error + Send + Sync>> {
    native(BrowserEngine::Moli).await
}

#[tokio::test]
#[ignore = "requires explicitly installed admitted regular Firefox"]
async fn native_firefox_session() -> Result<(), Box<dyn std_error::Error + Send + Sync>> {
    native(BrowserEngine::Firefox).await
}
