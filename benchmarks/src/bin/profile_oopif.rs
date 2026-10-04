//! Identity-bound CAS-383 same-process iframe versus OOPIF latency driver.

use anyhow::{Context, Result, bail};
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::{
    env, fs,
    net::Ipv4Addr,
    process::Command,
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    sync::oneshot,
    task::JoinHandle,
    time::timeout,
};
use void_crawl_core::{AccessibilitySnapshotOptions, BrowserSession, CdpMode, Page, SnapshotState};

const REQUEST_LIMIT: usize = 8 * 1024;

#[derive(Serialize)]
struct IdentityRecord {
    record: &'static str,
    yosoi_change: String,
    yosoi_commit: String,
    source_sha256: String,
    chrome_path: String,
    chrome_version: String,
    chrome_sha256: String,
    chromiumoxide_upstream: &'static str,
    chromiumoxide_source_sha256: String,
    cdp_revision: &'static str,
    cdp_mode: &'static str,
    sandbox: bool,
    site_isolation_default: bool,
    iterations: usize,
    warmup: usize,
}

#[derive(Serialize)]
struct AttemptRecord {
    record: &'static str,
    case: &'static str,
    operation: &'static str,
    iteration: usize,
    elapsed_micros: u128,
}

#[derive(Serialize)]
struct SummaryRecord {
    record: &'static str,
    case: &'static str,
    operation: &'static str,
    attempts: usize,
    p50_micros: u128,
    p95_micros: u128,
    max_micros: u128,
}

struct Fixture {
    port: u16,
    stop: Option<oneshot::Sender<()>>,
    task: JoinHandle<()>,
}

