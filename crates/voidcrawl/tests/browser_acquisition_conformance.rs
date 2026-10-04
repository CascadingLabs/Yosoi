//! Versioned, loopback-only Browser Acquisition conformance corpus.
#![allow(clippy::expect_used, clippy::panic, clippy::unwrap_used)]

use std::{
    collections::HashSet,
    fs,
    io::{ErrorKind, Read, Write},
    net::TcpListener,
    path::{Path, PathBuf},
    sync::mpsc,
    thread,
    time::Duration,
};

use serde::Deserialize;
use tokio::time::{sleep, timeout};
use void_crawl_core::{
    AccessibilitySnapshotOptions, BrowserSession, BrowserTarget, BrowserTargetKind,
    CapabilityDisabledReason, CapabilityState, CdpMode, InstrumentationMode, MeasuredCount,
    NavigationCaptureOptions, ObservationEventKind, ObservationOptions, ObservationTermination,
    ResponseBodyState, RuntimeDiagnosticKind, ScreenshotOptions, SnapshotState,
    SourceBodyUnavailableReason, VoidCrawlError,
};

#[path = "support/oopif_fixture.rs"]
mod oopif_fixture;

const STATIC: &str = include_str!("conformance/static.html");
const DELAYED_DOM: &str = include_str!("conformance/delayed-dom.html");
const RUNTIME_ERROR: &str = include_str!("conformance/runtime-error.html");
const FRAME_PARENT: &str = include_str!("conformance/frame-parent.html");
const FRAME_CHILD: &str = include_str!("conformance/frame-child.html");
const VISUAL_LAYOUT: &str = include_str!("conformance/visual-layout.html");
const SERVICE_WORKER: &str = include_str!("conformance/service-worker.html");
const SERVICE_WORKER_JS: &str = include_str!("conformance/conformance-sw.js");

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Manifest {
    schema: String,
    version: u64,
    provenance: Provenance,
    scenarios: Vec<Scenario>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Provenance {
    network: String,
    clock: String,
    secrets: String,
    public_sites_required: bool,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Scenario {
    id: String,
    fixture: String,
    expected: Vec<String>,
    coverage: String,
}

const EXPECTED_FACT_VOCABULARY: &[&str] = &[
    "body_unavailable",
    "cache_state_explicit",
    "cleanup_complete",
    "complete",
    "console",
    "coordinate_space",
    "deadline",
    "dimensions",
    "distinct_target_session",
    "document_cleared",
    "document_epoch",
    "dropped_explicit",
    "event_limit",
    "exact_retained_bytes",
    "exception",
    "failed",
    "final_response",
    "finished",
    "frame_payload_or_unavailable",
    "frame_geometry_routed",
    "frame_scope",
    "in_flight_known",
    "minimal_oopif_disabled_typed",
    "interrupted",
    "isolated_browser_context",
    "no_partial_bytes_claim",
    "permit_restored",
    "pre_navigation",
    "process_swap_routed",
    "provider_disconnected",
    "renderer_failure",
    "redirect_hops",
    "rendered_dom_changed",
    "same_document_epoch",
    "service_worker_state_explicit_or_unavailable",
    "shared_browser_profile",
    "state_removed",
    "state_retained",
    "tab_disposed",
    "trusted_input_routed",
    "truncated",
    "child_session_detached",
];

struct FixtureServer {
    url: String,
    stop: mpsc::Sender<()>,
    thread: Option<thread::JoinHandle<()>>,
}

impl FixtureServer {
    fn start() -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind conformance server");
        listener
            .set_nonblocking(true)
            .expect("nonblocking conformance server");
        let address = listener.local_addr().expect("fixture address");
        let (stop, stopped) = mpsc::channel();
        let thread = thread::spawn(move || {
            loop {
                if stopped.try_recv().is_ok() {
                    break;
                }
                match listener.accept() {
                    Ok((mut stream, _)) => {
                        let mut request = [0_u8; 4096];
                        let read = stream.read(&mut request).unwrap_or(0);
                        let request =
                            String::from_utf8_lossy(request.get(..read).unwrap_or_default());
                        let path = request.split_whitespace().nth(1).unwrap_or("/");
                        if path == "/partial-body" {
                            let _ = stream.write_all(
                            b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 1000\r\nConnection: close\r\n\r\nshort",
                        );
                            continue;
                        }
                        if path == "/endless" {
                            let _ = stream.write_all(
                            b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 1000000\r\nConnection: close\r\n\r\nx",
                        );
                            thread::sleep(Duration::from_millis(500));
                            continue;
                        }
                        let (status, content_type, body) = match path {
                            "/static.html" => ("200 OK", "text/html", STATIC),
                            "/delayed-dom.html" => ("200 OK", "text/html", DELAYED_DOM),
                            "/runtime-error.html" => ("200 OK", "text/html", RUNTIME_ERROR),
                            "/frame-parent.html" => ("200 OK", "text/html", FRAME_PARENT),
                            "/frame-child.html" => ("200 OK", "text/html", FRAME_CHILD),
                            "/visual-layout.html" => ("200 OK", "text/html", VISUAL_LAYOUT),
                            "/service-worker.html" => ("200 OK", "text/html", SERVICE_WORKER),
                            "/conformance-sw.js" => {
                                ("200 OK", "application/javascript", SERVICE_WORKER_JS)
                            }
                            _ => ("404 Not Found", "text/plain", "missing fixture"),
                        };
                        let response = format!(
                            "HTTP/1.1 {status}\r\nContent-Type: {content_type}\r\nContent-Length: {}\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n{body}",
                            body.len()
                        );
                        let _ = stream.write_all(response.as_bytes());
                    }
                    Err(error) if error.kind() == ErrorKind::WouldBlock => {
                        thread::sleep(Duration::from_millis(2));
                    }
                    Err(error) => panic!("conformance fixture accept: {error}"),
                }
            }
        });
        Self {
            url: format!("http://{address}"),
            stop,
            thread: Some(thread),
        }
    }

    fn url(&self, path: &str) -> String {
        format!("{}{path}", self.url)
    }
}

impl Drop for FixtureServer {
    fn drop(&mut self) {
        let _ = self.stop.send(());
        if let Some(thread) = self.thread.take() {
            thread.join().expect("join conformance server");
        }
    }
}

fn corpus_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/conformance")
}

