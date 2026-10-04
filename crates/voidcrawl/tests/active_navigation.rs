//! Black-box acceptance contract for CAS-357 active navigation.
//!
//! The loopback fixture is explicitly event-gated: it never uses `sleep` or
//! polling as readiness detection. Run serially with a local Chromium:
//!
//!     CARGO_BUILD_JOBS=1 cargo test -p void_crawl_core --test active_navigation -- --test-threads=1
//!
//! ## Public contract exercised here
//!
//! `Page::start_navigation(url, ActiveNavigationOptions)` starts a top-frame
//! navigation and returns `ActiveNavigation`. `next_progress(&mut self)`
//! yields typed, ordered `NavigationProgress` items; `wait(self)` and
//! `cancel(self)` consume the handle and yield the sole `NavigationReport`.
//! Terminal state is deliberately not a progress event. The report exposes a
//! `termination`, progress accounting (`admitted`, `retained`, `dropped`), and
//! `cleanup_complete`, but does not retain the progress stream.
#![allow(clippy::expect_used, clippy::panic, clippy::unwrap_used)]

use std::{
    num::NonZeroUsize,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    time::Duration,
};

use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    sync::{Notify, oneshot},
    task::JoinHandle,
    time::timeout,
};
use void_crawl_core::{
    ActiveNavigation, ActiveNavigationOptions, BrowserSession, MeasuredCount, NavigationProgress,
    NavigationProgressKind, NavigationReport, NavigationTermination, Page,
};

const NAVIGATION_DEADLINE: Duration = Duration::from_secs(5);
const FIXTURE_DEADLINE: Duration = Duration::from_secs(10);

struct Gate {
    arrived: AtomicBool,
    released: AtomicBool,
    arrival: Notify,
    release: Notify,
}

impl Gate {
    fn new() -> Self {
        Self {
            arrived: AtomicBool::new(false),
            released: AtomicBool::new(false),
            arrival: Notify::new(),
            release: Notify::new(),
        }
    }

    fn mark_arrived(&self) {
        self.arrived.store(true, Ordering::Release);
        self.arrival.notify_waiters();
    }

    async fn wait_for_arrival(&self) {
        while !self.arrived.load(Ordering::Acquire) {
            self.arrival.notified().await;
        }
    }

    fn open(&self) {
        self.released.store(true, Ordering::Release);
        self.release.notify_waiters();
    }

    async fn wait_until_open(&self) {
        while !self.released.load(Ordering::Acquire) {
            self.release.notified().await;
        }
    }
}

struct Fixture {
    base_url: String,
    hold: Arc<Gate>,
    shutdown: Option<oneshot::Sender<()>>,
    server: JoinHandle<()>,
}

impl Fixture {
    async fn start() -> Self {
        let listener = TcpListener::bind("127.0.0.1:0")
            .await
            .expect("bind loopback fixture");
        let address = listener.local_addr().expect("fixture address");
        let hold = Arc::new(Gate::new());
        let server_hold = Arc::clone(&hold);
        let (shutdown, mut shutdown_rx) = oneshot::channel();
        let server = tokio::spawn(async move {
            loop {
                tokio::select! {
                    _ = &mut shutdown_rx => return,
                    accepted = listener.accept() => match accepted {
                        Ok((stream, _)) => {
                            let gate = Arc::clone(&server_hold);
                            tokio::spawn(async move { serve(stream, gate).await; });
                        }
                        Err(_) => return,
                    },
                }
            }
        });
        Self {
            base_url: format!("http://{address}"),
            hold,
            shutdown: Some(shutdown),
            server,
        }
    }

    fn url(&self, path: &str) -> String {
        format!("{}{path}", self.base_url)
    }

    async fn wait_until_held(&self) {
        timeout(FIXTURE_DEADLINE, self.hold.wait_for_arrival())
            .await
            .expect("held request never reached fixture");
    }

    fn release_held_navigation(&self) {
        self.hold.open();
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        // A cancellation or close test can leave an HTTP handler held. This is
        // cleanup, not readiness synchronization.
        self.hold.open();
        if let Some(shutdown) = self.shutdown.take() {
            let _ = shutdown.send(());
        }
        self.server.abort();
    }
}

