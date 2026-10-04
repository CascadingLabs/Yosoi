//! Loopback-only active-navigation profile driver.
//!
//! This emits measurements; it does not make a speed claim. One warm
//! `BrowserSession` and its requested tabs are reused for every iteration.

use std::{
    env,
    num::NonZeroUsize,
    result::Result as StdResult,
    time::{Duration, Instant},
};

use anyhow::{Context, Result, bail};
use futures_util::future::join_all;
use serde::Serialize;
use void_crawl_core::{
    ActiveNavigationOptions, BrowserSession, MeasuredCount, MeasurementUnavailableReason,
    NavigationProgressAccounting, NavigationTermination, Page,
};
use yosoi_benchmarks::browser_support::{ArtifactSet, LoopbackFixture};

const NAVIGATION_TIMEOUT: Duration = Duration::from_secs(30);

#[derive(Clone, Copy)]
enum Mode {
    Direct,
    Observed,
}

impl Mode {
    fn parse(value: &str) -> Result<Self> {
        match value {
            "direct" => Ok(Self::Direct),
            "observed" => Ok(Self::Observed),
            _ => bail!("--mode must be direct or observed"),
        }
    }

    const fn label(self) -> &'static str {
        match self {
            Self::Direct => "direct",
            Self::Observed => "observed",
        }
    }
}

#[derive(Clone, Copy)]
struct Options {
    tabs: NonZeroUsize,
    iterations: NonZeroUsize,
    progress_capacity: NonZeroUsize,
    provider_event_capacity: NonZeroUsize,
    mode: Mode,
}

impl Options {
    fn parse() -> Result<Self> {
        let mut options = Self {
            tabs: nonzero(1, "tabs")?,
            iterations: nonzero(1, "iterations")?,
            progress_capacity: nonzero(64, "progress-capacity")?,
            provider_event_capacity: nonzero(64, "provider-event-capacity")?,
            mode: Mode::Direct,
        };
        let mut arguments = env::args().skip(1);
        while let Some(argument) = arguments.next() {
            let value = arguments
                .next()
                .with_context(|| format!("{argument} requires a value"))?;
            match argument.as_str() {
                "--tabs" => options.tabs = parse_nonzero(&value, "tabs")?,
                "--iterations" => options.iterations = parse_nonzero(&value, "iterations")?,
                "--progress-capacity" => {
                    options.progress_capacity = parse_nonzero(&value, "progress-capacity")?;
                }
                "--provider-event-capacity" => {
                    options.provider_event_capacity =
                        parse_nonzero(&value, "provider-event-capacity")?;
                }
                "--mode" => options.mode = Mode::parse(&value)?,
                _ => bail!(
                    "usage: profile_active_navigation --tabs N --iterations N --mode direct|observed [--progress-capacity N] [--provider-event-capacity N]"
                ),
            }
        }
        Ok(options)
    }
}

fn nonzero(value: usize, name: &str) -> Result<NonZeroUsize> {
    NonZeroUsize::new(value).with_context(|| format!("{name} must be positive"))
}

fn parse_nonzero(value: &str, name: &str) -> Result<NonZeroUsize> {
    let parsed = value
        .parse::<usize>()
        .with_context(|| format!("{name} must be a positive integer"))?;
    nonzero(parsed, name)
}

#[derive(Serialize)]
struct CountRecord {
    status: &'static str,
    value: Option<u64>,
    unavailable_reason: Option<&'static str>,
}

impl From<MeasuredCount> for CountRecord {
    fn from(count: MeasuredCount) -> Self {
        match count {
            MeasuredCount::Known { value } => Self {
                status: "known",
                value: Some(value),
                unavailable_reason: None,
            },
            MeasuredCount::Unavailable { reason } => Self {
                status: "unavailable",
                value: None,
                unavailable_reason: Some(match reason {
                    MeasurementUnavailableReason::NotCollected => "not_collected",
                    MeasurementUnavailableReason::ProviderDidNotReport => "provider_did_not_report",
                }),
            },
        }
    }
}

