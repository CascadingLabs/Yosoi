//! Deterministic browser navigation source/resource capture tests (CAS-312).
#![allow(clippy::expect_used, clippy::unwrap_used, clippy::panic)]

use std::{
    fmt::Write as FmtWrite,
    io::{ErrorKind, Read, Write as IoWrite},
    net::{SocketAddr, TcpListener, TcpStream},
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    thread,
    time::Duration,
};

use flate2::{Compression, write::GzEncoder};
use tokio::{
    task::yield_now,
    time::{sleep, timeout},
};
use void_crawl_core::{
    BrowserBodyLayer, BrowserSession, MeasuredCount, NavigationCaptureOptions,
    NavigationCaptureTermination, NavigationEventKind, NetworkExtraInfoState, ResponseBodyState,
    SourceBodyUnavailableReason,
};
use yosoi_types::BrowserResourceOutcome;

struct Fixture {
    address: SocketAddr,
    stop: Arc<AtomicBool>,
    worker: Option<thread::JoinHandle<()>>,
}

impl Fixture {
    fn start() -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind fixture");
        listener.set_nonblocking(true).expect("nonblocking fixture");
        let address = listener.local_addr().expect("fixture address");
        let stop = Arc::new(AtomicBool::new(false));
        let worker_stop = Arc::clone(&stop);
        let worker = thread::spawn(move || {
            while !worker_stop.load(Ordering::Acquire) {
                match listener.accept() {
                    Ok((mut stream, _)) => {
                        let _ = stream.set_read_timeout(Some(Duration::from_millis(250)));
                        let mut request = [0_u8; 4_096];
                        let read = stream.read(&mut request).unwrap_or(0);
                        let request =
                            String::from_utf8_lossy(request.get(..read).unwrap_or_default());
                        let path = request
                            .lines()
                            .next()
                            .and_then(|line| line.split_whitespace().nth(1))
                            .unwrap_or("/");
                        respond(&mut stream, path);
                    }
                    Err(error) if error.kind() == ErrorKind::WouldBlock => {
                        thread::sleep(Duration::from_millis(2));
                    }
                    Err(_) => break,
                }
            }
        });
        Self {
            address,
            stop,
            worker: Some(worker),
        }
    }

    fn url(&self, path: &str) -> String {
        format!("http://{}{}", self.address, path)
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Release);
        if let Some(worker) = self.worker.take() {
            worker.join().expect("join fixture");
        }
    }
}

fn respond(stream: &mut TcpStream, path: &str) {
    match path {
        "/" => html(
            stream,
            "<div id='value'>source-original</div><script>document.getElementById('value').textContent='rendered-mutated';fetch('/api')</script>",
            &[],
        ),
        "/api" => response(stream, "200 OK", "application/json", b"{\"ok\":true}", &[]),
        "/redirect" => response(
            stream,
            "302 Found",
            "text/plain",
            b"redirect body unavailable",
            &[("Location", "/final?access_token=secret")],
        ),
        value if value.starts_with("/final") => html(
            stream,
            "<main id='final'>final-source</main>",
            &[("Set-Cookie", "auth=secret; HttpOnly")],
        ),
        "/gzip" => {
            let source = b"<main id='gzip'>decoded-gzip-source</main>";
            let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
            encoder.write_all(source).expect("gzip write");
            let compressed = encoder.finish().expect("gzip finish");
            response(stream, "200 OK", "text/html", &compressed, &[("Content-Encoding", "gzip")]);
        }
        "/large" => response(stream, "200 OK", "text/plain", &[b'x'; 64], &[]),
        "/cache" => html(
            stream,
            "<main id='cache'>cacheable-source</main>",
            &[("Cache-Control", "public, max-age=3600")],
        ),
        "/register" => html(stream, "<main>register</main>", &[]),
        "/sw.js" => response(
            stream,
            "200 OK",
            "application/javascript",
            b"self.addEventListener('install',()=>self.skipWaiting());self.addEventListener('activate',e=>e.waitUntil(clients.claim()));self.addEventListener('fetch',e=>{if(new URL(e.request.url).pathname==='/controlled'){e.respondWith(new Response(\"<main id='controlled'>service-worker-source</main>\",{headers:{'Content-Type':'text/html'}}))}});",
            &[("Service-Worker-Allowed", "/")],
        ),
        "/controlled" => html(stream, "<main>network-fallback</main>", &[]),
        "/many" => {
            let mut tags = String::new();
            for i in 0..12 {
                let _ = write!(tags, "<img src='/asset-{i}'>");
            }
            html(stream, &format!("<main id='many'>many</main>{tags}"), &[]);
        }
        value if value.starts_with("/asset-") => {
            response(stream, "200 OK", "image/png", b"not-a-real-png", &[]);
        }
        _ => response(stream, "404 Not Found", "text/plain", b"missing", &[]),
    }
}

