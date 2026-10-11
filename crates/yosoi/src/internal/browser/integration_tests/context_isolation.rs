//! Black-box state-binding and isolated-context lifecycle tests for
//! CAS-315/CAS-352.
//!
//! Requires local Chromium. Run serially:
//!
//!     cargo test -p yosoi --features browser --lib internal::browser::integration_tests::context_isolation --
//! --test-threads=1
#![allow(
    clippy::absolute_paths,
    clippy::expect_used,
    clippy::implicit_clone,
    clippy::panic,
    clippy::unwrap_used
)]

use std::{
    collections::HashMap,
    io::{Read, Write},
    net::{SocketAddr, TcpListener, TcpStream},
    num::NonZeroUsize,
    sync::{
        Arc,
        atomic::{AtomicBool, AtomicUsize, Ordering},
    },
    thread,
    time::Duration,
};

use crate::internal::browser::vendor::chromiumoxide::{
    browser::{Browser, CdpMode},
    cdp::browser_protocol::target::{
        EventTargetCreated, EventTargetDestroyed, GetBrowserContextsParams,
        SetDiscoverTargetsParams,
    },
    handler::HandlerConfig,
    listeners::{EventDelivery, EventListenerConfig, EventOverflowPolicy},
};
use crate::internal::browser::{
    BrowserSession, BrowserStateBinding, ContextDisposalState, NavigationCaptureOptions,
    NavigationCaptureReport, Page, ResponseBodyState,
};
use futures::StreamExt;
use tokio::{
    task::yield_now,
    time::{Instant, timeout},
};

struct Fixture {
    url: String,
    address: SocketAddr,
    stop: Arc<AtomicBool>,
    cache_requests: Arc<AtomicUsize>,
    thread: Option<thread::JoinHandle<()>>,
}

fn serve_fixture_connection(mut stream: TcpStream, cache_requests: &AtomicUsize) {
    stream
        .set_read_timeout(Some(Duration::from_secs(2)))
        .expect("bound fixture request read");
    let mut request = [0_u8; 4096];
    let read = stream.read(&mut request).unwrap_or(0);
    let request = String::from_utf8_lossy(request.get(..read).unwrap_or_default());
    let path = request
        .split_whitespace()
        .nth(1)
        .unwrap_or("/")
        .split('?')
        .next()
        .unwrap_or("/");
    let (content_type, body, extra_headers) = match path {
        "/sw.js" => (
            "application/javascript",
            "self.addEventListener('install',()=>self.skipWaiting());".to_string(),
            "Cache-Control: no-store\r\nService-Worker-Allowed: /\r\n",
        ),
        "/cache" => {
            cache_requests.fetch_add(1, Ordering::AcqRel);
            (
                "text/html",
                "<!doctype html><main>network-cache</main>".to_string(),
                "Cache-Control: public, max-age=3600\r\n",
            )
        }
        "/echo-header" => {
            let value = request
                .lines()
                .filter_map(|line| line.split_once(':'))
                .find_map(|(name, value)| {
                    name.eq_ignore_ascii_case("x-cas352-context")
                        .then(|| value.trim())
                })
                .unwrap_or("absent");
            (
                "text/html",
                format!("<!doctype html><main>{value}</main>"),
                "Cache-Control: no-store\r\n",
            )
        }
        _ => (
            "text/html",
            "<!doctype html><title>isolated fixture</title><main>fixture</main>".to_string(),
            "Cache-Control: no-store\r\n",
        ),
    };
    let response = format!(
        "HTTP/1.1 200 OK\r\nContent-Type: {content_type}\r\nContent-Length: {}\r\nConnection: close\r\n{extra_headers}\r\n{body}",
        body.len()
    );
    let _ = stream.write_all(response.as_bytes());
}