impl Fixture {
    async fn start() -> Result<Self> {
        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0))
            .await
            .context("bind CAS-383 loopback fixture")?;
        let port = listener.local_addr().context("fixture address")?.port();
        let parent = Arc::<str>::from(parent_html(port));
        let (stop, mut stopped) = oneshot::channel();
        let task = tokio::spawn(async move {
            loop {
                tokio::select! {
                    _ = &mut stopped => break,
                    accepted = listener.accept() => {
                        let Ok((stream, peer)) = accepted else { break };
                        if !peer.ip().is_loopback() { continue; }
                        let parent = Arc::clone(&parent);
                        tokio::spawn(async move { serve(stream, port, parent).await; });
                    }
                }
            }
        });
        Ok(Self {
            port,
            stop: Some(stop),
            task,
        })
    }

    fn parent_url(&self) -> String {
        format!("http://a.test:{}/parent", self.port)
    }

    const fn resolver_rule() -> &'static str {
        "host-resolver-rules=MAP a.test 127.0.0.1,MAP b.test 127.0.0.1"
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        if let Some(stop) = self.stop.take() {
            let _ = stop.send(());
        }
        self.task.abort();
    }
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<()> {
    let iterations = parse_usize("CAS383_ITERATIONS", 100)?;
    let warmup = parse_usize("CAS383_WARMUP", 10)?;
    let yosoi_change = required_env("CAS383_YOSOI_CHANGE")?;
    let yosoi_commit = required_env("CAS383_YOSOI_COMMIT")?;
    let source_sha256 = required_env("CAS383_SOURCE_SHA256")?;
    let chromiumoxide_source_sha256 = required_env("CAS383_CHROMIUMOXIDE_SHA256")?;
    let chrome = env::var("CHROME").context("CHROME must name a regular Stable executable")?;
    if chrome.to_ascii_lowercase().contains("chrome-for-testing") {
        bail!("Chrome for Testing is prohibited");
    }
    let chrome_bytes = fs::read(&chrome).with_context(|| format!("read {chrome}"))?;
    let chrome_sha256 = format!("{:x}", Sha256::digest(chrome_bytes));
    let version = Command::new(&chrome)
        .arg("--version")
        .output()
        .context("read browser version")?;
    if !version.status.success() {
        bail!("browser version command failed");
    }
    let chrome_version = String::from_utf8(version.stdout)
        .context("browser version was not UTF-8")?
        .trim()
        .to_owned();
    println!(
        "{}",
        serde_json::to_string(&IdentityRecord {
            record: "identity",
            yosoi_change,
            yosoi_commit,
            source_sha256,
            chrome_path: chrome.clone(),
            chrome_version,
            chrome_sha256,
            chromiumoxide_upstream: "a7e2bb835b9643410f9e3dc044f0d947e96cbfa4",
            chromiumoxide_source_sha256,
            cdp_revision: "r1681091",
            cdp_mode: "normal",
            sandbox: true,
            site_isolation_default: true,
            iterations,
            warmup,
        })?
    );

    let fixture = Fixture::start().await?;
    let browser = BrowserSession::builder()
        .headless()
        .cdp_mode(CdpMode::Normal)
        .arg(Fixture::resolver_rule())
        .launch()
        .await
        .context("launch browser")?;
    let page = browser
        .new_page(&fixture.parent_url())
        .await
        .context("open benchmark parent")?;
    page.evaluate_js("window.__loadFrames()")
        .await
        .context("start benchmark frames")?;
    timeout(
        Duration::from_secs(10),
        page.evaluate_js("window.__framesReady"),
    )
    .await
    .context("frame readiness timed out")??;

    let nested = page
        .evaluate_js_in_frame("/nested", "document.body.dataset.marker")
        .await
        .context("evaluate nested frame inside OOPIF session")?;
    if nested.as_str() != Some("OOPIF-NESTED") {
        bail!("nested OOPIF evaluation was misrouted");
    }
    page.click_ax_in_frame("/cross", "button", "OOPIF-FRAME", 0, false)
        .await
        .context("dispatch trusted OOPIF click")?;
    let clicked = page
        .evaluate_js_in_frame("/cross", "document.body.dataset.clicked")
        .await
        .context("verify trusted OOPIF click")?;
    if clicked.as_str() != Some("true") {
        bail!("trusted OOPIF click did not reach the child renderer");
    }

    for _ in 0..warmup {
        run_operations(&page, "/same", "SAME-FRAME")
            .await
            .context("warm same-origin frame")?;
        run_operations(&page, "/cross", "OOPIF-FRAME")
            .await
            .context("warm OOPIF frame")?;
    }

    let mut same_eval = Vec::with_capacity(iterations);
    let mut same_ax = Vec::with_capacity(iterations);
    let mut same_geometry = Vec::with_capacity(iterations);
    let mut oopif_eval = Vec::with_capacity(iterations);
    let mut oopif_ax = Vec::with_capacity(iterations);
    let mut oopif_geometry = Vec::with_capacity(iterations);
    for iteration in 0..iterations {
        measure_case(
            &page,
            "same_origin",
            "/same",
            "SAME-FRAME",
            iteration,
            &mut same_eval,
            &mut same_ax,
            &mut same_geometry,
        )
        .await?;
        measure_case(
            &page,
            "oopif",
            "/cross",
            "OOPIF-FRAME",
            iteration,
            &mut oopif_eval,
            &mut oopif_ax,
            &mut oopif_geometry,
        )
        .await?;
    }

    for (case, operation, values) in [
        ("same_origin", "evaluate", same_eval),
        ("same_origin", "accessibility", same_ax),
        ("same_origin", "geometry", same_geometry),
        ("oopif", "evaluate", oopif_eval),
        ("oopif", "accessibility", oopif_ax),
        ("oopif", "geometry", oopif_geometry),
    ] {
        print_summary(case, operation, values)?;
    }
    verify_process_swaps(&page, fixture.port).await?;
    page.close().await.context("close benchmark page")?;
    browser.close().await.context("close benchmark browser")?;
    Ok(())
}

async fn verify_process_swaps(page: &Page, port: u16) -> Result<()> {
    let same_site = format!("http://a.test:{port}/swap-same");
    let observed = page
        .navigate_frame("/cross", &same_site)
        .await
        .context("navigate OOPIF back to the parent renderer")?;
    if observed != same_site {
        bail!("same-site frame navigation reported the wrong destination");
    }
    wait_for_marker(page, "SAME-SWAP").await?;
    let marker = page
        .evaluate_js_in_frame("/swap-same", "document.body.dataset.marker")
        .await
        .context("evaluate frame after OOPIF to same-site swap")?;
    if marker.as_str() != Some("SAME-SWAP") {
        bail!("same-site process-swap evaluation was misrouted");
    }

    let cross_site = format!("http://b.test:{port}/cross-final");
    let observed = page
        .navigate_frame("/swap-same", &cross_site)
        .await
        .context("navigate same-site frame to replacement OOPIF")?;
    if observed != cross_site {
        bail!("replacement OOPIF navigation reported the wrong destination");
    }
    wait_for_marker(page, "OOPIF-FINAL").await?;
    let marker = page
        .evaluate_js_in_frame("/cross-final", "document.body.dataset.marker")
        .await
        .context("evaluate replacement OOPIF")?;
    if marker.as_str() != Some("OOPIF-FINAL") {
        bail!("replacement OOPIF evaluation was misrouted");
    }

    let fragment = format!("{cross_site}#ready");
    let observed = page
        .navigate_frame("/cross-final", &fragment)
        .await
        .context("navigate OOPIF within its document")?;
    if observed != fragment {
        bail!("same-document OOPIF navigation reported the wrong destination");
    }
    Ok(())
}