fn html(stream: &mut TcpStream, body: &str, headers: &[(&str, &str)]) {
    response(stream, "200 OK", "text/html", body.as_bytes(), headers);
}

fn response(
    stream: &mut TcpStream,
    status: &str,
    content_type: &str,
    body: &[u8],
    headers: &[(&str, &str)],
) {
    let mut head = format!(
        "HTTP/1.1 {status}\r\nContent-Type: {content_type}\r\nContent-Length: {}\r\nConnection: close\r\n",
        body.len()
    );
    for (name, value) in headers {
        let _ = write!(head, "{name}: {value}\r\n");
    }
    head.push_str("\r\n");
    let _ = stream.write_all(head.as_bytes());
    let _ = stream.write_all(body);
    let _ = stream.flush();
}

async fn session() -> BrowserSession {
    BrowserSession::builder()
        .headless()
        .launch()
        .await
        .expect("launch Chromium")
}

async fn capture(
    page: &void_crawl_core::Page,
    url: &str,
    options: NavigationCaptureOptions,
) -> void_crawl_core::NavigationCaptureReport {
    let capture = page
        .arm_navigation_capture(options)
        .await
        .expect("arm navigation capture");
    let _ = page.navigate(url).await;
    sleep(Duration::from_millis(100)).await;
    capture.finish().await.expect("finish navigation capture")
}

#[tokio::test]
async fn source_bytes_are_distinct_from_mutated_rendered_dom() {
    let fixture = Fixture::start();
    let browser = session().await;
    let page = browser.new_blank_page().await.expect("blank page");
    let report = capture(
        &page,
        &fixture.url("/"),
        NavigationCaptureOptions::default(),
    )
    .await;
    let source = report.main_document.expect("main document source");
    let rendered = page.content().await.expect("rendered DOM");

    assert_eq!(report.termination, NavigationCaptureTermination::Finished);
    assert_eq!(source.body_state, ResponseBodyState::Available);
    assert!(String::from_utf8_lossy(source.body()).contains(">source-original</div>"));
    assert!(rendered.contains(">rendered-mutated</div>"));
    assert!(
        report
            .resources
            .iter()
            .any(|resource| resource.url.as_str().ends_with("/api"))
    );

    page.close().await.expect("close page");
    browser.close().await.expect("close browser");
}