impl CountRecord {
    fn measured(&self) -> MeasuredCount {
        match (self.value, self.unavailable_reason) {
            (Some(value), _) => MeasuredCount::Known { value },
            (None, Some("not_collected")) => MeasuredCount::Unavailable {
                reason: MeasurementUnavailableReason::NotCollected,
            },
            _ => MeasuredCount::Unavailable {
                reason: MeasurementUnavailableReason::ProviderDidNotReport,
            },
        }
    }
}

#[derive(Serialize)]
struct ProgressAccountingRecord {
    admitted: CountRecord,
    retained: CountRecord,
    dropped: CountRecord,
}

impl From<NavigationProgressAccounting> for ProgressAccountingRecord {
    fn from(accounting: NavigationProgressAccounting) -> Self {
        Self {
            admitted: accounting.admitted.into(),
            retained: accounting.retained.into(),
            dropped: accounting.dropped.into(),
        }
    }
}

#[derive(Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
enum LossAccountingRecord {
    NotObserved,
    Observed {
        progress: ProgressAccountingRecord,
        provider_events_dropped: CountRecord,
    },
}

#[derive(Serialize)]
struct AttemptRecord {
    record: &'static str,
    mode: &'static str,
    iteration: usize,
    tab: usize,
    elapsed_micros: u128,
    terminal: &'static str,
    loss_accounting: LossAccountingRecord,
}

#[derive(Default)]
struct CountTotals {
    known_total: u64,
    unavailable_attempts: u64,
}

impl CountTotals {
    fn record(&mut self, count: MeasuredCount) -> Result<()> {
        match count {
            MeasuredCount::Known { value } => {
                self.known_total = self
                    .known_total
                    .checked_add(value)
                    .context("loss total overflow")?;
            }
            MeasuredCount::Unavailable { .. } => {
                self.unavailable_attempts = self
                    .unavailable_attempts
                    .checked_add(1)
                    .context("unavailable loss count overflow")?;
            }
        }
        Ok(())
    }
}