impl Fixture {
    fn start() -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind fixture");
        let address = listener.local_addr().expect("fixture address");
        let stop = Arc::new(AtomicBool::new(false));
        let cache_requests = Arc::new(AtomicUsize::new(0));
        let worker_stop = Arc::clone(&stop);
        let worker_cache_requests = Arc::clone(&cache_requests);
        let thread = thread::spawn(move || {
            let mut request_threads = Vec::new();
            loop {
                let (stream, _) = listener.accept().expect("fixture accept");
                if worker_stop.load(Ordering::Acquire) {
                    break;
                }
                let cache_requests = Arc::clone(&worker_cache_requests);
                request_threads.push(thread::spawn(move || {
                    serve_fixture_connection(stream, &cache_requests);
                }));
            }
            for request_thread in request_threads {
                request_thread.join().expect("join fixture request");
            }
        });
        Self {
            url: format!("http://{address}/"),
            address,
            stop,
            cache_requests,
            thread: Some(thread),
        }
    }

    fn url(&self, path: &str) -> String {
        format!("http://{}{path}", self.address)
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Release);
        let _ = TcpStream::connect(self.address);
        if let Some(thread) = self.thread.take() {
            thread.join().expect("join fixture");
        }
    }
}

async fn session() -> BrowserSession {
    BrowserSession::builder()
        .headless()
        .launch()
        .await
        .expect("launch Chromium")
}

async fn capture_navigation(page: &Page, url: &str) -> NavigationCaptureReport {
    let capture = page
        .arm_navigation_capture(NavigationCaptureOptions::default())
        .await
        .expect("arm navigation capture");
    page.goto_and_wait_for_idle(url, Duration::from_secs(8))
        .await
        .expect("navigation reached CDP network-idle event");
    capture.finish().await.expect("finish navigation capture")
}

#[tokio::test]
async fn session_close_before_reaps_the_launched_browser() {
    let browser = timeout(Duration::from_secs(20), BrowserSession::launch_headless())
        .await
        .expect("browser launch deadline")
        .expect("launch browser");
    browser
        .close_before(Instant::now() + Duration::from_secs(15))
        .await
        .expect("bounded close and reap");
}

#[tokio::test]
async fn disposable_context_removes_cookie_and_origin_storage_state() {
    let fixture = Fixture::start();
    let browser = session().await;

    let isolated = timeout(Duration::from_secs(15), browser.new_isolated_context())
        .await
        .expect("create isolated context timed out")
        .expect("isolated context");
    timeout(
        Duration::from_secs(15),
        isolated.page().navigate(&fixture.url),
    )
    .await
    .expect("isolated navigation timed out")
    .expect("navigate isolated page");
    assert_eq!(
        isolated.binding(),
        BrowserStateBinding::IsolatedBrowserContext
    );
    assert_eq!(
        isolated.page().state_binding(),
        BrowserStateBinding::IsolatedBrowserContext
    );

    timeout(
        Duration::from_secs(5),
        isolated.page().evaluate_js(
            r#"(() => {
                document.cookie = 'context_cookie=secret; path=/';
                localStorage.setItem('context_local', 'secret');
                sessionStorage.setItem('context_session', 'secret');
                return true;
            })()"#,
        ),
    )
    .await
    .expect("synchronous state seeding timed out")
    .expect("seed synchronous isolated state");

    timeout(
        Duration::from_secs(8),
        isolated.page().evaluate_js(
            r#"new Promise((resolve, reject) => {
                const request = indexedDB.open('context_db', 1);
                request.onupgradeneeded = () => request.result.createObjectStore('items');
                request.onsuccess = () => { request.result.close(); resolve(true); };
                request.onerror = () => reject(request.error);
            })"#,
        ),
    )
    .await
    .expect("IndexedDB seeding timed out")
    .expect("seed IndexedDB state");

    let report = timeout(Duration::from_secs(15), isolated.dispose())
        .await
        .expect("context disposal timed out");
    assert_eq!(
        report.state_binding,
        BrowserStateBinding::IsolatedBrowserContext
    );
    assert_eq!(report.disposal_state, ContextDisposalState::Disposed);
    assert!(report.cleanup_complete);

    let clean = timeout(Duration::from_secs(15), browser.new_isolated_context())
        .await
        .expect("create clean context timed out")
        .expect("clean context");
    timeout(Duration::from_secs(15), clean.page().navigate(&fixture.url))
        .await
        .expect("clean navigation timed out")
        .expect("navigate clean page");
    let observed = timeout(
        Duration::from_secs(15),
        clean.page().evaluate_js(
            r#"(async () => ({
                cookie: document.cookie,
                local: localStorage.getItem('context_local'),
                session: sessionStorage.getItem('context_session'),
                databases: (await indexedDB.databases()).map((entry) => entry.name)
            }))()"#,
        ),
    )
    .await
    .expect("clean-state inspection timed out")
    .expect("inspect clean state");
    assert_eq!(observed["cookie"], "");
    assert!(observed["local"].is_null());
    assert!(observed["session"].is_null());
    assert_eq!(observed["databases"].as_array().map(Vec::len), Some(0));

    assert!(
        timeout(Duration::from_secs(15), clean.dispose())
            .await
            .expect("clean context disposal timed out")
            .cleanup_complete
    );
    browser.close().await.expect("close browser");
}

