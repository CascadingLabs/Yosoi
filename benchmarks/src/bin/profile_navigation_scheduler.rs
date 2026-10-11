//! Loopback-only profile driver for the Yosoi tab-navigation scheduler.
//!
//! Runtime flags select the tab count; there is no source-level tab ceiling.

use std::{
    env,
    num::{NonZeroU32, NonZeroU64, NonZeroUsize},
    time::Instant,
};

use anyhow::{Context, Result};
use futures_util::future::join_all;
use serde::Serialize;
use tokio_util::sync::CancellationToken;
use yosoi_benchmarks::browser_support::{ArtifactSet, LoopbackFixture};
use yosoi_dev_support::internal::web_capture::{
    BrowserActiveNavigationLimit, BrowserCleanupDeadline, BrowserContextTotalLimit,
    BrowserContextsPerProcessLimit, BrowserEngineProgressCapacity, BrowserExecutionLimits,
    BrowserExecutionManager, BrowserExecutionManagerConfig, BrowserNavigationCommand,
    BrowserNavigationDeadline, BrowserNavigationHandle, BrowserNavigationOutcome,
    BrowserNavigationProgressCapacity, BrowserNavigationReadinessCheckpoint,
    BrowserNavigationScheduler, BrowserNavigationSchedulerLimits, BrowserProcessLimit,
    BrowserProviderEventCapacity, BrowserQueueDepthLimit, BrowserQueueWaitLimit,
    BrowserRecycleThreshold, BrowserTabTotalLimit, BrowserTabsPerSessionLimit, LossExtent,
    RequestedWebTarget,
};

#[derive(Clone, Copy)]
struct Options {
    tabs: NonZeroU32,
    iterations: NonZeroUsize,
    scheduler_progress_capacity: NonZeroU32,
    engine_progress_capacity: NonZeroU32,
    provider_event_capacity: NonZeroU32,
}

impl Options {
    fn parse() -> Result<Self> {
        let mut options = Self {
            tabs: NonZeroU32::MIN,
            iterations: NonZeroUsize::MIN,
            scheduler_progress_capacity: NonZeroU32::new(64).context("default capacity")?,
            engine_progress_capacity: NonZeroU32::new(64).context("default capacity")?,
            provider_event_capacity: NonZeroU32::new(64).context("default capacity")?,
        };
        let mut arguments = env::args().skip(1);
        while let Some(argument) = arguments.next() {
            let value = arguments
                .next()
                .with_context(|| format!("{argument} requires a value"))?;
            match argument.as_str() {
                "--tabs" => options.tabs = parse_nonzero_u32(&value, "tabs")?,
                "--iterations" => {
                    options.iterations = parse_nonzero_usize(&value, "iterations")?;
                }
                "--scheduler-progress-capacity" => {
                    options.scheduler_progress_capacity =
                        parse_nonzero_u32(&value, "scheduler-progress-capacity")?;
                }
                "--engine-progress-capacity" => {
                    options.engine_progress_capacity =
                        parse_nonzero_u32(&value, "engine-progress-capacity")?;
                }
                "--provider-event-capacity" => {
                    options.provider_event_capacity =
                        parse_nonzero_u32(&value, "provider-event-capacity")?;
                }
                _ => anyhow::bail!(
                    "usage: profile_navigation_scheduler --tabs N --iterations N [--scheduler-progress-capacity N] [--engine-progress-capacity N] [--provider-event-capacity N]"
                ),
            }
        }
        Ok(options)
    }
}

fn parse_nonzero_u32(value: &str, name: &str) -> Result<NonZeroU32> {
    value
        .parse::<u32>()
        .with_context(|| format!("{name} must be a positive integer"))?
        .try_into()
        .with_context(|| format!("{name} must be positive"))
}

fn parse_nonzero_usize(value: &str, name: &str) -> Result<NonZeroUsize> {
    value
        .parse::<usize>()
        .with_context(|| format!("{name} must be a positive integer"))?
        .try_into()
        .with_context(|| format!("{name} must be positive"))
}

#[derive(Serialize)]
struct AttemptRecord {
    record: &'static str,
    iteration: usize,
    tab: usize,
    outcome: &'static str,
    queue_wait_micros: u64,
    execution_micros: u64,
    scheduler_progress_dropped: LossExtent,
    engine_progress_dropped: LossExtent,
    provider_events_dropped: LossExtent,
}