fn coverage_file(module: &str) -> PathBuf {
    match module {
        "browser_acquisition_conformance" => {
            Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/browser_acquisition_conformance.rs")
        }
        "observation" => {
            Path::new(env!("CARGO_MANIFEST_DIR")).join("src/observation_progress_tests.rs")
        }
        other => Path::new(env!("CARGO_MANIFEST_DIR")).join(format!("tests/{other}.rs")),
    }
}

#[test]
fn manifest_is_versioned_local_and_references_real_coverage() {
    let manifest: Manifest =
        serde_json::from_str(include_str!("conformance/browser-acquisition-v1.json"))
            .expect("valid conformance manifest");
    assert_eq!(manifest.schema, "voidcrawl.browser-acquisition-conformance");
    assert_eq!(manifest.version, 1);
    assert_eq!(manifest.provenance.network, "loopback-only");
    assert_eq!(manifest.provenance.clock, "relative-or-category-only");
    assert_eq!(manifest.provenance.secrets, "synthetic");
    assert!(!manifest.provenance.public_sites_required);
    assert!(manifest.scenarios.len() >= 18);

    let mut ids = HashSet::new();
    for scenario in manifest.scenarios {
        assert!(
            ids.insert(scenario.id.clone()),
            "duplicate scenario {}",
            scenario.id
        );
        assert!(
            !scenario.expected.is_empty(),
            "{} has no expectations",
            scenario.id
        );
        let mut expected = HashSet::new();
        for fact in &scenario.expected {
            assert!(
                expected.insert(fact),
                "{} repeats expected fact {fact}",
                scenario.id
            );
            assert!(
                EXPECTED_FACT_VOCABULARY.contains(&fact.as_str()),
                "{} uses unknown expected fact {fact}",
                scenario.id,
            );
        }
        assert!(
            !scenario.coverage.is_empty(),
            "{} has no coverage",
            scenario.id
        );
        if !scenario.fixture.contains(':') {
            assert!(
                corpus_dir().join(&scenario.fixture).is_file(),
                "missing {}",
                scenario.fixture
            );
        }
        let (module, test) = scenario
            .coverage
            .split_once("::")
            .expect("coverage is module::test");
        let source = fs::read_to_string(coverage_file(module)).expect("read coverage source");
        assert!(
            source.contains(&format!("fn {test}(")),
            "coverage target {} is stale",
            scenario.coverage
        );
    }
}