#[tokio::test]
async fn independent_contexts_isolate_permissions_headers_and_renderer_state() {
    let fixture = Fixture::start();
    let browser = session().await;
    let context_a = browser.new_isolated_context().await.expect("context A");
    let context_b = browser.new_isolated_context().await.expect("context B");

    context_a
        .page()
        .navigate(&fixture.url)
        .await
        .expect("navigate A");
    context_b
        .page()
        .navigate(&fixture.url)
        .await
        .expect("navigate B");
    context_a
        .page()
        .add_init_script("globalThis.__cas352_renderer = 'a-only'")
        .await
        .expect("install A-only renderer state");
    context_a
        .page()
        .set_headers(HashMap::from([(
            "X-Cas352-Context".to_string(),
            "a-only".to_string(),
        )]))
        .await
        .expect("set A-only header");
    context_a
        .page()
        .set_geolocation(40.758, -73.9855, Some(10.0))
        .await
        .expect("grant geolocation only in context A");

    context_a
        .page()
        .goto_and_wait_for_idle(&fixture.url("/echo-header"), Duration::from_secs(8))
        .await
        .expect("navigate A to header echo");
    context_b
        .page()
        .goto_and_wait_for_idle(&fixture.url("/echo-header"), Duration::from_secs(8))
        .await
        .expect("navigate B to header echo");

    let state_a = context_a
        .page()
        .evaluate_js(
            r#"(async () => ({
                header: document.querySelector('main').textContent,
                renderer: globalThis.__cas352_renderer ?? null,
                geolocation: (await navigator.permissions.query({name: 'geolocation'})).state
            }))()"#,
        )
        .await
        .expect("observe context A state");
    let state_b = context_b
        .page()
        .evaluate_js(
            r#"(async () => ({
                header: document.querySelector('main').textContent,
                renderer: globalThis.__cas352_renderer ?? null,
                geolocation: (await navigator.permissions.query({name: 'geolocation'})).state
            }))()"#,
        )
        .await
        .expect("observe context B state");

    assert_eq!(state_a["header"], "a-only");
    assert_eq!(
        state_b["header"], "absent",
        "B observed A's extra request header"
    );
    assert_eq!(state_a["renderer"], "a-only");
    assert!(
        state_b["renderer"].is_null(),
        "B observed A's renderer init state"
    );
    assert_eq!(state_a["geolocation"], "granted");
    assert_eq!(
        state_b["geolocation"], "prompt",
        "B inherited A's browser-context permission grant"
    );

    assert!(context_a.dispose().await.cleanup_complete);
    assert!(context_b.dispose().await.cleanup_complete);
    browser.close().await.expect("close browser");
}

