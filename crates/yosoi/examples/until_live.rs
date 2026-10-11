//! Live, bounded examples of event-driven browser confirmation.
//!
//! Run one pass by default; pass an evidence directory and an optional
//! iteration count (1 through 5):
//! `cargo run -p yosoi --features browser --example until_live -- <evidence-dir> [iterations]`
//!
//! The example opens two owned tabs on one shared execution pool. It stops on
//! the first failed pass and retains the complete Flow outcomes before closing
//! the tabs and Session.

use std::process as std_process;
use std::{
    env,
    error::Error,
    fs, io,
    path::{Path, PathBuf},
    time::{Instant, SystemTime, UNIX_EPOCH},
};

use tokio::task::JoinSet;
use yosoi::{
    Archive, action,
    automation_record::{
        AutomationContext, AutomationRecord, AutomationRecordRef, MAX_OBSERVATION_SCREENSHOT_BYTES,
    },
    expect::{self, Expectation},
    flow::{self, FailureCapturePolicy, Flow, FlowOutcome, FlowTermination},
    policy::Policy,
    prelude as ys,
    session::{self, ActionKind, ExecutionPool, Session, SessionPolicy, Tab, Work},
};

type LiveError = Box<dyn Error + Send + Sync>;

const DYNAMIC_LOADING_URL: &str = "https://the-internet.herokuapp.com/dynamic_loading/1";
const HTTPBIN_PAGE_URL: &str = "https://httpbin.org/html";
const HTTPBIN_ORIGIN: &str = "https://httpbin.org";
const MAX_ITERATIONS: usize = 5;

#[derive(ys::Contract)]
#[ys(
    id = "dynamic_loading_message",
    description = "The text rendered by the dynamic loading example",
    root = ys::locator::css("#finish")
)]
struct DynamicLoadingHeading {
    #[ys(
        description = "The completed loading message",
        locator = ys::locator::css("h4").text()
    )]
    text: String,
}

#[derive(serde::Serialize)]
struct RunReport {
    source_revision: Option<String>,
    browser_identity: Option<String>,
    browser_identity_source: &'static str,
    session_mode: String,
    iterations_requested: usize,
    pool_capacity: Option<u32>,
    pool_peak_active: Option<u32>,
    pool_active_after_close: Option<u32>,
    pool_queued_after_close: Option<u32>,
    pool_parked_after_close: Option<u32>,
    error: Option<String>,
    archive_error: Option<String>,
    runs: Vec<RunSummary>,
}

#[derive(serde::Serialize)]
struct RunSummary {
    site: String,
    url: String,
    iteration: usize,
    elapsed_ms: u128,
    completed: bool,
    terminal: Option<FlowTermination>,
    error: Option<String>,
    outcome_file: String,
    screenshot_files: Vec<String>,
    screenshots_omitted: Vec<String>,
    archive_ref: Option<AutomationRecordRef>,
    archive_read_verified: bool,
    archive_error: Option<String>,
}

struct SiteRun {
    site: &'static str,
    url: String,
    iteration: usize,
    elapsed_ms: u128,
    outcome: Option<FlowOutcome>,
    error: Option<String>,
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), LiveError> {
    let (output_dir, iterations) = parse_args()?;
    fs::create_dir_all(&output_dir)?;
    let mode = if env::var("YOSOI_YIELD_MODE").as_deref() == Ok("headful") {
        session::BrowserMode::Headful
    } else {
        session::BrowserMode::Headless
    };
    let mut report = RunReport {
        source_revision: optional_env("YOSOI_SPIKE_SOURCE_REVISION"),
        browser_identity: optional_env("YOSOI_SPIKE_BROWSER_IDENTITY"),
        browser_identity_source: "YOSOI_SPIKE_BROWSER_IDENTITY",
        session_mode: format!("{mode:?}"),
        iterations_requested: iterations,
        pool_capacity: None,
        pool_peak_active: None,
        pool_active_after_close: None,
        pool_queued_after_close: None,
        pool_parked_after_close: None,
        error: None,
        archive_error: None,
        runs: Vec::new(),
    };

    run_browser(&output_dir, iterations, mode, &mut report).await;
    write_report(&output_dir, &report)?;
    println!("{}", serde_json::to_string_pretty(&report)?);

    if let Some(error) = &report.error {
        return Err(io::Error::other(error.clone()).into());
    }
    if report.runs.iter().any(|run| !run.completed) {
        return Err(io::Error::other(
            "a live until flow failed; evidence was retained and no retry was made",
        )
        .into());
    }
    Ok(())
}