fn assert_contract(scenario_id: &str, expected: &[&str]) {
    let manifest: Manifest =
        serde_json::from_str(include_str!("conformance/browser-acquisition-v1.json"))
            .expect("valid conformance manifest");
    let scenario = manifest
        .scenarios
        .iter()
        .find(|scenario| scenario.id == scenario_id)
        .unwrap_or_else(|| panic!("missing contract scenario {scenario_id}"));
    assert_eq!(
        scenario.expected, expected,
        "contract expectations drifted for {scenario_id}"
    );
}

async fn session() -> BrowserSession {
    BrowserSession::builder()
        .headless()
        .launch()
        .await
        .expect("launch Chromium")
}

#[tokio::test]
async fn static_delayed_runtime_frame_and_visual_fixtures_are_observable() {
    let fixtures = FixtureServer::start();
    let browser = session().await;
    let page = browser.new_blank_page().await.expect("blank page");

    page.navigate(&fixtures.url("/static.html"))
        .await
        .expect("static navigation");
    let static_dom = page
        .rendered_dom_snapshot(1024 * 1024)
        .await
        .expect("static DOM");
    assert_eq!(static_dom.state, SnapshotState::Complete);
    assert!(
        static_dom
            .bytes()
            .windows(b"Static fixture".len())
            .any(|w| w == b"Static fixture")
    );

    page.navigate(&fixtures.url("/delayed-dom.html"))
        .await
        .expect("delayed navigation");
    let before = page
        .rendered_dom_snapshot(1024 * 1024)
        .await
        .expect("initial DOM");
    sleep(Duration::from_millis(80)).await;
    let after = page
        .rendered_dom_snapshot(1024 * 1024)
        .await
        .expect("settled DOM");
    assert_eq!(before.scope.epoch, after.scope.epoch);
    assert!(
        after
            .bytes()
            .windows(b"settled".len())
            .any(|w| w == b"settled")
    );

    let scope = page
        .arm_observation(ObservationOptions {
            max_duration: Duration::from_secs(3),
            ..ObservationOptions::default()
        })
        .await
        .expect("arm runtime observation");
    page.navigate(&fixtures.url("/runtime-error.html"))
        .await
        .expect("runtime fixture");
    sleep(Duration::from_millis(25)).await;
    let report = scope.finish().await.expect("finish runtime observation");
    assert!(
        report
            .events
            .iter()
            .any(|event| event.kind == ObservationEventKind::ConsoleApiCalled)
    );
    assert!(
        report
            .diagnostics
            .iter()
            .any(|diagnostic| matches!(diagnostic.kind, RuntimeDiagnosticKind::Console { .. }))
    );
    assert!(
        report
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.kind == RuntimeDiagnosticKind::Exception)
    );

    page.navigate(&fixtures.url("/frame-parent.html"))
        .await
        .expect("frame fixture");
    let frame = page
        .accessibility_snapshot_in_frame(
            "frame-child.html",
            AccessibilitySnapshotOptions::default(),
        )
        .await
        .expect("frame AX");
    assert_eq!(frame.state, SnapshotState::Complete);

    page.navigate(&fixtures.url("/visual-layout.html"))
        .await
        .expect("visual fixture");
    let visual = page
        .visual_snapshot(ScreenshotOptions {
            selector: Some(BrowserTarget {
                kind: BrowserTargetKind::Css,
                value: "#moving".into(),
                regex: None,
                name: None,
                nth: None,
                x: None,
                y: None,
            }),
            ..ScreenshotOptions::default()
        })
        .await
        .expect("visual snapshot");
    assert_eq!(visual.image_width_pixels, 80);
    assert_eq!(visual.image_height_pixels, 40);
    assert!(visual.retained_bytes > 0);
    assert_contract("static_navigation", &["finished", "complete"]);
    assert_contract(
        "delayed_dom",
        &["same_document_epoch", "rendered_dom_changed"],
    );
    assert_contract(
        "synchronous_runtime_error",
        &["console", "exception", "pre_navigation"],
    );
    assert_contract("same_process_frame", &["frame_scope"]);
    assert_contract(
        "visual_layout_change",
        &["dimensions", "coordinate_space", "document_epoch"],
    );

    page.close().await.expect("close page");
    browser.close().await.expect("close browser");
}