#[tokio::test]
async fn independent_contexts_isolate_cache_storage_http_cache_and_service_workers() {
    let fixture = Fixture::start();
    let browser = session().await;
    let context_a = browser.new_isolated_context().await.expect("context A");
    let context_b = browser.new_isolated_context().await.expect("context B");

    context_a
        .page()
        .navigate(&fixture.url)
        .await
        .expect("navigate A");
    context_b
        .page()
        .navigate(&fixture.url)
        .await
        .expect("navigate B");
    let cache_a = context_a
        .page()
        .evaluate_js(
            r#"(async () => {
                const cache = await caches.open('cas352-a-only');
                await cache.put('/cache-entry', new Response('a-only'));
                return {
                    names: await caches.keys(),
                    body: await (await cache.match('/cache-entry')).text()
                };
            })()"#,
        )
        .await
        .expect("seed and observe A CacheStorage");
    assert_eq!(cache_a["names"], serde_json::json!(["cas352-a-only"]));
    assert_eq!(cache_a["body"], "a-only");
    let cache_b = context_b
        .page()
        .evaluate_js("caches.keys()")
        .await
        .expect("observe B CacheStorage support and contents");
    assert_eq!(
        cache_b,
        serde_json::json!([]),
        "B observed A's CacheStorage entry"
    );

    let cache_url = fixture.url("/cache");
    context_a
        .page()
        .goto_and_wait_for_idle(&cache_url, Duration::from_secs(8))
        .await
        .expect("prime A HTTP cache");
    assert_eq!(fixture.cache_requests.load(Ordering::Acquire), 1);
    context_a
        .page()
        .navigate("about:blank")
        .await
        .expect("leave A cache resource");
    let cached_a = capture_navigation(context_a.page(), &cache_url).await;
    let cached_a_source = cached_a
        .main_document
        .expect("A cached main document observation");
    assert!(
        cached_a_source.from_cache,
        "A HTTP cache was not observably available"
    );
    assert_eq!(fixture.cache_requests.load(Ordering::Acquire), 1);

    let network_b = capture_navigation(context_b.page(), &cache_url).await;
    let network_b_source = network_b
        .main_document
        .expect("B main document observation");
    assert!(
        !network_b_source.from_cache,
        "B reused A's HTTP cache entry"
    );
    assert!(!network_b_source.from_service_worker);
    assert_eq!(network_b_source.body_state, ResponseBodyState::Available);
    assert_eq!(
        network_b_source.body(),
        b"<!doctype html><main>network-cache</main>"
    );
    assert_eq!(
        fixture.cache_requests.load(Ordering::Acquire),
        2,
        "B did not make its own observable network request"
    );

    context_a
        .page()
        .navigate(&fixture.url)
        .await
        .expect("return A to worker scope");
    let worker_a = timeout(
        Duration::from_secs(8),
        context_a.page().evaluate_js(
            r#"navigator.serviceWorker.register('/sw.js').then(async registration => ({
                has_worker: Boolean(registration.installing || registration.waiting || registration.active),
                registrations: (await navigator.serviceWorker.getRegistrations()).length
            }))"#,
        ),
    )
    .await
    .expect("A service-worker registration event timed out")
    .expect("register and observe A service worker");
    assert_eq!(worker_a["has_worker"], true);
    assert_eq!(worker_a["registrations"], 1);

    context_b
        .page()
        .navigate(&fixture.url)
        .await
        .expect("return B to worker scope");
    let workers_b = context_b
        .page()
        .evaluate_js("navigator.serviceWorker.getRegistrations().then(items => items.length)")
        .await
        .expect("observe B service-worker support and registrations");
    assert_eq!(workers_b, 0, "B observed A's service-worker registration");

    assert!(context_a.dispose().await.cleanup_complete);
    assert!(context_b.dispose().await.cleanup_complete);
    browser.close().await.expect("close browser");
}

