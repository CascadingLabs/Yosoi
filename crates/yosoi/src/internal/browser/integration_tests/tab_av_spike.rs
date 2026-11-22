//! Explicitly invoked fixture qualification; never part of the normal browser matrix.
use crate::internal::browser::vendor::chromiumoxide::cdp::js_protocol::runtime::EvaluateParams;
use crate::internal::browser::{BrowserSession, Page};
use serde_json::{Value, json};
use std::{env, error::Error, fs, io, path::PathBuf, result::Result as StdResult, time::Duration};
use tokio::time::timeout;

type Result<T> = StdResult<T, Box<dyn Error + Send + Sync>>;

#[path = "youtube_tab_av_spike.rs"]
mod youtube;

async fn evaluate(page: &Page, expression: &str) -> Result<Value> {
    let params = EvaluateParams::builder()
        .expression(expression)
        .await_promise(true)
        .return_by_value(true)
        .build()?;
    Ok(timeout(
        Duration::from_secs(45),
        page.cdp().evaluate_expression(params),
    )
    .await??
    .into_value()?)
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "opt-in loopback-only tab A/V capture qualification"]
async fn concurrent_tab_av_spike() -> Result<()> {
    let origin = env::var("YOSOI_TAB_AV_ORIGIN")?;
    let parsed = url::Url::parse(&origin)?;
    if parsed.scheme() != "http"
        || parsed.host_str() != Some("127.0.0.1")
        || parsed.port().is_none()
    {
        return Err(io::Error::other("the spike only accepts its loopback fixture origin").into());
    }
    let output = PathBuf::from(env::var("YOSOI_TAB_AV_OUTPUT")?);
    fs::create_dir_all(&output)?;
    let count: u32 = env::var("YOSOI_TAB_AV_COUNT")?.parse()?;
    if !(2..=4).contains(&count) {
        return Err(io::Error::other("use 2–4 tabs").into());
    }
    // The user-requested capture fixture explicitly grants each isolated tab
    // permission to capture itself. No real desktop, camera or microphone is
    // selected. This switch is confined to this ignored test, never SDK defaults.
    let browser = BrowserSession::builder()
        .headful()
        .viewport(640, 360)
        .window_size(960, 720)
        .arg("auto-accept-this-tab-capture")
        .launch()
        .await?;
    let result = async {
        let mut pages = Vec::new();
        let mut ready = Vec::new();
        for id in 0..count {
            let page = browser.new_page(&format!("{origin}/tab?id={id}&duration=16000&fps=30")).await?;
            page.cdp().bring_to_front().await?;
            // Semantic fixture control, with a trusted native compositor click.
            page.click_by_role("button", &format!("Start tab {} capture", char::from_u32(65_u32.saturating_add(id))
                .ok_or_else(|| io::Error::other("invalid tab label"))?), 0, true).await?;
            let started = evaluate(&page, "window.tabAvReady").await?;
            if started.get("error").is_some() { return Err(io::Error::other(started.to_string()).into()); }
            ready.push(json!({"target":page.target_id(),"capture":started}));
            pages.push(page);
        }
        let control = browser.new_page(&format!("{origin}/control")).await?;
        control.cdp().bring_to_front().await?;
        let control_before = evaluate(&control, "({title:document.title,visibility:document.visibilityState,focus:document.hasFocus(),at:Date.now()})").await?;
        let mut results = Vec::new();
        for page in &pages {
            if page.alone_in_window().await? { return Err(io::Error::other("capture tab unexpectedly has a separate window").into()); }
            results.push(evaluate(page, "window.tabAvDone").await?);
        }
        let control_after = evaluate(&control, "({title:document.title,visibility:document.visibilityState,focus:document.hasFocus(),at:Date.now()})").await?;
        let report = json!({"provider":"native Yosoi BrowserSession / Chromiumoxide CDP",
            "tabs":count,"ready":ready,"control_target":control.target_id(),
            "control_before":control_before,"control_after":control_after,"results":results,
            "capture":"getDisplayMedia preferCurrentTab + VP8/Opus MediaRecorder",
            "scope":"cooperating fixture pages; same browser and shared window; not generic arbitrary-site recording"});
        fs::write(output.join("browser-report.json"), serde_json::to_vec_pretty(&report)?)?;
        println!("TAB_AV_REPORT={report}");
        drop(control);
        drop(pages);
        Ok::<_, Box<dyn Error + Send + Sync>>(())
    }.await;
    let closed = browser.close().await;
    drop(browser);
    result?;
    closed?;
    Ok(())
}