async fn serve(mut stream: TcpStream, hold: Arc<Gate>) {
    let mut request = [0_u8; 4_096];
    let Ok(read) = stream.read(&mut request).await else {
        return;
    };
    let request_text = String::from_utf8_lossy(request.get(..read).unwrap_or_default());
    let path = request_text
        .split_whitespace()
        .nth(1)
        .unwrap_or("/")
        .split('?')
        .next()
        .unwrap_or("/");

    if matches!(path, "/hold" | "/hold-resource") {
        hold.mark_arrived();
        hold.wait_until_open().await;
    }

    let body = match path {
        "/same-document" => {
            "<!doctype html><main>before</main><script>history.pushState({}, '', '#first');history.pushState({}, '', '#second')</script>"
        }
        "/frame-parent" => {
            "<!doctype html><main>top-frame</main><iframe src='/frame-child'></iframe>"
        }
        "/frame-child" => {
            "<!doctype html><main>child-frame</main><script>history.pushState({}, '', '#child')</script>"
        }
        "/progress-burst" => {
            "<!doctype html><main>burst</main><script>for(let index=0;index<64;index+=1){history.pushState({index}, '', '#'+index)}</script>"
        }
        "/dcl-hold" => "<!doctype html><main>dcl-ready</main><img src='/hold-resource' alt='held'>",
        "/hold" => "<!doctype html><main>released</main>",
        _ => "<!doctype html><main>normal</main>",
    };
    let response = format!(
        "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: {}\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n{body}",
        body.len()
    );
    let _ = stream.write_all(response.as_bytes()).await;
    let _ = stream.shutdown().await;
}

async fn session() -> BrowserSession {
    // This intentionally preserves Chromium's sandbox; browser execution is
    // not run as part of this change without separately authorized validation.
    BrowserSession::launch_headless()
        .await
        .expect("launch local Chromium")
}

const fn options(capacity: usize, max_duration: Duration) -> ActiveNavigationOptions {
    ActiveNavigationOptions::new(
        NonZeroUsize::new(capacity).expect("positive progress capacity"),
        max_duration,
    )
}

async fn collect_progress(navigation: &mut ActiveNavigation) -> Vec<NavigationProgress> {
    let mut progress = Vec::new();
    while let Some(item) = timeout(NAVIGATION_DEADLINE, navigation.next_progress())
        .await
        .expect("progress stream did not settle")
        .expect("active navigation progress failed")
    {
        progress.push(item);
    }
    progress
}

fn assert_strictly_ordered(progress: &[NavigationProgress]) {
    assert!(!progress.is_empty(), "navigation produced no progress");
    assert!(
        progress
            .windows(2)
            .all(|pair| matches!(pair, [first, second] if first.sequence < second.sequence)),
        "progress receipt sequence must be strictly ordered: {progress:#?}"
    );
}

fn assert_loss_accounting_is_honest(report: &NavigationReport) {
    match (
        report.progress.admitted,
        report.progress.retained,
        report.progress.dropped,
    ) {
        (
            MeasuredCount::Known { value: admitted },
            MeasuredCount::Known { value: retained },
            MeasuredCount::Known { value: dropped },
        ) => assert_eq!(
            Some(admitted),
            retained.checked_add(dropped),
            "progress accounting must balance"
        ),
        (_, _, MeasuredCount::Unavailable { .. }) => {}
        values => panic!("partially known progress accounting is misleading: {values:#?}"),
    }
}

async fn finish(page: &Page, url: &str) -> (Vec<NavigationProgress>, NavigationReport) {
    let mut navigation = page
        .start_navigation(url, options(128, NAVIGATION_DEADLINE))
        .await
        .expect("start active navigation");
    let progress = collect_progress(&mut navigation).await;
    let report = navigation
        .wait()
        .await
        .expect("receive terminal navigation report");
    (progress, report)
}

#[tokio::test]
async fn top_frame_navigation_has_typed_ordered_progress_and_one_terminal_report() {
    let fixture = Fixture::start().await;
    let browser = session().await;
    let page = browser.new_blank_page().await.expect("blank page");
    let before = page.instrumentation_state();

    let (progress, report) = finish(&page, &fixture.url("/normal")).await;

    assert_strictly_ordered(&progress);
    assert!(
        progress
            .first()
            .is_some_and(|item| matches!(item.kind, NavigationProgressKind::CommandAccepted))
    );
    assert!(
        progress
            .iter()
            .any(|item| matches!(item.kind, NavigationProgressKind::DocumentCommitted))
    );
    assert!(
        progress
            .iter()
            .any(|item| matches!(item.kind, NavigationProgressKind::Load))
    );
    assert_eq!(report.termination, NavigationTermination::Completed);
    assert!(report.cleanup_complete);
    assert_loss_accounting_is_honest(&report);

    // `wait(self)` consumes the only producer handle, so this owned report is
    // the only terminal result for the navigation.
    let after = page.instrumentation_state();
    assert!(!before.network_enabled && !before.runtime_enabled);
    assert!(!after.network_enabled && !after.runtime_enabled);

    page.close().await.expect("close page");
    browser.close().await.expect("close browser");
}