#[tokio::test]
async fn additional_isolated_pages_share_only_their_context_and_are_disposed_together() {
    let fixture = Fixture::start();
    let browser = session().await;
    let isolated = browser
        .new_isolated_context()
        .await
        .expect("isolated context");
    let additional = isolated
        .new_blank_page()
        .await
        .expect("additional isolated page");

    assert_eq!(
        isolated.binding(),
        BrowserStateBinding::IsolatedBrowserContext
    );
    assert_eq!(
        isolated.page().state_binding(),
        BrowserStateBinding::IsolatedBrowserContext
    );
    assert_eq!(
        additional.state_binding(),
        BrowserStateBinding::IsolatedBrowserContext
    );

    isolated
        .page()
        .navigate(&fixture.url)
        .await
        .expect("navigate initial page");
    isolated
        .page()
        .evaluate_js("document.cookie = 'shared_context=present; path=/'")
        .await
        .expect("seed context cookie");
    additional
        .navigate(&fixture.url)
        .await
        .expect("navigate additional page");
    assert!(
        additional
            .evaluate_js("document.cookie")
            .await
            .expect("read context cookie")
            .as_str()
            .is_some_and(|cookies| cookies.contains("shared_context=present"))
    );

    let report = isolated.dispose().await;
    assert_eq!(
        report.state_binding,
        BrowserStateBinding::IsolatedBrowserContext
    );
    assert_eq!(report.disposal_state, ContextDisposalState::Disposed);
    assert!(
        report.cleanup_complete,
        "context cleanup covers every context page"
    );
    assert!(additional.evaluate_js("document.cookie").await.is_err());
    browser.close().await.expect("close browser");
}

#[tokio::test]
async fn dropping_context_disposes_its_page_without_leaking_a_target() {
    let fixture = Fixture::start();
    let browser = session().await;
    let isolated = browser
        .new_isolated_context()
        .await
        .expect("isolated context");
    isolated
        .page()
        .navigate(&fixture.url)
        .await
        .expect("navigate isolated page");
    let isolated_url = fixture.url.clone();
    let isolated_page = isolated.page_handle();

    drop(isolated);
    timeout(Duration::from_secs(15), isolated_page.wait_until_closed())
        .await
        .expect("dropped isolated context did not close its page target");
    assert!(isolated_page.url().await.is_err());
    for page in browser.pages().await.expect("list remaining pages") {
        assert_ne!(
            page.url()
                .await
                .expect("read remaining page URL")
                .as_deref(),
            Some(isolated_url.as_str()),
            "dropped isolated context left its page target in the browser handler"
        );
    }
    browser.close().await.expect("close browser");
}

#[tokio::test]
async fn cancelling_explicit_context_disposal_does_not_leak_the_context() {
    let browser = session().await;
    let fixture = Fixture::start();
    let isolated = browser
        .new_isolated_context()
        .await
        .expect("isolated context");
    isolated
        .page()
        .navigate(&fixture.url)
        .await
        .expect("navigate isolated page");
    let isolated_url = fixture.url.clone();
    let isolated_page = isolated.page_handle();

    let disposal = tokio::spawn(async move { isolated.dispose().await });
    yield_now().await;
    disposal.abort();
    let _ = disposal.await;

    timeout(Duration::from_secs(15), isolated_page.wait_until_closed())
        .await
        .expect("cancelled disposal did not close its page target");
    assert!(isolated_page.url().await.is_err());
    for page in browser.pages().await.expect("list remaining pages") {
        assert_ne!(
            page.url()
                .await
                .expect("read remaining page URL")
                .as_deref(),
            Some(isolated_url.as_str()),
            "cancelled isolated-context disposal left a page target in the browser handler"
        );
    }
    browser.close().await.expect("close browser");
}