async fn wait_for_marker(page: &Page, marker: &str) -> Result<()> {
    let marker = serde_json::to_string(marker).context("encode readiness marker")?;
    timeout(
        Duration::from_secs(10),
        page.evaluate_js(&format!("window.__waitForMarker({marker})")),
    )
    .await
    .context("frame marker readiness timed out")??;
    Ok(())
}

async fn run_operations(page: &Page, pattern: &str, marker: &str) -> Result<()> {
    let value = page
        .evaluate_js_in_frame(pattern, "document.body.dataset.marker")
        .await
        .with_context(|| format!("evaluate frame {pattern}"))?;
    if value.as_str() != Some(marker) {
        bail!("frame evaluation returned the wrong marker");
    }
    let snapshot = page
        .accessibility_snapshot_in_frame(pattern, AccessibilitySnapshotOptions::default())
        .await
        .with_context(|| format!("capture frame accessibility {pattern}"))?;
    if snapshot.state != SnapshotState::Complete
        || !snapshot
            .bytes()
            .windows(marker.len())
            .any(|v| v == marker.as_bytes())
    {
        bail!("frame accessibility snapshot was incomplete or misrouted");
    }
    let rect = page
        .ax_box_in_frame(pattern, "button", marker, 0)
        .await
        .with_context(|| format!("resolve frame geometry {pattern}"))?;
    let [_, _, width, height] = rect.as_slice() else {
        bail!("frame geometry was malformed");
    };
    if *width <= 0.0 || *height <= 0.0 {
        bail!("frame geometry was empty or malformed");
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
async fn measure_case(
    page: &Page,
    case: &'static str,
    pattern: &str,
    marker: &str,
    iteration: usize,
    evaluation: &mut Vec<u128>,
    accessibility: &mut Vec<u128>,
    geometry: &mut Vec<u128>,
) -> Result<()> {
    let started = Instant::now();
    let value = page
        .evaluate_js_in_frame(pattern, "document.body.dataset.marker")
        .await?;
    if value.as_str() != Some(marker) {
        bail!("frame evaluation returned the wrong marker");
    }
    record(case, "evaluate", iteration, started, evaluation)?;

    let started = Instant::now();
    let snapshot = page
        .accessibility_snapshot_in_frame(pattern, AccessibilitySnapshotOptions::default())
        .await?;
    if snapshot.state != SnapshotState::Complete {
        bail!("frame accessibility snapshot was incomplete");
    }
    record(case, "accessibility", iteration, started, accessibility)?;

    let started = Instant::now();
    let rect = page.ax_box_in_frame(pattern, "button", marker, 0).await?;
    let [_, _, width, height] = rect.as_slice() else {
        bail!("frame geometry was malformed");
    };
    if *width <= 0.0 || *height <= 0.0 {
        bail!("frame geometry was empty or malformed");
    }
    record(case, "geometry", iteration, started, geometry)
}

fn record(
    case: &'static str,
    operation: &'static str,
    iteration: usize,
    started: Instant,
    values: &mut Vec<u128>,
) -> Result<()> {
    let elapsed_micros = started.elapsed().as_micros();
    values.push(elapsed_micros);
    println!(
        "{}",
        serde_json::to_string(&AttemptRecord {
            record: "attempt",
            case,
            operation,
            iteration,
            elapsed_micros,
        })?
    );
    Ok(())
}

fn print_summary(case: &'static str, operation: &'static str, mut values: Vec<u128>) -> Result<()> {
    values.sort_unstable();
    if values.is_empty() {
        bail!("benchmark produced no samples");
    }
    let p50 = percentile(&values, 50);
    let p95 = percentile(&values, 95);
    let max = *values.last().context("missing maximum")?;
    println!(
        "{}",
        serde_json::to_string(&SummaryRecord {
            record: "summary",
            case,
            operation,
            attempts: values.len(),
            p50_micros: p50,
            p95_micros: p95,
            max_micros: max,
        })?
    );
    Ok(())
}

fn percentile(values: &[u128], percentile: usize) -> u128 {
    let rank = values.len().saturating_mul(percentile).div_ceil(100);
    values
        .get(rank.saturating_sub(1).min(values.len().saturating_sub(1)))
        .copied()
        .unwrap_or_default()
}

fn parse_usize(name: &str, default: usize) -> Result<usize> {
    match env::var(name) {
        Ok(value) => value
            .parse::<usize>()
            .with_context(|| format!("{name} must be a positive integer"))
            .and_then(|value| {
                if value == 0 {
                    bail!("{name} must be positive")
                }
                Ok(value)
            }),
        Err(env::VarError::NotPresent) => Ok(default),
        Err(error) => Err(error).with_context(|| format!("read {name}")),
    }
}

fn required_env(name: &str) -> Result<String> {
    env::var(name).with_context(|| format!("{name} is required for identity-bound evidence"))
}

fn parent_html(port: u16) -> String {
    format!(
        r#"<!doctype html><body><iframe id="same"></iframe><iframe id="cross"></iframe><script>
        const expected = new Set(['SAME-FRAME', 'OOPIF-FRAME']);
        const seen = new Set();
        const messages = [];
        const waiters = new Map();
        let resolveReady;
        window.__framesReady = new Promise(resolve => {{ resolveReady = resolve; }});
        window.__waitForMarker = marker => {{
          const index = messages.indexOf(marker);
          if (index >= 0) {{ messages.splice(index, 1); return Promise.resolve(marker); }}
          return new Promise(resolve => waiters.set(marker, resolve));
        }};
        window.addEventListener('message', event => {{
          if (event.data?.fixture !== 'cas-383-benchmark') return;
          const waiter = waiters.get(event.data.marker);
          if (waiter) {{ waiters.delete(event.data.marker); waiter(event.data.marker); }}
          else messages.push(event.data.marker);
          expected.has(event.data.marker) && seen.add(event.data.marker);
          if (seen.size === expected.size) resolveReady(true);
        }});
        window.__loadFrames = () => {{
          document.getElementById('same').src = 'http://a.test:{port}/same';
          document.getElementById('cross').src = 'http://b.test:{port}/cross';
        }};
        </script></body>"#
    )
}

fn child_html(port: u16, marker: &str, nested: bool) -> String {
    let nested_frame = if nested {
        format!("<iframe src=\"http://b.test:{port}/nested\"></iframe>")
    } else {
        String::new()
    };
    format!(
        r#"<!doctype html><body data-marker="{marker}" data-clicked="false"><button id="action" aria-label="{marker}">{marker}</button>{nested_frame}<script>
        document.getElementById('action').addEventListener('click', () => {{ document.body.dataset.clicked = 'true'; }});
        window.addEventListener('load', () => window.parent.postMessage(
          {{ fixture: 'cas-383-benchmark', marker: '{marker}' }}, 'http://a.test:{port}'
        ), {{ once: true }});
        </script></body>"#
    )
}

fn nested_html() -> String {
    "<!doctype html><body data-marker=\"OOPIF-NESTED\"><button aria-label=\"OOPIF-NESTED\">OOPIF-NESTED</button></body>".to_owned()
}

async fn serve(mut stream: TcpStream, port: u16, parent: Arc<str>) {
    let Some((host, path)) = read_request(&mut stream).await else {
        return;
    };
    let body = match (host.as_str(), path.as_str()) {
        ("a.test", "/parent") => parent.to_string(),
        ("a.test", "/same") => child_html(port, "SAME-FRAME", false),
        ("a.test", "/swap-same") => child_html(port, "SAME-SWAP", false),
        ("b.test", "/cross") => child_html(port, "OOPIF-FRAME", true),
        ("b.test", "/cross-final") => child_html(port, "OOPIF-FINAL", false),
        ("b.test", "/nested") => nested_html(),
        _ => String::from("missing"),
    };
    let status = if body == "missing" {
        "404 Not Found"
    } else {
        "200 OK"
    };
    let response = format!(
        "HTTP/1.1 {status}\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n{body}",
        body.len()
    );
    let _ = stream.write_all(response.as_bytes()).await;
    let _ = stream.shutdown().await;
}

async fn read_request(stream: &mut TcpStream) -> Option<(String, String)> {
    let mut bytes = Vec::with_capacity(1024);
    let mut chunk = [0_u8; 1024];
    loop {
        let read = stream.read(&mut chunk).await.ok()?;
        if read == 0 || bytes.len().checked_add(read)? > REQUEST_LIMIT {
            return None;
        }
        bytes.extend_from_slice(chunk.get(..read)?);
        if bytes.windows(4).any(|window| window == b"\r\n\r\n") {
            break;
        }
    }
    let request = String::from_utf8_lossy(&bytes);
    let mut lines = request.lines();
    let path = lines
        .next()?
        .split_whitespace()
        .nth(1)?
        .split('?')
        .next()?
        .to_owned();
    let host = lines.find_map(|line| {
        let (name, value) = line.split_once(':')?;
        name.eq_ignore_ascii_case("host").then(|| {
            value
                .trim()
                .split(':')
                .next()
                .unwrap_or_default()
                .to_ascii_lowercase()
        })
    })?;
    Some((host, path))
}