#[tokio::test]
async fn dom_content_loaded_readiness_stops_slow_resources_and_keeps_page_usable() {
    let fixture = Fixture::start().await;
    let browser = session().await;
    let page = browser.new_blank_page().await.expect("blank page");

    timeout(
        FIXTURE_DEADLINE,
        page.navigate_until_dom_content_loaded(
            &fixture.url("/dcl-hold"),
            options(128, NAVIGATION_DEADLINE),
        ),
    )
    .await
    .expect("DOMContentLoaded readiness did not finish")
    .expect("DOMContentLoaded readiness failed");
    fixture.wait_until_held().await;
    assert!(
        page.content()
            .await
            .expect("read DOM after readiness")
            .contains("dcl-ready")
    );

    let (_, report) = finish(&page, &fixture.url("/normal")).await;
    assert_eq!(report.termination, NavigationTermination::Completed);
    fixture.release_held_navigation();
    page.close().await.expect("close page");
    browser.close().await.expect("close browser");
}

#[tokio::test]
async fn same_document_navigation_is_explicitly_typed() {
    let fixture = Fixture::start().await;
    let browser = session().await;
    let page = browser.new_blank_page().await.expect("blank page");
    let initial = fixture.url("/normal");
    page.navigate(&initial).await.expect("initial document");

    let same_document = format!("{initial}#fragment");
    let (progress, report) = finish(&page, &same_document).await;

    assert!(
        progress
            .iter()
            .any(|item| matches!(item.kind, NavigationProgressKind::SameDocumentNavigation))
    );
    assert_eq!(report.termination, NavigationTermination::Completed);
    assert!(report.same_document);
    assert_loss_accounting_is_honest(&report);

    page.close().await.expect("close page");
    browser.close().await.expect("close browser");
}

#[tokio::test]
async fn child_frame_navigation_does_not_enter_top_frame_progress() {
    let fixture = Fixture::start().await;
    let browser = session().await;
    let page = browser.new_blank_page().await.expect("blank page");

    let (progress, report) = finish(&page, &fixture.url("/frame-parent")).await;

    assert_eq!(report.termination, NavigationTermination::Completed);
    assert_eq!(
        progress
            .iter()
            .filter(|item| matches!(item.kind, NavigationProgressKind::DocumentCommitted))
            .count(),
        1,
        "child-frame commits leaked into top-frame progress: {progress:#?}"
    );
    assert_eq!(
        progress
            .iter()
            .filter(|item| matches!(item.kind, NavigationProgressKind::SameDocumentNavigation))
            .count(),
        0,
        "child-frame same-document events leaked into top-frame progress: {progress:#?}"
    );

    page.close().await.expect("close page");
    browser.close().await.expect("close browser");
}

#[tokio::test]
async fn saturated_progress_consumer_reports_loss_instead_of_stalling_or_hiding_it() {
    let fixture = Fixture::start().await;
    let browser = session().await;
    let page = browser.new_blank_page().await.expect("blank page");
    let navigation = page
        .start_navigation(
            &fixture.url("/progress-burst"),
            options(1, NAVIGATION_DEADLINE).with_provider_event_capacity(
                NonZeroUsize::new(128).expect("positive provider capacity"),
            ),
        )
        .await
        .expect("start bounded active navigation");

    // Do not consume progress. The bounded stream must finish and report loss
    // rather than blocking the coordinator or claiming a complete feed.
    let report = timeout(NAVIGATION_DEADLINE, navigation.wait())
        .await
        .expect("lagged progress consumer stalled navigation")
        .expect("receive terminal report");
    assert_eq!(report.termination, NavigationTermination::Completed);
    assert!(matches!(report.progress.dropped, MeasuredCount::Known { value } if value > 0));
    assert_loss_accounting_is_honest(&report);

    page.close().await.expect("close page");
    browser.close().await.expect("close browser");
}

#[tokio::test]
async fn provider_listener_overflow_is_incomplete_and_poisons_the_page() {
    let fixture = Fixture::start().await;
    let browser = session().await;
    let page = browser.new_blank_page().await.expect("blank page");
    let navigation = page
        .start_navigation(
            &fixture.url("/progress-burst"),
            options(128, NAVIGATION_DEADLINE).with_provider_event_capacity(NonZeroUsize::MIN),
        )
        .await
        .expect("start provider-overflow navigation");

    let report = navigation.wait().await.expect("provider-overflow report");
    assert_eq!(
        report.termination,
        NavigationTermination::Failed {
            reason: void_crawl_core::NavigationFailureReason::EventStreamClosed,
        }
    );
    assert!(matches!(
        report.provider_events_dropped,
        MeasuredCount::Known { value } if value > 0
    ));
    assert!(matches!(
        page.start_navigation(&fixture.url("/normal"), options(8, NAVIGATION_DEADLINE))
            .await,
        Err(void_crawl_core::VoidCrawlError::NavigationStateUncertain)
    ));

    page.close().await.expect("close page");
    browser.close().await.expect("close browser");
}