fn parse_args() -> Result<(PathBuf, usize), io::Error> {
    let mut arguments = env::args().skip(1);
    let output = arguments
        .next()
        .map(PathBuf::from)
        .or_else(|| env::var_os("YOSOI_BROWSER_OUTPUT_DIR").map(PathBuf::from))
        .ok_or_else(|| {
            io::Error::other("usage: until_live <evidence-dir> [iterations, default 1, maximum 5]")
        })?;
    let iterations = match arguments.next() {
        Some(value) => value
            .parse::<usize>()
            .map_err(|_| io::Error::other("iterations must be an integer from 1 through 5"))?,
        None => 1,
    };
    if !(1..=MAX_ITERATIONS).contains(&iterations) || arguments.next().is_some() {
        return Err(io::Error::other(
            "usage: until_live <evidence-dir> [iterations from 1 through 5]",
        ));
    }
    Ok((output, iterations))
}

#[expect(
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn run_browser(
    output_dir: &Path,
    iterations: usize,
    mode: session::BrowserMode,
    report: &mut RunReport,
) {
    let pool = match ExecutionPool::new(2, 16) {
        Ok(pool) => pool,
        Err(error) => {
            report.error = Some(format!("execution pool creation failed: {error}"));
            return;
        }
    };
    report.pool_capacity = Some(pool.snapshot().capacity);

    let mut session_policy = SessionPolicy {
        mode,
        maximum_tabs: 2,
        execution_concurrency: 2,
        maximum_queued_operations: 16,
        allow_arbitrary_js: true,
        maximum_result_bytes: 512 * 1024,
        maximum_observation_bytes: 128 * 1024,
        watch_capacity: 64,
        ..SessionPolicy::default()
    };
    if !session_policy
        .allowed_actions
        .contains(&ActionKind::Evaluate)
    {
        session_policy.allowed_actions.push(ActionKind::Evaluate);
    }

    let browser_session = match session::new()
        .configure(session_policy.clone())
        .execution_pool(&pool)
        .acquire()
        .await
    {
        Ok(session) => session,
        Err(error) => {
            report.error = Some(format!("browser Session acquisition failed: {error}"));
            return;
        }
    };

    let second_tab = match browser_session.new_tab().await {
        Ok(tab) => Some(tab),
        Err(error) => {
            report.error = Some(format!("second tab acquisition failed: {error}"));
            None
        }
    };

    let archive = match Archive::open(output_dir.join("archive")).await {
        Ok(archive) => Some(archive),
        Err(error) => {
            report.archive_error = Some(format!("archive could not be opened: {error}"));
            None
        }
    };
    let base_policy = Policy::default();
    let policy_identity = base_policy
        .effective_identity()
        .map(|identity| format!("v{}:{}", identity.version(), identity.digest()));
    if let Err(error) = &policy_identity {
        report.archive_error = Some(format!(
            "policy identity unavailable for archive context: {error}"
        ));
    }
    let context = policy_identity
        .ok()
        .map(|effective_policy_identity| AutomationContext {
            effective_policy_identity,
            session_policy: session_policy.clone(),
            provider: "voidcrawl/cdp".to_owned(),
            browser_identity: report.browser_identity.clone(),
            source_revision: report.source_revision.clone(),
            parent: None,
        });

    if let Some(tab) = second_tab.as_ref() {
        for iteration in 1..=iterations {
            let runs = match execute_iteration(&browser_session, tab, iteration).await {
                Ok(runs) => runs,
                Err(error) => {
                    report.error = Some(format!("iteration {iteration} could not start: {error}"));
                    break;
                }
            };
            let mut iteration_failed = false;
            for run in runs {
                let summary =
                    match persist_run(output_dir, run, archive.as_ref(), context.as_ref()).await {
                        Ok(summary) => summary,
                        Err(error) => {
                            report.error = Some(format!("evidence persistence failed: {error}"));
                            iteration_failed = true;
                            continue;
                        }
                    };
                iteration_failed |= !summary.completed;
                println!(
                    "{} iteration {}: completed={}, {:?}, {} ms",
                    summary.site,
                    summary.iteration,
                    summary.completed,
                    summary.terminal,
                    summary.elapsed_ms
                );
                report.runs.push(summary);
            }
            if iteration_failed {
                break;
            }
        }
    }

    if let Some(archive) = archive {
        drop(archive);
    }
    if let Some(tab) = second_tab
        && let Err(error) = tab.close().await
    {
        report
            .error
            .get_or_insert_with(|| format!("second tab close failed: {error}"));
    }
    if let Err(error) = browser_session.close().await {
        report
            .error
            .get_or_insert_with(|| format!("browser Session close failed: {error}"));
    }
    let snapshot = pool.snapshot();
    report.pool_peak_active = Some(snapshot.peak_active);
    report.pool_active_after_close = Some(snapshot.active);
    report.pool_queued_after_close = Some(snapshot.queued);
    report.pool_parked_after_close = Some(snapshot.parked);
    if snapshot.active != 0
        || snapshot.queued != 0
        || snapshot.parked != 0
        || snapshot.peak_active > 2
    {
        report.error.get_or_insert_with(|| {
            "shared execution pool did not settle within its two-worker bound".to_owned()
        });
    }
}