#[derive(Serialize)]
struct SummaryRecord {
    record: &'static str,
    tabs: u32,
    iterations: usize,
    attempts: u64,
    batch_elapsed_micros_total: u128,
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<()> {
    let options = Options::parse()?;
    let fixture = LoopbackFixture::start(ArtifactSet::Minimal).await?;
    let target = RequestedWebTarget::parse(&fixture.url()).context("validate fixture URL")?;
    let scheduler = scheduler(options)?;
    let cancellation = CancellationToken::new();
    let session = scheduler
        .acquire_session(&cancellation)
        .await
        .context("acquire scheduler session")?;
    let mut tabs = vec![session.initial_tab().clone()];
    for _ in 1..options.tabs.get() {
        tabs.push(
            session
                .new_tab(&cancellation)
                .await
                .context("create scheduler tab")?,
        );
    }
    let mut attempts = 0_u64;
    let mut batch_elapsed_micros_total = 0_u128;
    for iteration in 0..options.iterations.get() {
        let batch_started = Instant::now();
        let mut handles = Vec::with_capacity(tabs.len());
        for tab in &tabs {
            handles.push(
                scheduler
                    .schedule(
                        tab,
                        BrowserNavigationCommand::new(
                            target.clone(),
                            BrowserNavigationReadinessCheckpoint::Load,
                        ),
                        &cancellation,
                    )
                    .await
                    .context("schedule navigation")?,
            );
        }
        let receipts = join_all(handles.into_iter().map(BrowserNavigationHandle::wait)).await;
        batch_elapsed_micros_total = batch_elapsed_micros_total
            .checked_add(batch_started.elapsed().as_micros())
            .context("batch elapsed total overflow")?;
        for (tab, receipt) in receipts.into_iter().enumerate() {
            let receipt = receipt.context("wait for navigation")?;
            if receipt.outcome() != BrowserNavigationOutcome::Completed {
                anyhow::bail!(
                    "scheduled navigation did not complete: {:?}",
                    receipt.outcome()
                );
            }
            attempts = attempts.checked_add(1).context("attempt count overflow")?;
            println!(
                "{}",
                serde_json::to_string(&AttemptRecord {
                    record: "attempt",
                    iteration,
                    tab,
                    outcome: "completed",
                    queue_wait_micros: receipt.queue_wait().as_microseconds(),
                    execution_micros: receipt.execution().as_microseconds(),
                    scheduler_progress_dropped: receipt.progress().dropped(),
                    engine_progress_dropped: receipt.engine_progress_dropped(),
                    provider_events_dropped: receipt.provider_events_dropped(),
                })?
            );
        }
    }
    println!(
        "{}",
        serde_json::to_string(&SummaryRecord {
            record: "summary",
            tabs: options.tabs.get(),
            iterations: options.iterations.get(),
            attempts,
            batch_elapsed_micros_total,
        })?
    );
    scheduler.shutdown().await.context("shutdown scheduler")
}

fn scheduler(options: Options) -> Result<BrowserNavigationScheduler> {
    let execution = BrowserExecutionLimits::new(
        BrowserProcessLimit::new(NonZeroU32::MIN),
        BrowserContextTotalLimit::new(NonZeroU32::MIN),
        BrowserContextsPerProcessLimit::new(NonZeroU32::MIN),
        BrowserTabTotalLimit::new(options.tabs),
        BrowserTabsPerSessionLimit::new(options.tabs),
        BrowserQueueDepthLimit::new(options.tabs),
        BrowserQueueWaitLimit::new(NonZeroU64::new(30_000).context("queue wait")?),
        BrowserCleanupDeadline::new(NonZeroU64::new(5_000).context("cleanup deadline")?),
        BrowserRecycleThreshold::new(NonZeroU32::new(100).context("recycle threshold")?),
    )
    .context("validate browser execution limits")?;
    let navigation = BrowserNavigationSchedulerLimits::new(
        BrowserActiveNavigationLimit::new(options.tabs),
        BrowserQueueDepthLimit::new(options.tabs),
        BrowserNavigationProgressCapacity::new(options.scheduler_progress_capacity),
        BrowserEngineProgressCapacity::new(options.engine_progress_capacity),
        BrowserProviderEventCapacity::new(options.provider_event_capacity),
        BrowserNavigationDeadline::new(NonZeroU64::new(30_000).context("navigation deadline")?),
    );
    BrowserNavigationScheduler::new(
        BrowserExecutionManager::new(execution, BrowserExecutionManagerConfig::default()),
        navigation,
    )
    .context("create scheduler")
}