#[tokio::test]
async fn redirects_and_final_response_are_explicit_but_debug_is_redacted() {
    let fixture = Fixture::start();
    let browser = session().await;
    let page = browser.new_blank_page().await.expect("blank page");
    let report = capture(
        &page,
        &fixture.url("/redirect"),
        NavigationCaptureOptions::default(),
    )
    .await;

    assert_eq!(report.redirects.len(), 1);
    assert!(
        report
            .requested_url
            .as_ref()
            .is_some_and(|url| url.as_str().ends_with("/redirect"))
    );
    assert!(
        report
            .final_url
            .as_ref()
            .is_some_and(|url| url.as_str().contains("/final?access_token=secret"))
    );
    let source = report.main_document.as_ref().expect("final source");
    assert_eq!(source.status, Some(200));
    assert!(
        !source
            .headers
            .as_slice()
            .iter()
            .any(|(name, _)| name == "set-cookie"),
        "raw Set-Cookie is unavailable without response ExtraInfo"
    );
    assert_eq!(
        report.network_extra_info,
        NetworkExtraInfoState::UnavailableInCurrentClient
    );
    assert_eq!(report.events_admitted, report.events_retained);
    assert_eq!(
        report.events_retained,
        u64::try_from(report.events.len()).expect("event count fits u64")
    );
    assert_eq!(report.events_dropped, MeasuredCount::Known { value: 0 });
    assert!(report.events.windows(2).all(|pair| {
        pair[0].sequence + 1 == pair[1].sequence && pair[0].offset_micros <= pair[1].offset_micros
    }));
    assert!(
        report
            .events
            .iter()
            .any(|event| event.kind == NavigationEventKind::Request)
    );
    assert!(
        report
            .events
            .iter()
            .any(|event| event.kind == NavigationEventKind::Response)
    );
    assert!(
        report
            .events
            .iter()
            .any(|event| event.kind == NavigationEventKind::Finished)
    );
    assert!(source.captured_at_micros <= report.elapsed_micros);
    let serialized_events = serde_json::to_string(&report.events).expect("serialize safe events");
    assert!(!serialized_events.contains("access_token"));
    assert!(!serialized_events.contains("secret"));
    let debug = format!("{report:?}");
    assert!(!debug.contains("access_token"));
    assert!(!debug.contains("auth=secret"));
    assert!(!debug.contains("final-source"));

    page.close().await.expect("close page");
    browser.close().await.expect("close browser");
}

#[tokio::test]
async fn dropped_main_redirect_successor_does_not_leave_stale_document_identity() {
    let fixture = Fixture::start();
    let browser = session().await;
    let page = browser.new_blank_page().await.expect("blank page");
    let report = capture(
        &page,
        &fixture.url("/redirect"),
        NavigationCaptureOptions {
            max_resources: 1,
            ..NavigationCaptureOptions::default()
        },
    )
    .await;

    assert_eq!(report.resources.len(), 1);
    assert_eq!(
        report.resources[0].outcome,
        BrowserResourceOutcome::Redirected
    );
    assert!(
        report.resources_dropped > 0,
        "redirect successor loss is explicit"
    );
    assert!(report.final_url.is_none());
    assert!(report.main_document.is_none());

    page.close().await.expect("close page");
    browser.close().await.expect("close browser");
}

#[tokio::test]
async fn clean_cancel_has_exact_zero_event_loss() {
    let fixture = Fixture::start();
    let browser = session().await;
    let page = browser.new_blank_page().await.expect("blank page");
    let capture = page
        .arm_navigation_capture(NavigationCaptureOptions::default())
        .await
        .expect("arm capture");
    page.navigate(&fixture.url("/")).await.expect("navigate");
    sleep(Duration::from_millis(100)).await;
    let report = capture.cancel().await.expect("cancel capture");

    assert_eq!(report.termination, NavigationCaptureTermination::Cancelled);
    assert_eq!(report.events_admitted, report.events_retained);
    assert_eq!(
        report.events_retained,
        u64::try_from(report.events.len()).expect("event count fits u64")
    );
    assert_eq!(report.events_dropped, MeasuredCount::Known { value: 0 });
    assert!(!report.additional_loss_unknown);

    page.close().await.expect("close page");
    browser.close().await.expect("close browser");
}