#[tokio::test]
async fn cancelling_context_creation_after_the_cdp_request_disposes_the_context() {
    let browser = Arc::new(session().await);
    let (observer, mut handler) = Browser::connect_with_config(
        browser.websocket_url().await,
        HandlerConfig {
            cdp_mode: CdpMode::Minimal,
            ignore_invalid_messages: false,
            ..HandlerConfig::default()
        },
    )
    .await
    .expect("connect lifecycle observer");
    let observer_task = tokio::spawn(async move { while handler.next().await.is_some() {} });
    let config = EventListenerConfig::new(
        NonZeroUsize::new(32).expect("positive capacity"),
        EventOverflowPolicy::Close,
    );
    let mut created = observer
        .event_listener::<EventTargetCreated>(config)
        .await
        .expect("observe target creation");
    let mut destroyed = observer
        .event_listener::<EventTargetDestroyed>(config)
        .await
        .expect("observe target destruction");
    let initial_contexts = observer
        .execute(GetBrowserContextsParams::default())
        .await
        .expect("initial contexts")
        .result
        .browser_context_ids;
    observer
        .execute(SetDiscoverTargetsParams::new(true))
        .await
        .expect("enable target lifecycle events");

    let creating_browser = Arc::clone(&browser);
    let creating = tokio::spawn(async move { creating_browser.new_isolated_context().await });
    // Identify the newly created isolated context rather than sampling page
    // counts: Chrome's unrelated startup tab can arrive after any sample.
    let target = timeout(Duration::from_secs(10), async {
        while let Some(delivery) = created.next().await {
            let EventDelivery::Event(event) = delivery else {
                panic!("creation events overflowed")
            };
            if event.target_info.r#type == "page"
                && let Some(id) = event.target_info.browser_context_id.as_ref()
                && !initial_contexts.contains(id)
            {
                // Chrome can give its default startup tab a context ID too,
                // but GetBrowserContexts lists only explicitly created contexts.
                let private_contexts = observer
                    .execute(GetBrowserContextsParams::default())
                    .await
                    .expect("identify private context")
                    .result
                    .browser_context_ids;
                if private_contexts.contains(id) {
                    return event.target_info.clone();
                }
            }
        }
        panic!("creation event stream closed")
    })
    .await
    .expect("isolated target creation timed out");
    creating.abort();
    // If construction won the cancellation race, drop its delivered context
    // explicitly; both cancellation boundaries must release the same target.
    drop(creating.await);
    timeout(Duration::from_secs(10), async {
        while let Some(delivery) = destroyed.next().await {
            let EventDelivery::Event(event) = delivery else {
                panic!("destruction events overflowed")
            };
            if event.target_id == target.target_id {
                return;
            }
        }
        panic!("destruction event stream closed")
    })
    .await
    .expect("cancelled context creation left its target behind");
    let contexts = observer
        .execute(GetBrowserContextsParams::default())
        .await
        .expect("remaining contexts")
        .result
        .browser_context_ids;
    assert!(
        !target
            .browser_context_id
            .as_ref()
            .is_some_and(|id| contexts.contains(id)),
        "cancelled context creation left its browser context behind"
    );
    drop(observer);
    observer_task.abort();
    let _ = observer_task.await;
    browser.close().await.expect("close browser");
}

#[tokio::test]
async fn cancelling_session_close_can_be_retried() {
    let browser = Arc::new(session().await);
    let closing_browser = Arc::clone(&browser);
    let closing = tokio::spawn(async move { closing_browser.close().await });
    yield_now().await;
    closing.abort();
    let _ = closing.await;

    timeout(Duration::from_secs(15), browser.close())
        .await
        .expect("retried close timed out")
        .expect("retried close failed");
    browser
        .close()
        .await
        .expect("completed close is idempotent");
}

#[tokio::test]
async fn ordinary_session_pages_are_explicitly_shared_not_isolated() {
    let browser = session().await;
    let page = browser.new_blank_page().await.expect("shared page");
    assert_eq!(
        page.state_binding(),
        BrowserStateBinding::SharedBrowserProfile
    );
    assert!(!page.state_binding().is_isolated());
    page.close().await.expect("close page");
    browser.close().await.expect("close browser");
}