#[expect(
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn execute_iteration(
    browser_session: &Session,
    second_tab: &Tab,
    iteration: usize,
) -> Result<Vec<SiteRun>, LiveError> {
    let dynamic = dynamic_flow()?;
    let nonce = unique_nonce(iteration);
    let response_url = format!("{HTTPBIN_ORIGIN}/anything?until_proof={nonce}");
    let httpbin = httpbin_flow(&nonce, &response_url)?;

    let dynamic_work = browser_session.work().await?;
    let response_work = match second_tab.work().await {
        Ok(work) => work,
        Err(error) => {
            dynamic_work.release().await?;
            return Err(error.into());
        }
    };

    let mut jobs = JoinSet::new();
    jobs.spawn(invoke_flow(
        dynamic_work,
        dynamic,
        "dynamic-loading",
        DYNAMIC_LOADING_URL.to_owned(),
        iteration,
    ));
    jobs.spawn(invoke_flow(
        response_work,
        httpbin,
        "httpbin-response",
        HTTPBIN_PAGE_URL.to_owned(),
        iteration,
    ));

    let mut runs = Vec::with_capacity(2);
    while let Some(result) = jobs.join_next().await {
        match result {
            Ok(run) => runs.push(run),
            Err(error) => {
                runs.push(SiteRun {
                    site: "worker-task",
                    url: String::new(),
                    iteration,
                    elapsed_ms: 0,
                    outcome: None,
                    error: Some(format!("live worker task failed: {error}")),
                });
            }
        }
    }
    Ok(runs)
}