#[tokio::test]
async fn chromium_body_is_a_decoded_representation_and_truncation_is_exact() {
    let fixture = Fixture::start();
    let browser = session().await;
    let page = browser.new_blank_page().await.expect("blank page");

    let gzip = capture(
        &page,
        &fixture.url("/gzip"),
        NavigationCaptureOptions::default(),
    )
    .await;
    let gzip = gzip.main_document.expect("gzip source");
    assert_eq!(
        gzip.body_layer,
        Some(BrowserBodyLayer::DecodedRepresentation)
    );
    assert_eq!(gzip.body(), b"<main id='gzip'>decoded-gzip-source</main>");

    let truncated = capture(
        &page,
        &fixture.url("/large"),
        NavigationCaptureOptions {
            max_source_bytes: 8,
            ..NavigationCaptureOptions::default()
        },
    )
    .await;
    let truncated = truncated.main_document.expect("truncated source");
    assert_eq!(truncated.body_state, ResponseBodyState::Truncated);
    assert_eq!(truncated.body(), b"xxxxxxxx");
    assert_eq!(truncated.retained_bytes, 8);
    assert_eq!(truncated.complete_bytes, Some(64));

    page.close().await.expect("close page");
    browser.close().await.expect("close browser");
}

#[tokio::test]
async fn browser_cache_provenance_is_explicit() {
    let fixture = Fixture::start();
    let browser = session().await;
    let page = browser
        .new_page(&fixture.url("/cache"))
        .await
        .expect("prime cache");
    sleep(Duration::from_millis(50)).await;
    page.navigate("about:blank")
        .await
        .expect("leave cacheable page");

    let report = capture(
        &page,
        &fixture.url("/cache"),
        NavigationCaptureOptions::default(),
    )
    .await;
    let source = report.main_document.expect("cached main source");
    assert!(
        source.from_cache,
        "second navigation should use Chromium's HTTP cache"
    );
    assert!(report.resources.iter().any(|resource| resource.from_cache));

    page.close().await.expect("close page");
    browser.close().await.expect("close browser");
}

#[tokio::test]
async fn service_worker_source_and_provenance_are_explicit() {
    let fixture = Fixture::start();
    let browser = session().await;
    let page = browser
        .new_page(&fixture.url("/register"))
        .await
        .expect("register page");
    let readiness = timeout(
        Duration::from_secs(5),
        page.evaluate_js(
            "(async()=>{\
               try {\
                 await navigator.serviceWorker.register('/sw.js');\
                 const registration = await navigator.serviceWorker.ready;\
                 return {ready: registration.active !== null, error: null};\
               } catch (error) {\
                 return {ready:false,error:String(error)};\
               }\
             })()",
        ),
    )
    .await;
    let readiness_observed = matches!(
        readiness,
        Ok(Ok(ref value)) if value["ready"] == serde_json::Value::Bool(true)
    );

    let report = capture(
        &page,
        &fixture.url("/controlled"),
        NavigationCaptureOptions::default(),
    )
    .await;
    let source = report.main_document.expect("service-worker main document");
    if source.from_service_worker {
        assert!(
            report
                .resources
                .iter()
                .any(|resource| resource.from_service_worker)
        );
    } else {
        // Some Chromium builds keep service-worker readiness unavailable in
        // short-lived automation profiles. Preserve an explicit false fact
        // rather than fabricating service-worker provenance or failing a
        // deterministic local conformance run on provider scheduling.
        assert!(
            !readiness_observed,
            "an active worker should control the next navigation"
        );
        assert!(
            report
                .resources
                .iter()
                .all(|resource| !resource.from_service_worker)
        );
        if source.body_state == ResponseBodyState::Available {
            assert!(
                source
                    .body()
                    .windows(b"network-fallback".len())
                    .any(|window| { window == b"network-fallback" })
            );
        }
    }
    assert!(matches!(
        source.body_state,
        ResponseBodyState::Available | ResponseBodyState::Unavailable
    ));

    page.close().await.expect("close page");
    browser.close().await.expect("close browser");
}