#[tokio::test]
async fn active_network_can_finish_with_explicit_in_flight_accounting() {
    let fixtures = FixtureServer::start();
    let browser = session().await;
    let page = browser
        .new_page(&fixtures.url("/static.html"))
        .await
        .expect("static page");
    let scope = page
        .arm_observation(ObservationOptions {
            collect_console: false,
            collect_exceptions: false,
            max_duration: Duration::from_secs(2),
            ..ObservationOptions::default()
        })
        .await
        .expect("arm network observation");
    page.evaluate_js("void fetch('/endless')")
        .await
        .expect("start endless request");
    sleep(Duration::from_millis(30)).await;
    let report = scope
        .finish()
        .await
        .expect("finish active network observation");
    assert_eq!(report.termination, ObservationTermination::Finished);
    assert!(matches!(
        report.accounting.in_flight_requests,
        MeasuredCount::Known { value } if value >= 1
    ));
    assert!(report.cleanup_complete);
    assert_contract(
        "endless_network",
        &["finished", "in_flight_known", "cleanup_complete"],
    );
    page.close().await.expect("close page");
    browser.close().await.expect("close browser");
}

#[tokio::test]
async fn mid_body_disconnect_is_an_explicit_failed_source_not_partial_bytes() {
    let fixtures = FixtureServer::start();
    let browser = session().await;
    let page = browser.new_blank_page().await.expect("blank page");
    let capture = page
        .arm_navigation_capture(NavigationCaptureOptions {
            max_duration: Duration::from_secs(3),
            ..NavigationCaptureOptions::default()
        })
        .await
        .expect("arm navigation capture");
    let _ = page.navigate(&fixtures.url("/partial-body")).await;
    sleep(Duration::from_millis(25)).await;
    let report = capture.finish().await.expect("partial response report");
    let source = report.main_document.expect("main document fact");
    assert_eq!(source.body_state, ResponseBodyState::Unavailable);
    assert!(matches!(
        source.body_unavailable,
        Some(
            SourceBodyUnavailableReason::RequestFailed
                | SourceBodyUnavailableReason::CdpBodyUnavailable
        )
    ));
    assert_eq!(source.body().len(), 0);
    assert!(report.cleanup_complete);
    assert_contract(
        "partial_response_body",
        &["failed", "body_unavailable", "no_partial_bytes_claim"],
    );
    page.close().await.expect("close page");
    browser.close().await.expect("close browser");
}

