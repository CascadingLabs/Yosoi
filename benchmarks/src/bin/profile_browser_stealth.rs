//! CAS-374 browser fingerprint and automation-disclosure probe.
//!
//! The hermetic fixture is the conformance gate. An optional public URL is an
//! observation only: third-party detector output is mutable and never becomes
//! a bypass guarantee.

use anyhow::{Context, Result, bail};
use serde::Serialize;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    env,
    num::NonZeroU16,
    sync::Arc,
    time::{Instant, SystemTime},
};
use url::Url;
use void_crawl_core::{BrowserDebugPortPolicy, BrowserSession, CdpMode, Page, VoidCrawlError};
use yosoi_benchmarks::stealth_support::{
    Fixture, LIVE_READY_JS, LIVE_SUMMARY_JS, LiveSummaryParts, WEBDRIVER_DISGUISE,
    live_summary_parts, snapshot, validate_snapshot,
};

#[derive(Clone, Copy, Debug, Serialize)]
#[serde(rename_all = "snake_case")]
enum RunMode {
    Headless,
    Headful,
}

#[derive(Clone, Copy, Debug, Serialize)]
#[serde(rename_all = "snake_case")]
enum WebdriverPolicy {
    SupportedConfiguration,
    AutomationDisclosed,
    BoundedDisguise,
}

#[derive(Debug)]
struct Options {
    mode: RunMode,
    webdriver_policy: WebdriverPolicy,
    cdp_mode: CdpMode,
    fixed_port: Option<u16>,
    live_url: Option<String>,
}

#[derive(Debug, Serialize)]
struct LiveObservation {
    url: String,
    final_url: Option<String>,
    ready_signal_observed: bool,
    title: Option<String>,
    body_bytes: usize,
    body_sha256: String,
    detector_signals: Value,
    detector_statuses: Value,
    scores: Value,
    diagnostic_rows: Value,
    provider_resources: Value,
    challenge_markers: Value,
    fingerprint: Value,
}