#[tokio::test]
async fn cancellation_deadline_page_close_and_browser_close_each_produce_a_terminal_report() {
    let fixture = Fixture::start().await;

    let browser = session().await;
    let page = browser.new_blank_page().await.expect("cancellation page");
    let navigation = page
        .start_navigation(&fixture.url("/hold"), options(8, NAVIGATION_DEADLINE))
        .await
        .expect("start cancellable navigation");
    fixture.wait_until_held().await;
    let report = navigation.cancel().await.expect("cancel navigation");
    assert_eq!(report.termination, NavigationTermination::Cancelled);
    assert!(!report.cleanup_complete);
    page.close().await.expect("close cancellation page");
    browser.close().await.expect("close cancellation browser");

    let browser = session().await;
    let page = browser.new_blank_page().await.expect("deadline page");
    let navigation = page
        .start_navigation(&fixture.url("/hold"), options(8, Duration::from_millis(50)))
        .await
        .expect("start deadline navigation");
    let report = timeout(FIXTURE_DEADLINE, navigation.wait())
        .await
        .expect("navigation deadline did not resolve")
        .expect("receive deadline report");
    assert_eq!(report.termination, NavigationTermination::DeadlineReached);
    page.close().await.expect("close deadline page");
    browser.close().await.expect("close deadline browser");

    let fixture = Fixture::start().await;
    let browser = session().await;
    let page = browser.new_blank_page().await.expect("page-close page");
    let navigation = page
        .start_navigation(&fixture.url("/hold"), options(8, NAVIGATION_DEADLINE))
        .await
        .expect("start page-close navigation");
    fixture.wait_until_held().await;
    page.close().await.expect("close active page");
    let report = navigation.wait().await.expect("page-close terminal report");
    assert_eq!(report.termination, NavigationTermination::PageClosed);
    browser.close().await.expect("close page-close browser");

    let fixture = Fixture::start().await;
    let browser = session().await;
    let page = browser.new_blank_page().await.expect("browser-close page");
    let navigation = page
        .start_navigation(&fixture.url("/hold"), options(8, NAVIGATION_DEADLINE))
        .await
        .expect("start browser-close navigation");
    fixture.wait_until_held().await;
    browser.close().await.expect("close active browser");
    let report = navigation
        .wait()
        .await
        .expect("browser-close terminal report");
    assert_eq!(report.termination, NavigationTermination::BrowserClosed);
}

async fn assert_dynamic_tab_count(browser: &BrowserSession, fixture: &Fixture, tab_count: usize) {
    let mut pages = Vec::with_capacity(tab_count);
    for _ in 0..tab_count {
        pages.push(browser.new_blank_page().await.expect("dynamic tab"));
    }
    let mut navigations = Vec::with_capacity(tab_count);
    for (index, page) in pages.iter().enumerate() {
        navigations.push(
            page.start_navigation(
                &fixture.url(&format!("/tab/{index}")),
                options(128, NAVIGATION_DEADLINE),
            )
            .await
            .expect("start concurrent dynamic navigation"),
        );
    }
    for navigation in navigations {
        let report = navigation.wait().await.expect("dynamic navigation report");
        assert_eq!(report.termination, NavigationTermination::Completed);
    }
    for page in pages {
        page.close().await.expect("close dynamic tab");
    }
}

#[tokio::test]
async fn held_tab_does_not_block_another_and_tab_counts_are_not_api_limited() {
    let fixture = Fixture::start().await;
    let browser = session().await;
    let held_page = browser.new_blank_page().await.expect("held page");
    let held = held_page
        .start_navigation(&fixture.url("/hold"), options(16, NAVIGATION_DEADLINE))
        .await
        .expect("start held navigation");
    fixture.wait_until_held().await;

    let fast_page = browser.new_blank_page().await.expect("independent page");
    let (_, fast_report) = finish(&fast_page, &fixture.url("/normal")).await;
    assert_eq!(fast_report.termination, NavigationTermination::Completed);

    fixture.release_held_navigation();
    let held_report = held.wait().await.expect("held terminal report");
    assert_eq!(held_report.termination, NavigationTermination::Completed);

    // The count is runtime input, not a tab API maximum.
    for tab_count in [1_usize, 4, 16] {
        assert_dynamic_tab_count(&browser, &fixture, tab_count).await;
    }

    fast_page.close().await.expect("close independent page");
    held_page.close().await.expect("close held page");
    browser.close().await.expect("close browser");
}

#[tokio::test]
#[ignore = "resource-gated 64-tab soak; run explicitly after checking host pressure"]
async fn configured_sixty_four_tab_soak() {
    let fixture = Fixture::start().await;
    let browser = session().await;
    assert_dynamic_tab_count(&browser, &fixture, 64).await;
    browser.close().await.expect("close browser");
}
