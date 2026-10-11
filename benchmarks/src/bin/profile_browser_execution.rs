//! Loopback-only CAS-352 warm-browser capacity and soak driver.

use anyhow::{Context, Result, bail};
use serde::Serialize;
use std::{env, num::NonZeroU32, time::Instant};
use tokio::task::JoinSet;
use tokio_util::sync::CancellationToken;
use yosoi_benchmarks::browser_support::{self, ArtifactSet, BrowserRunMode, LoopbackFixture};
use yosoi_dev_support::internal::web_capture::{
    BrowserExecutionManager, BrowserExecutionManagerConfig, capture_attempt_managed,
};

#[derive(Clone, Copy)]
struct Options {
    iterations: NonZeroU32,
    concurrency: NonZeroU32,
    processes: NonZeroU32,
    contexts_total: NonZeroU32,
    contexts_per_process: NonZeroU32,
    tabs_total: NonZeroU32,
    queue_depth: NonZeroU32,
    recycle_threshold: NonZeroU32,
}

impl Options {
    fn parse() -> Result<Self> {
        let mut options = Self {
            iterations: nonzero(10, "iterations")?,
            concurrency: nonzero(2, "concurrency")?,
            processes: NonZeroU32::MIN,
            contexts_total: nonzero(2, "contexts-total")?,
            contexts_per_process: nonzero(2, "contexts-per-process")?,
            tabs_total: nonzero(2, "tabs-total")?,
            queue_depth: nonzero(4, "queue-depth")?,
            recycle_threshold: nonzero(100, "recycle-threshold")?,
        };
        let mut arguments = env::args().skip(1);
        while let Some(argument) = arguments.next() {
            let value = arguments.next().context("missing option value")?;
            let parsed = value.parse::<u32>().context("option must be an integer")?;
            let value = nonzero(parsed, "browser execution option")?;
            match argument.as_str() {
                "--iterations" => options.iterations = value,
                "--concurrency" => options.concurrency = value,
                "--processes" => options.processes = value,
                "--contexts-total" => options.contexts_total = value,
                "--contexts-per-process" => options.contexts_per_process = value,
                "--tabs-total" => options.tabs_total = value,
                "--queue-depth" => options.queue_depth = value,
                "--recycle-threshold" => options.recycle_threshold = value,
                _ => bail!(
                    "usage: profile_browser_execution [--iterations N] [--concurrency N] [--processes N] [--contexts-total N] [--contexts-per-process N] [--tabs-total N] [--queue-depth N] [--recycle-threshold N]"
                ),
            }
        }
        Ok(options)
    }
}

fn nonzero(value: u32, name: &str) -> Result<NonZeroU32> {
    NonZeroU32::new(value).with_context(|| format!("{name} must be positive"))
}

#[derive(Serialize)]
struct AttemptRecord {
    record: &'static str,
    iteration: u32,
    manager_id: String,
    process_generation: u64,
    execution_id: String,
    elapsed_micros: u128,
}

#[derive(Serialize)]
struct SummaryRecord {
    record: &'static str,
    manager_id: String,
    iterations: u32,
    concurrency: u32,
    processes: u32,
    contexts_total: u32,
    contexts_per_process: u32,
    tabs_total: u32,
    queue_depth: u32,
    recycle_threshold: u32,
    attempts: u64,
    distinct_generations: Vec<u64>,
    residual_processes_before_shutdown: u32,
    residual_contexts_before_shutdown: u32,
    residual_tabs_before_shutdown: u32,
    residual_processes_after_shutdown: u32,
    residual_contexts_after_shutdown: u32,
    residual_tabs_after_shutdown: u32,
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<()> {
    let options = Options::parse()?;
    let limits = browser_support::execution_limits(
        options.processes,
        options.contexts_total,
        options.contexts_per_process,
        options.tabs_total,
        options.queue_depth,
        options.recycle_threshold,
    )?;
    let manager = BrowserExecutionManager::new(limits, BrowserExecutionManagerConfig::default());
    let manager_id = manager.id().to_string();
    let fixture = LoopbackFixture::start(ArtifactSet::Minimal).await?;
    let target = fixture.url();
    let mut attempts = 0_u64;
    let mut generations = Vec::new();

    for iteration in 0..options.iterations.get() {
        let mut tasks = JoinSet::new();
        for _ in 0..options.concurrency.get() {
            let task_manager = manager.clone();
            let task_target = target.clone();
            tasks.spawn(async move {
                let spec = browser_support::spec(
                    &task_target,
                    ArtifactSet::Minimal,
                    BrowserRunMode::Headless,
                )?;
                let started = Instant::now();
                let result =
                    capture_attempt_managed(&task_manager, &spec, &CancellationToken::new())
                        .await
                        .context("managed soak capture")?;
                if !result.is_ready() {
                    bail!("managed soak capture stopped before finalization readiness");
                }
                let receipt = result
                    .execution()
                    .context("managed soak capture omitted execution receipt")?;
                Ok::<_, anyhow::Error>((
                    receipt
                        .terminal()
                        .admission()
                        .execution()
                        .process()
                        .generation()
                        .get(),
                    receipt
                        .terminal()
                        .admission()
                        .execution()
                        .execution()
                        .to_string(),
                    started.elapsed().as_micros(),
                ))
            });
        }
        while let Some(joined) = tasks.join_next().await {
            let (generation, execution_id, elapsed_micros) =
                joined.context("soak task panicked")??;
            attempts = attempts.checked_add(1).context("attempt count overflow")?;
            if !generations.contains(&generation) {
                generations.push(generation);
            }
            println!(
                "{}",
                serde_json::to_string(&AttemptRecord {
                    record: "attempt",
                    iteration,
                    manager_id: manager_id.clone(),
                    process_generation: generation,
                    execution_id,
                    elapsed_micros,
                })?
            );
        }
    }

    generations.sort_unstable();
    let before = manager.snapshot().await?;
    manager.shutdown().await?;
    let after = manager.snapshot().await?;
    println!(
        "{}",
        serde_json::to_string(&SummaryRecord {
            record: "summary",
            manager_id,
            iterations: options.iterations.get(),
            concurrency: options.concurrency.get(),
            processes: options.processes.get(),
            contexts_total: options.contexts_total.get(),
            contexts_per_process: options.contexts_per_process.get(),
            tabs_total: options.tabs_total.get(),
            queue_depth: options.queue_depth.get(),
            recycle_threshold: options.recycle_threshold.get(),
            attempts,
            distinct_generations: generations,
            residual_processes_before_shutdown: before.active_processes,
            residual_contexts_before_shutdown: before.active_contexts,
            residual_tabs_before_shutdown: before.active_tabs,
            residual_processes_after_shutdown: after.active_processes,
            residual_contexts_after_shutdown: after.active_contexts,
            residual_tabs_after_shutdown: after.active_tabs,
        })?
    );
    Ok(())
}