async fn invoke_flow(
    work: Work,
    recipe: Flow,
    site: &'static str,
    url: String,
    iteration: usize,
) -> SiteRun {
    let started = Instant::now();
    let invocation = recipe.with_lease(&work).invoke().await;
    let release = work.release().await;
    let elapsed_ms = started.elapsed().as_millis();
    match invocation {
        Ok(outcome) => {
            let completed = outcome.require_completed().is_ok();
            let error = release
                .err()
                .map(|error| format!("Work release failed: {error}"))
                .or_else(|| {
                    (!completed).then(|| format!("Flow stopped with {:?}", outcome.terminal))
                });
            SiteRun {
                site,
                url,
                iteration,
                elapsed_ms,
                outcome: Some(outcome),
                error,
            }
        }
        Err(error) => SiteRun {
            site,
            url,
            iteration,
            elapsed_ms,
            outcome: None,
            error: Some(release.err().map_or_else(
                || format!("Flow invocation failed: {error}"),
                |release_error| {
                    format!("Flow invocation failed: {error}; Work release failed: {release_error}")
                },
            )),
        },
    }
}

fn dynamic_flow() -> Result<Flow, LiveError> {
    let confirmation = expect::all([
        expect::visible("#finish h4"),
        Expectation::from(expect::ax("Hello World!").role("heading")),
    ]);
    Ok(flow::new([
        action::navigate(DYNAMIC_LOADING_URL),
        expect::visible("#start button").until(),
        action::click("#start button").until(confirmation),
        action::assert_all::<DynamicLoadingHeading>(
            DynamicLoadingHeading::plan()?,
            [
                action::check(|heading: &DynamicLoadingHeading| heading.text == "Hello World!")
                    .named("exact result text"),
            ],
        )
        .until(),
        action::screenshot(),
    ])
    .timeout(60_000)
    .with_failure_capture(FailureCapturePolicy::Screenshot))
}

fn httpbin_flow(nonce: &str, response_url: &str) -> Result<Flow, LiveError> {
    let relative = format!("/anything?until_proof={nonce}");
    let encoded_relative = serde_json::to_string(&relative)?;
    let trigger = action::evaluate(format!("void fetch({encoded_relative})"));
    let expected_response = expect::response(response_url)
        .method("GET")
        .status(200)
        .json("/args/until_proof", nonce);
    Ok(flow::new([
        action::navigate(HTTPBIN_PAGE_URL),
        expect::visible("h1").until(),
        trigger.until(expected_response),
        action::screenshot(),
    ])
    .timeout(60_000)
    .with_failure_capture(FailureCapturePolicy::Screenshot))
}

async fn persist_run(
    output_dir: &Path,
    run: SiteRun,
    archive: Option<&Archive>,
    context: Option<&AutomationContext>,
) -> Result<RunSummary, LiveError> {
    let outcome_file_name = format!("{}-iteration-{}.json", run.site, run.iteration);
    let outcome_path = output_dir.join(&outcome_file_name);
    let mut screenshot_files = Vec::new();
    let mut screenshots_omitted = Vec::new();
    let mut archive_ref = None;
    let mut archive_read_verified = false;
    let mut archive_error = None;
    let mut error = run.error;
    let terminal = run.outcome.as_ref().map(|outcome| outcome.terminal);
    let completed = run
        .outcome
        .as_ref()
        .is_some_and(|outcome| outcome.require_completed().is_ok())
        && error.is_none();

    if let Some(outcome) = run.outcome {
        let encoded = serde_json::to_vec_pretty(&outcome)?;
        fs::write(&outcome_path, encoded)?;
        save_screenshots(
            output_dir,
            run.site,
            run.iteration,
            &outcome,
            &mut screenshot_files,
            &mut screenshots_omitted,
        )?;

        match (archive, context) {
            (Some(archive), Some(context)) => {
                let archived = async {
                    let record = AutomationRecord::new(
                        format!("live-until-{}-{}", run.site, session::new_operation_id()),
                        Vec::new(),
                        Vec::new(),
                    )?
                    .with_context(context.clone())?
                    .with_flow_outcome(outcome.clone())?;
                    let reference = record.write_to(archive).await?;
                    let reopened = Archive::open(output_dir.join("archive")).await?;
                    let saved = AutomationRecord::read_from(&reopened, &reference).await?;
                    if serde_json::to_value(&saved)? != serde_json::to_value(&record)? {
                        return Err(io::Error::other(
                            "reopened archive changed the saved evidence",
                        )
                        .into());
                    }
                    Ok::<_, LiveError>(reference)
                }
                .await;
                match archived {
                    Ok(reference) => {
                        let ref_name =
                            format!("{}-iteration-{}-archive-ref.json", run.site, run.iteration);
                        fs::write(
                            output_dir.join(&ref_name),
                            serde_json::to_vec_pretty(&reference)?,
                        )?;
                        archive_ref = Some(reference);
                        archive_read_verified = true;
                    }
                    Err(archive_failure) => {
                        archive_error = Some(archive_failure.to_string());
                    }
                }
            }
            (None, _) => {
                archive_error =
                    Some("archive is unavailable; the full JSON outcome was saved".to_owned());
            }
            (_, None) => {
                archive_error = Some(
                    "archive context is unavailable; the full JSON outcome was saved".to_owned(),
                );
            }
        }
    } else {
        fs::write(
            &outcome_path,
            serde_json::to_vec_pretty(&serde_json::json!({
                "site": run.site,
                "url": run.url,
                "iteration": run.iteration,
                "elapsed_ms": run.elapsed_ms,
                "error": error.as_deref(),
            }))?,
        )?;
        if error.is_none() {
            error = Some("Flow produced no outcome".to_owned());
        }
    }

    Ok(RunSummary {
        site: run.site.to_owned(),
        url: run.url,
        iteration: run.iteration,
        elapsed_ms: run.elapsed_ms,
        completed,
        terminal,
        error,
        outcome_file: outcome_file_name,
        screenshot_files,
        screenshots_omitted,
        archive_ref,
        archive_read_verified,
        archive_error,
    })
}