#[derive(Debug, Serialize)]
struct Report {
    schema: &'static str,
    captured_at: chrono::DateTime<chrono::Utc>,
    mode: RunMode,
    browser_product: String,
    webdriver_policy: WebdriverPolicy,
    cdp_mode: &'static str,
    elapsed_ms: u128,
    stages: Vec<(&'static str, Value)>,
    live: Option<LiveObservation>,
    isolated_context_cleanup: Value,
    browser_cleanup_complete: bool,
    contract_passed: bool,
    contract_violations: Vec<String>,
}

fn parse_options() -> Result<Options> {
    let mut options = Options {
        mode: RunMode::Headless,
        webdriver_policy: WebdriverPolicy::SupportedConfiguration,
        cdp_mode: CdpMode::Normal,
        fixed_port: None,
        live_url: None,
    };
    let mut arguments = env::args().skip(1);
    while let Some(argument) = arguments.next() {
        let value = arguments.next().context("missing option value")?;
        match argument.as_str() {
            "--mode" => {
                options.mode = match value.as_str() {
                    "headless" => RunMode::Headless,
                    "headful" => RunMode::Headful,
                    _ => bail!("mode must be headless or headful"),
                }
            }
            "--webdriver-policy" => {
                options.webdriver_policy = match value.as_str() {
                    "supported-configuration" => WebdriverPolicy::SupportedConfiguration,
                    "automation-disclosed" => WebdriverPolicy::AutomationDisclosed,
                    "bounded-disguise" => WebdriverPolicy::BoundedDisguise,
                    _ => bail!("unknown webdriver policy"),
                }
            }
            "--cdp-mode" => {
                options.cdp_mode = match value.as_str() {
                    "normal" => CdpMode::Normal,
                    "minimal" => CdpMode::Minimal,
                    _ => bail!("CDP mode must be normal or minimal"),
                }
            }
            "--fixed-port" => {
                options.fixed_port = Some(value.parse().context("invalid fixed port")?);
            }
            "--live-url" => options.live_url = Some(validate_live_url(&value)?),
            _ => bail!("unknown option {argument}"),
        }
    }
    Ok(options)
}

fn validate_live_url(value: &str) -> Result<String> {
    let parsed = Url::parse(value).context("live URL is invalid")?;
    if parsed.scheme() != "https" {
        bail!("live URL must use HTTPS")
    }
    if !parsed.username().is_empty() || parsed.password().is_some() {
        bail!("live URL must not contain credentials")
    }
    if parsed.query().is_some() || parsed.fragment().is_some() {
        bail!("live URL must not contain a query or fragment")
    }
    Ok(parsed.to_string())
}

async fn prepare_page(page: &Page, policy: WebdriverPolicy) -> Result<()> {
    if matches!(policy, WebdriverPolicy::BoundedDisguise) {
        page.add_init_script(WEBDRIVER_DISGUISE)
            .await
            .context("installing bounded webdriver disguise")?;
    }
    Ok(())
}

async fn snapshot_stage(page: &Page, stage: &'static str) -> Result<Value> {
    snapshot(page)
        .await
        .with_context(|| format!("capturing {stage} fingerprint snapshot"))
}

async fn attached_page_with_title(session: &BrowserSession, title: &str) -> Result<Page> {
    for candidate in session
        .pages()
        .await
        .context("enumerating pages in attached browser session")?
    {
        if candidate
            .title()
            .await
            .context("reading attached page title")?
            .as_deref()
            == Some(title)
        {
            return Ok(candidate);
        }
    }
    bail!("attached browser session did not contain page titled {title:?}")
}

async fn navigate_fixture(page: &Page, url: &str, stage: &'static str) -> Result<()> {
    page.navigate(url).await.map_err(|error| match error {
        VoidCrawlError::NavigationFailed(detail) => {
            anyhow::anyhow!("{stage} fixture navigation failed: {detail}")
        }
        other => anyhow::anyhow!("{stage} fixture navigation failed: {other}"),
    })
}

const fn expected_webdriver(policy: WebdriverPolicy) -> bool {
    matches!(policy, WebdriverPolicy::AutomationDisclosed)
}

async fn live_observation(page: &Page, url: String) -> Result<LiveObservation> {
    page.navigate(&url)
        .await
        .with_context(|| format!("navigating to live diagnostic {url}"))?;
    let ready_signal_observed = page
        .evaluate_js(LIVE_READY_JS)
        .await
        .context("waiting for live diagnostic readiness")?
        .as_bool()
        .is_some_and(|value| value);
    let summary = page
        .evaluate_js(LIVE_SUMMARY_JS)
        .await
        .context("capturing live diagnostic summary")?;
    let LiveSummaryParts {
        signals: detector_signals,
        statuses: detector_statuses,
        scores,
        rows: diagnostic_rows,
        provider_resources,
        challenge_markers,
        body,
    } = live_summary_parts(&summary);
    let body_sha256 = format!("{:x}", Sha256::digest(body.as_bytes()));
    Ok(LiveObservation {
        url,
        final_url: page
            .url()
            .await
            .context("reading final live diagnostic URL")?,
        ready_signal_observed,
        title: summary
            .pointer("/title")
            .and_then(Value::as_str)
            .map(str::to_owned),
        body_bytes: body.len(),
        body_sha256,
        detector_signals,
        detector_statuses,
        scores,
        diagnostic_rows,
        provider_resources,
        challenge_markers,
        fingerprint: snapshot_stage(page, "live_diagnostic").await?,
    })
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<()> {
    let started = Instant::now();
    let options = parse_options()?;
    let executable = env::var("CHROME").context("CHROME must name the certified executable")?;
    let fixture = Fixture::start()
        .await
        .context("starting hermetic fingerprint fixture")?;
    let mut builder = BrowserSession::builder()
        .chrome_executable(executable)
        .cdp_mode(options.cdp_mode);
    builder = match options.mode {
        RunMode::Headless => builder.headless(),
        RunMode::Headful => builder.headful(),
    };
    if let Some(port) = options.fixed_port {
        let port = NonZeroU16::new(port).context("fixed port must be non-zero")?;
        builder = builder.debug_port_policy(BrowserDebugPortPolicy::Fixed(port));
    } else if matches!(
        options.webdriver_policy,
        WebdriverPolicy::AutomationDisclosed | WebdriverPolicy::BoundedDisguise
    ) {
        builder = builder.debug_port_policy(BrowserDebugPortPolicy::ChromeAssigned);
    }
    let session = builder
        .launch()
        .await
        .context("launching owner browser session")?;
    let browser_product = session
        .version()
        .await
        .context("reading owner browser version")?;
    let mut stages = Vec::new();
    let mut violations = Vec::new();

    let page = session
        .new_blank_page()
        .await
        .context("creating first browser page")?;
    prepare_page(&page, options.webdriver_policy)
        .await
        .context("preparing first browser page")?;
    navigate_fixture(
        &page,
        &format!("{}/first", fixture.base_url),
        "first_document",
    )
    .await?;
    let first = snapshot_stage(&page, "first_document").await?;
    validate_snapshot(
        "first_document",
        &first,
        expected_webdriver(options.webdriver_policy),
        &mut violations,
    );
    stages.push(("first_document", first));

    page.evaluate_js("location.hash = 'same-document'")
        .await
        .context("navigating within the first document")?;
    let same = snapshot_stage(&page, "same_document").await?;
    validate_snapshot(
        "same_document",
        &same,
        expected_webdriver(options.webdriver_policy),
        &mut violations,
    );
    stages.push(("same_document", same));

    navigate_fixture(
        &page,
        &format!("{}/second", fixture.base_url),
        "cross_document",
    )
    .await?;
    let cross = snapshot_stage(&page, "cross_document").await?;
    validate_snapshot(
        "cross_document",
        &cross,
        expected_webdriver(options.webdriver_policy),
        &mut violations,
    );
    stages.push(("cross_document", cross));

    let tab = session
        .new_blank_page()
        .await
        .context("creating second browser tab")?;
    prepare_page(&tab, options.webdriver_policy)
        .await
        .context("preparing second browser tab")?;
    navigate_fixture(&tab, &format!("{}/tab", fixture.base_url), "new_tab").await?;
    let tab_snapshot = snapshot_stage(&tab, "new_tab").await?;
    validate_snapshot(
        "new_tab",
        &tab_snapshot,
        expected_webdriver(options.webdriver_policy),
        &mut violations,
    );
    stages.push(("new_tab", tab_snapshot));

    let context = session
        .new_isolated_context()
        .await
        .context("creating isolated browser context")?;
    let context_page: Arc<Page> = context.page_handle();
    prepare_page(&context_page, options.webdriver_policy)
        .await
        .context("preparing isolated context page")?;
    navigate_fixture(
        &context_page,
        &format!("{}/context", fixture.base_url),
        "isolated_context",
    )
    .await?;
    let context_snapshot = snapshot_stage(&context_page, "isolated_context").await?;
    validate_snapshot(
        "isolated_context",
        &context_snapshot,
        expected_webdriver(options.webdriver_policy),
        &mut violations,
    );
    stages.push(("isolated_context", context_snapshot));

    const ATTACHED_PAGE_TITLE: &str = "cas374-attached-existing-document";
    page.evaluate_js("document.title = 'cas374-attached-existing-document'")
        .await
        .context("marking page for typed attached-session discovery")?;
    let attached = BrowserSession::builder()
        .remote_debug(session.websocket_url().await)
        .cdp_mode(options.cdp_mode)
        .launch()
        .await
        .context("launching attached browser session")?;
    let attached_page = attached_page_with_title(&attached, ATTACHED_PAGE_TITLE).await?;
    let attached_existing = snapshot_stage(&attached_page, "attached_existing_document").await?;
    validate_snapshot(
        "attached_existing_document",
        &attached_existing,
        expected_webdriver(options.webdriver_policy),
        &mut violations,
    );
    stages.push(("attached_existing_document", attached_existing));
    attached
        .close()
        .await
        .context("closing attached browser session")?;

    let live = match options.live_url {
        Some(url) => Some(
            live_observation(&page, url)
                .await
                .context("capturing live diagnostic observation")?,
        ),
        None => None,
    };

    tab.close().await.context("closing second browser tab")?;
    let context_cleanup = context.dispose().await;
    if !context_cleanup.cleanup_complete {
        violations.push("isolated context cleanup was incomplete".to_string());
    }
    page.close().await.context("closing first browser page")?;
    session
        .close()
        .await
        .context("closing owner browser session")?;
    fixture.close().await.context("closing hermetic fixture")?;

    let contract_passed = violations.is_empty();
    let report = Report {
        schema: "yosoi.cas374.browser-stealth.v1",
        captured_at: chrono::DateTime::<chrono::Utc>::from(SystemTime::now()),
        mode: options.mode,
        browser_product,
        webdriver_policy: options.webdriver_policy,
        cdp_mode: match options.cdp_mode {
            CdpMode::Normal => "normal",
            CdpMode::Minimal => "minimal",
        },
        elapsed_ms: started.elapsed().as_millis(),
        stages,
        live,
        isolated_context_cleanup: serde_json::to_value(context_cleanup)?,
        browser_cleanup_complete: true,
        contract_passed,
        contract_violations: violations,
    };
    println!("{}", serde_json::to_string_pretty(&report)?);
    if !contract_passed {
        bail!("one or more hermetic stealth contracts failed")
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::validate_live_url;

    #[test]
    fn live_urls_are_https_and_secret_free() {
        assert!(validate_live_url("https://example.test/path").is_ok());
        for rejected in [
            "http://example.test/path",
            "https://user:secret@example.test/path",
            "https://example.test/path?token=secret",
            "https://example.test/path#fragment",
        ] {
            assert!(validate_live_url(rejected).is_err(), "accepted {rejected}");
        }
    }
}