#[derive(Serialize)]
struct SummaryRecord {
    record: &'static str,
    mode: &'static str,
    tabs: usize,
    iterations: usize,
    progress_capacity: usize,
    provider_event_capacity: usize,
    attempts: u64,
    elapsed_micros_total: u128,
    batch_elapsed_micros_total: u128,
    observed_attempts: u64,
    progress_events_dropped_known_total: u64,
    progress_events_dropped_unavailable_attempts: u64,
    provider_events_dropped_known_total: u64,
    provider_events_dropped_unavailable_attempts: u64,
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<()> {
    let options = Options::parse()?;
    let fixture = LoopbackFixture::start(ArtifactSet::Minimal).await?;
    let target = fixture.url();
    let session = BrowserSession::launch_headless()
        .await
        .context("launch warm browser session")?;
    let result = run(&session, &target, options).await;
    let close_result = session.close().await.context("close warm browser session");
    result?;
    close_result
}

async fn run(session: &BrowserSession, target: &str, options: Options) -> Result<()> {
    let mut pages = Vec::<Page>::new();
    for _ in 0..options.tabs.get() {
        pages.push(session.new_blank_page().await.context("create warm tab")?);
    }

    let mut attempts = 0_u64;
    let mut elapsed_micros_total = 0_u128;
    let mut batch_elapsed_micros_total = 0_u128;
    let mut observed_attempts = 0_u64;
    let mut progress_dropped = CountTotals::default();
    let mut provider_dropped = CountTotals::default();

    for iteration in 0..options.iterations.get() {
        let batch_started = Instant::now();
        let outcomes = match options.mode {
            Mode::Direct => direct_batch(&pages, target).await?,
            Mode::Observed => observed_batch(&pages, target, options).await?,
        };
        batch_elapsed_micros_total = batch_elapsed_micros_total
            .checked_add(batch_started.elapsed().as_micros())
            .context("batch elapsed microseconds overflow")?;
        for (tab, outcome) in outcomes.into_iter().enumerate() {
            if let LossAccountingRecord::Observed {
                progress,
                provider_events_dropped,
            } = &outcome.loss_accounting
            {
                observed_attempts = observed_attempts
                    .checked_add(1)
                    .context("observed attempt count overflow")?;
                progress_dropped.record(progress.dropped.measured())?;
                provider_dropped.record(provider_events_dropped.measured())?;
            }
            attempts = attempts.checked_add(1).context("attempt count overflow")?;
            elapsed_micros_total = elapsed_micros_total
                .checked_add(outcome.elapsed_micros)
                .context("elapsed microseconds overflow")?;
            println!(
                "{}",
                serde_json::to_string(&AttemptRecord {
                    record: "attempt",
                    mode: options.mode.label(),
                    iteration,
                    tab,
                    elapsed_micros: outcome.elapsed_micros,
                    terminal: outcome.terminal,
                    loss_accounting: outcome.loss_accounting,
                })?
            );
        }
    }

    println!(
        "{}",
        serde_json::to_string(&SummaryRecord {
            record: "summary",
            mode: options.mode.label(),
            tabs: options.tabs.get(),
            iterations: options.iterations.get(),
            progress_capacity: options.progress_capacity.get(),
            provider_event_capacity: options.provider_event_capacity.get(),
            attempts,
            elapsed_micros_total,
            batch_elapsed_micros_total,
            observed_attempts,
            progress_events_dropped_known_total: progress_dropped.known_total,
            progress_events_dropped_unavailable_attempts: progress_dropped.unavailable_attempts,
            provider_events_dropped_known_total: provider_dropped.known_total,
            provider_events_dropped_unavailable_attempts: provider_dropped.unavailable_attempts,
        })?
    );
    Ok(())
}

struct AttemptOutcome {
    elapsed_micros: u128,
    terminal: &'static str,
    loss_accounting: LossAccountingRecord,
}

async fn direct_batch(pages: &[Page], target: &str) -> Result<Vec<AttemptOutcome>> {
    let outcomes = join_all(pages.iter().map(|page| async move {
        let started = Instant::now();
        page.navigate(target).await?;
        Ok::<_, void_crawl_core::VoidCrawlError>(AttemptOutcome {
            elapsed_micros: started.elapsed().as_micros(),
            terminal: "navigation_completed",
            loss_accounting: LossAccountingRecord::NotObserved,
        })
    }))
    .await;
    outcomes
        .into_iter()
        .map(|outcome| outcome.context("direct page navigation"))
        .collect()
}

async fn observed_batch(
    pages: &[Page],
    target: &str,
    options: Options,
) -> Result<Vec<AttemptOutcome>> {
    let navigation_options =
        ActiveNavigationOptions::new(options.progress_capacity, NAVIGATION_TIMEOUT)
            .with_provider_event_capacity(options.provider_event_capacity);
    let started = Instant::now();
    let starts = join_all(
        pages
            .iter()
            .map(|page| page.start_navigation(target, navigation_options)),
    )
    .await;
    let navigations = starts
        .into_iter()
        .collect::<StdResult<Vec<_>, _>>()
        .context("start observed navigation batch")?;
    let reports = join_all(navigations.into_iter().map(|navigation| async {
        let report = navigation.wait().await;
        (report, started.elapsed().as_micros())
    }))
    .await;
    reports
        .into_iter()
        .map(|(report, elapsed_micros)| {
            let report = report.context("wait for observed navigation")?;
            if report.termination != NavigationTermination::Completed {
                bail!(
                    "observed navigation did not complete: {:?}",
                    report.termination
                );
            }
            Ok(AttemptOutcome {
                elapsed_micros,
                terminal: "completed",
                loss_accounting: LossAccountingRecord::Observed {
                    progress: report.progress.into(),
                    provider_events_dropped: report.provider_events_dropped.into(),
                },
            })
        })
        .collect()
}