fn save_screenshots(
    output_dir: &Path,
    site: &str,
    iteration: usize,
    outcome: &FlowOutcome,
    files: &mut Vec<String>,
    omitted: &mut Vec<String>,
) -> Result<(), io::Error> {
    for step in &outcome.steps {
        if let Some(bytes) = step
            .receipt
            .observation
            .as_ref()
            .and_then(|observation| observation.screenshot.as_ref())
        {
            write_bounded_screenshot(
                output_dir,
                format!("{site}-iteration-{iteration}-step-{}.png", step.index),
                bytes,
                files,
                omitted,
            )?;
        }
    }
    if let Some(bytes) = outcome
        .failure_capture
        .as_ref()
        .and_then(|receipt| receipt.observation.as_ref())
        .and_then(|observation| observation.screenshot.as_ref())
    {
        write_bounded_screenshot(
            output_dir,
            format!("{site}-iteration-{iteration}-failure.png"),
            bytes,
            files,
            omitted,
        )?;
    }
    Ok(())
}

fn write_bounded_screenshot(
    output_dir: &Path,
    file_name: String,
    bytes: &[u8],
    files: &mut Vec<String>,
    omitted: &mut Vec<String>,
) -> Result<(), io::Error> {
    if bytes.len() > MAX_OBSERVATION_SCREENSHOT_BYTES {
        omitted.push(format!(
            "{file_name}: {} bytes exceeds {}",
            bytes.len(),
            MAX_OBSERVATION_SCREENSHOT_BYTES
        ));
        return Ok(());
    }
    fs::write(output_dir.join(&file_name), bytes)?;
    files.push(file_name);
    Ok(())
}

fn unique_nonce(iteration: usize) -> String {
    let unix_nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .ok()
        .and_then(|duration| u64::try_from(duration.as_nanos()).ok())
        .unwrap_or(0);
    format!("{}-{iteration}-{unix_nanos}", std_process::id())
}

fn optional_env(name: &str) -> Option<String> {
    env::var(name).ok().filter(|value| !value.trim().is_empty())
}

fn write_report(output_dir: &Path, report: &RunReport) -> Result<(), io::Error> {
    fs::write(
        output_dir.join("live-until.json"),
        serde_json::to_vec_pretty(report).map_err(io::Error::other)?,
    )
}