#[tokio::test]
async fn loopback_cross_origin_frame_is_payload_or_explicitly_unavailable() {
    let parent = FixtureServer::start();
    let child = FixtureServer::start();
    let browser = BrowserSession::builder()
        .headless()
        .launch()
        .await
        .expect("launch site-isolated Chromium");
    let page = browser
        .new_page(&parent.url("/static.html"))
        .await
        .expect("parent page");
    let child_url = child.url("/frame-child.html");
    let encoded_child = serde_json::to_string(&child_url).expect("encode child URL");
    page.evaluate_js(&format!(
        "new Promise((resolve, reject) => {{ const f=document.createElement('iframe'); f.addEventListener('load', () => resolve(f.src), {{ once: true }}); f.addEventListener('error', () => reject(new Error('child frame failed')), {{ once: true }}); f.src={encoded_child}; document.body.append(f); }})"
    ))
    .await
    .expect("append and await cross-origin frame load");
    assert!(
        page.frame_urls()
            .await
            .expect("frame URLs")
            .contains(&child_url)
    );

    let snapshot = page
        .accessibility_snapshot_in_frame(
            "/frame-child.html",
            AccessibilitySnapshotOptions::default(),
        )
        .await
        .expect("truthful cross-origin frame result");
    assert!(matches!(
        snapshot.state,
        SnapshotState::Complete
            | SnapshotState::Unavailable {
                reason: void_crawl_core::SnapshotUnavailableReason::FrameUnavailable,
            }
    ));
    assert_contract("oopif", &["frame_payload_or_unavailable"]);
    page.close().await.expect("close page");
    browser.close().await.expect("close browser");
}

#[tokio::test]
async fn cross_site_oopif_session_routes_child_operations_and_swaps() {
    let fixture = oopif_fixture::OopifFixture::start().await;
    let browser = fixture.launch_browser(CdpMode::Normal).await;
    let page = browser.new_blank_page().await.expect("blank OOPIF page");

    // The fixture forces b.test and c.test into cross-site iframe processes.
    // Successful typed operations before and after both process swaps prove
    // that the controller replaced detached child sessions without exposing
    // raw target or session handles through VoidCrawl's public API.
    fixture.navigate_parent(&page).await;

    let evaluated = page
        .evaluate_js_in_frame(
            "/child-first",
            "document.querySelector('button').getAttribute('aria-label')",
        )
        .await
        .expect("route JavaScript into the attached OOPIF session");
    assert_eq!(evaluated.as_str(), Some("OOPIF-CHILD-B1"));
    let nested = page
        .evaluate_js_in_frame("/nested", "document.body.dataset.marker")
        .await
        .expect("route JavaScript to a same-process nested frame inside the OOPIF session");
    assert_eq!(nested.as_str(), Some("OOPIF-NESTED"));
    let outline = page
        .ax_outline_in_frame("/child-first", None)
        .await
        .expect("route AX command into the attached OOPIF session");
    assert!(outline.contains("OOPIF-CHILD-B1"));
    let snapshot = page
        .accessibility_snapshot_in_frame("/child-first", AccessibilitySnapshotOptions::default())
        .await
        .expect("route AX capture into the attached OOPIF session");
    assert_eq!(snapshot.state, SnapshotState::Complete);
    assert!(String::from_utf8_lossy(snapshot.bytes()).contains("OOPIF-CHILD-B1"));

    let rect = page
        .ax_box_in_frame("/child-first", "button", "OOPIF-CHILD-B1", 0)
        .await
        .expect("resolve OOPIF button geometry through its owning session");
    assert_eq!(rect.len(), 4);
    assert!(rect[2] > 0.0 && rect[3] > 0.0);
    page.click_ax_in_frame("/child-first", "button", "OOPIF-CHILD-B1", 0, false)
        .await
        .expect("dispatch a trusted click to the OOPIF button");
    fixture
        .wait_for_child_message(&page, "OOPIF-CHILD-B1-CLICKED")
        .await;

    let first_navigation = timeout(
        Duration::from_secs(10),
        page.navigate_frame(
            "/child-first",
            &fixture.child_url("a.test", "/child-middle"),
        ),
    )
    .await
    .expect("OOPIF to in-process navigation timed out");
    let first_destination = match first_navigation {
        Ok(destination) => destination,
        Err(error) => match error {
            void_crawl_core::VoidCrawlError::NavigationFailed(message) => {
                panic!("navigate the OOPIF back into the parent renderer: {message}")
            }
            other => panic!("navigate the OOPIF back into the parent renderer: {other:?}"),
        },
    };
    assert_eq!(
        first_destination,
        fixture.child_url("a.test", "/child-middle")
    );
    fixture
        .wait_for_child_message(&page, "OOPIF-CHILD-A2")
        .await;

    let second_destination = timeout(
        Duration::from_secs(10),
        page.navigate_frame(
            "/child-middle",
            &fixture.child_url("c.test", "/child-final"),
        ),
    )
    .await
    .expect("in-process to OOPIF navigation timed out")
    .expect("navigate the in-process frame into a replacement OOPIF session");
    assert_eq!(
        second_destination,
        fixture.child_url("c.test", "/child-final")
    );
    fixture
        .wait_for_child_message(&page, "OOPIF-CHILD-C3")
        .await;
    let evaluated = page
        .evaluate_js_in_frame(
            "/child-final",
            "document.querySelector('button').getAttribute('aria-label')",
        )
        .await
        .expect("route JavaScript after the child process swap");
    assert_eq!(evaluated.as_str(), Some("OOPIF-CHILD-C3"));

    let fragment_url = format!("{}#ready", fixture.child_url("c.test", "/child-final"));
    let fragment_destination = page
        .navigate_frame("/child-final", &fragment_url)
        .await
        .expect("confirm a same-document OOPIF navigation");
    assert_eq!(fragment_destination, fragment_url);

    page.close()
        .await
        .expect("close parent page and child target");
    browser.close().await.expect("close OOPIF browser");
    assert_contract(
        "oopif_session_routing",
        &[
            "distinct_target_session",
            "child_session_detached",
            "cleanup_complete",
            "frame_geometry_routed",
            "process_swap_routed",
            "trusted_input_routed",
        ],
    );
}