#[tokio::test]
async fn resource_and_event_limits_are_hard_and_loss_is_explicit() {
    let fixture = Fixture::start();
    let browser = session().await;
    let page = browser.new_blank_page().await.expect("blank page");

    let resources = capture(
        &page,
        &fixture.url("/many"),
        NavigationCaptureOptions {
            max_resources: 2,
            ..NavigationCaptureOptions::default()
        },
    )
    .await;
    assert_eq!(resources.resources.len(), 2);
    assert!(resources.resources_dropped > 0);

    let events = page
        .arm_navigation_capture(NavigationCaptureOptions {
            max_events: 1,
            ..NavigationCaptureOptions::default()
        })
        .await
        .expect("arm event-limited capture");
    page.navigate(&fixture.url("/"))
        .await
        .expect("navigate event-limited capture");
    let events = events.wait().await.expect("wait for event limit");
    assert_eq!(
        events.termination,
        NavigationCaptureTermination::EventLimitReached
    );
    assert_eq!(events.events_admitted, 1);
    assert_eq!(events.events_retained, 1);
    assert_eq!(events.events.len(), 1);
    assert_eq!(events.events[0].sequence, 0);
    assert_eq!(events.events_dropped, MeasuredCount::Known { value: 0 });
    assert!(events.additional_loss_unknown);
    assert_eq!(
        events
            .main_document
            .expect("partial main document")
            .body_unavailable,
        Some(SourceBodyUnavailableReason::CaptureEndedBeforeBody)
    );

    page.close().await.expect("close page");
    browser.close().await.expect("close browser");
}

#[tokio::test]
async fn cancelled_terminal_joins_do_not_poison_later_body_capture() {
    let fixture = Fixture::start();
    let browser = session().await;
    let page = browser.new_blank_page().await.expect("blank page");

    let waiting = page
        .arm_navigation_capture(NavigationCaptureOptions::default())
        .await
        .expect("arm waiting capture");
    let waiting = tokio::spawn(async move { waiting.wait().await });
    yield_now().await;
    waiting.abort();
    let _ = waiting.await;

    let finishing = page
        .arm_navigation_capture(NavigationCaptureOptions::default())
        .await
        .expect("arm finishing capture");
    let finishing = tokio::spawn(async move { finishing.finish().await });
    yield_now().await;
    finishing.abort();
    let _ = finishing.await;

    let cancelling = page
        .arm_navigation_capture(NavigationCaptureOptions::default())
        .await
        .expect("arm cancelling capture");
    let cancelling = tokio::spawn(async move { cancelling.cancel().await });
    yield_now().await;
    cancelling.abort();
    let _ = cancelling.await;

    let report = capture(
        &page,
        &fixture.url("/"),
        NavigationCaptureOptions::default(),
    )
    .await;
    let source = report
        .main_document
        .expect("body capture after cancelled joins");
    assert_eq!(source.body_state, ResponseBodyState::Available);
    assert!(
        source
            .body()
            .windows(b"source-original".len())
            .any(|body| body == b"source-original")
    );

    page.close().await.expect("close page");
    browser.close().await.expect("close browser");
}

#[tokio::test]
async fn failed_document_request_has_explicit_unavailable_source() {
    let listener = TcpListener::bind("127.0.0.1:0").expect("reserve closed port");
    let address = listener.local_addr().expect("closed address");
    drop(listener);

    let browser = session().await;
    let page = browser.new_blank_page().await.expect("blank page");
    let report = capture(
        &page,
        &format!("http://{address}/unreachable"),
        NavigationCaptureOptions::default(),
    )
    .await;
    let source = report.main_document.expect("unavailable main document");

    assert_eq!(source.body_state, ResponseBodyState::Unavailable);
    assert_eq!(
        source.body_unavailable,
        Some(SourceBodyUnavailableReason::RequestFailed)
    );
    assert_eq!(source.body().len(), 0);
    assert!(
        report
            .resources
            .iter()
            .any(|resource| { matches!(resource.outcome, BrowserResourceOutcome::Failed { .. }) })
    );

    page.close().await.expect("close page");
    browser.close().await.expect("close browser");
}