#[tokio::test]
async fn minimal_mode_reports_oopif_routing_as_typed_disabled_capability() {
    let fixture = oopif_fixture::OopifFixture::start().await;
    let browser = fixture.launch_browser(CdpMode::Minimal).await;
    let page = browser.new_blank_page().await.expect("blank Minimal page");
    fixture.navigate_parent(&page).await;

    let environment = page
        .environment_snapshot()
        .await
        .expect("observe Minimal instrumentation capabilities");
    assert_eq!(
        environment.instrumentation.configured_mode,
        InstrumentationMode::Minimal
    );
    assert_eq!(
        environment.capabilities.out_of_process_frame_routing,
        CapabilityState::Disabled {
            reason: CapabilityDisabledReason::MinimalCdpMode,
        },
    );

    page.close().await.expect("close Minimal page");
    browser.close().await.expect("close Minimal browser");
    assert_contract("oopif_minimal_mode", &["minimal_oopif_disabled_typed"]);
}

#[tokio::test]
async fn browser_disconnect_reaches_the_provider_disconnect_terminal() {
    let browser = session().await;
    let page = browser.new_blank_page().await.expect("blank page");
    let scope = page
        .arm_observation(ObservationOptions {
            collect_network: false,
            max_duration: Duration::from_secs(3),
            ..ObservationOptions::default()
        })
        .await
        .expect("arm before browser close");

    browser.close().await.expect("close browser");
    let report = scope.finish().await.expect("browser disconnect report");
    assert_eq!(
        report.termination,
        ObservationTermination::ProviderDisconnected
    );
    assert!(report.cleanup_complete);
    assert_contract(
        "browser_disconnect",
        &["provider_disconnected", "cleanup_complete"],
    );
}

const fn is_pdf_token_delimiter(byte: u8) -> bool {
    byte.is_ascii_whitespace()
        || matches!(byte, b'(' | b')' | b'<' | b'>' | b'[' | b']' | b'/' | b'%')
}

fn contains_pdf_name(bytes: &[u8], name: &[u8]) -> bool {
    !name.is_empty()
        && bytes
            .windows(name.len())
            .enumerate()
            .any(|(index, window)| {
                window == name
                    && bytes
                        .get(index.saturating_add(name.len()))
                        .is_none_or(|byte| is_pdf_token_delimiter(*byte))
            })
}

fn has_terminal_pdf_eof(bytes: &[u8]) -> bool {
    let Some(last_content_byte) = bytes.iter().rposition(|byte| !byte.is_ascii_whitespace()) else {
        return false;
    };
    bytes
        .get(..=last_content_byte)
        .is_some_and(|content| content.ends_with(b"%%EOF"))
}

#[tokio::test]
async fn pdf_bytes_returns_bounded_pdf_and_typed_error_for_closed_page() {
    const MAX_PDF_BYTES: usize = 256 * 1024;

    let fixtures = FixtureServer::start();
    let browser = BrowserSession::builder()
        .headless()
        .launch()
        .await
        .expect("launch sandboxed regular Stable browser");
    let isolated = match browser.new_isolated_context().await {
        Ok(context) => context,
        Err(error) => {
            let close_result = browser.close().await;
            assert!(
                close_result.is_ok(),
                "close browser after context setup failure"
            );
            panic!("create isolated browser context: {error}");
        }
    };

    let (navigation_result, pdf_result, successful_page_close) = {
        let page = isolated.page();
        let navigation_result = page.navigate(&fixtures.url("/static.html")).await;
        let pdf_result = page.pdf_bytes().await;
        let page_close = page.close().await;
        (navigation_result, pdf_result, page_close)
    };

    let closed_page_result = match isolated.new_blank_page().await {
        Ok(page) => {
            let close_result = page.close().await;
            let pdf_result = page.pdf_bytes().await;
            Ok((close_result, pdf_result))
        }
        Err(error) => Err(error),
    };

    let context_cleanup = isolated.dispose().await;
    let browser_close = browser.close().await;

    assert!(
        navigation_result.is_ok(),
        "navigate to loopback fixture: {navigation_result:?}"
    );
    assert!(
        successful_page_close.is_ok(),
        "close PDF page: {successful_page_close:?}"
    );
    assert!(
        context_cleanup.cleanup_complete,
        "dispose isolated context: {context_cleanup:?}"
    );
    assert!(
        browser_close.is_ok(),
        "close browser session: {browser_close:?}"
    );

    let pdf = pdf_result.expect("generate PDF from loopback fixture");
    assert!(
        pdf.len() <= MAX_PDF_BYTES,
        "PDF was {} bytes, over the {MAX_PDF_BYTES}-byte ceiling",
        pdf.len()
    );
    assert!(pdf.starts_with(b"%PDF-"), "PDF header is missing");
    assert!(
        has_terminal_pdf_eof(&pdf),
        "terminal %%EOF marker is missing"
    );
    assert!(
        contains_pdf_name(&pdf, b"/Type /Page"),
        "PDF page-object marker is missing"
    );

    let (closed_page_close, closed_page_pdf) =
        closed_page_result.expect("create page for closed-page failure case");
    assert!(
        closed_page_close.is_ok(),
        "close failure-case page: {closed_page_close:?}"
    );
    let pdf_error = closed_page_pdf.expect_err("PDF generation on a closed page must fail");
    assert!(
        matches!(&pdf_error, VoidCrawlError::PdfError(_)),
        "closed-page PDF failure must be typed as PdfError, got {pdf_error:?}"
    );
}

#[test]
fn pdf_page_name_check_rejects_the_pages_tree_prefix() {
    assert!(contains_pdf_name(b"<< /Type /Page\n>>", b"/Type /Page"));
    assert!(!contains_pdf_name(b"<< /Type /Pages >>", b"/Type /Page"));
}
