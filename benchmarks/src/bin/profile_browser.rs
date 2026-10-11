//! Bounded CAS-333 loopback browser-attempt driver.
//!
//! The process sampler owns `/proc` collection. This driver emits only attempt
//! state and timing, never command lines or provider arguments.

use anyhow::{Context, Result, bail};
use chrono::Utc;
use serde::Serialize;
use std::{
    env,
    num::NonZeroU32,
    sync::{Arc, Mutex},
    time::{Duration, Instant, SystemTime},
};
use tokio_util::sync::CancellationToken;
use yosoi_benchmarks::browser_support::{
    self, ArtifactSet, BrowserRunMode, LoopbackFixture, LoopbackResponseMode,
};
use yosoi_dev_support::internal::web_capture::capture_attempt;
use yosoi_dev_support::internal::web_capture::{
    BrowserFinalizationInput, Observation, VoidCrawlAdapterError, finalize_browser_capture,
};

const DELAYED_RESPONSE: Duration = Duration::from_secs(60);

#[derive(Clone, Copy)]
enum Workload {
    Success,
    Cancellation,
    Deadline,
    Failure,
}
impl Workload {
    fn parse(value: &str) -> Result<Self> {
        match value {
            "success" => Ok(Self::Success),
            "cancellation" => Ok(Self::Cancellation),
            "deadline" => Ok(Self::Deadline),
            "failure" => Ok(Self::Failure),
            _ => bail!("workload must be success, cancellation, deadline, or failure"),
        }
    }
    const fn name(self) -> &'static str {
        match self {
            Self::Success => "success",
            Self::Cancellation => "cancellation",
            Self::Deadline => "deadline",
            Self::Failure => "failure",
        }
    }
    const fn response_mode(self) -> LoopbackResponseMode {
        match self {
            Self::Success => LoopbackResponseMode::Immediate,
            Self::Cancellation | Self::Deadline => LoopbackResponseMode::Delayed(DELAYED_RESPONSE),
            Self::Failure => LoopbackResponseMode::PartialDisconnect,
        }
    }
}

#[derive(Serialize)]
struct AttemptRecord {
    mode: &'static str,
    artifact_set: &'static str,
    workload: &'static str,
    adapter_state: Option<String>,
    terminal: Option<String>,
    cleanup_state: Option<String>,
    finalization: String,
    completeness: Option<String>,
    elapsed_ms: u128,
    cancellation_requested_after_ms: Option<u128>,
    cancellation_to_return_ms: Option<u128>,
    bounded_deadline_before_staging: bool,
    unavailable_metrics: Vec<&'static str>,
}
impl AttemptRecord {
    fn is_expected(&self) -> bool {
        if self.workload == "deadline"
            && self.adapter_state.is_none()
            && self.terminal.is_none()
            && self.cleanup_state.is_none()
            && self.bounded_deadline_before_staging
        {
            return true;
        }
        if self.finalization != "ok" || self.cleanup_state.as_deref() != Some("Complete") {
            return false;
        }
        match self.workload {
            "success" => {
                self.adapter_state.as_deref() == Some("ReadyForFinalization")
                    && self
                        .terminal
                        .as_deref()
                        .is_some_and(|value| value.contains("ControllerCompleted"))
                    && self.completeness.as_deref() == Some("Complete")
            }
            "cancellation" => {
                self.adapter_state.as_deref() == Some("Stopped")
                    && self
                        .terminal
                        .as_deref()
                        .is_some_and(|value| value.contains("CallerCancelled"))
                    && self.cancellation_to_return_ms.is_some()
            }
            "deadline" => {
                self.adapter_state.as_deref() == Some("Stopped")
                    && self
                        .terminal
                        .as_deref()
                        .is_some_and(|value| value.contains("DeadlineReached"))
            }
            "failure" => {
                self.adapter_state.as_deref() == Some("Stopped")
                    && self.terminal.as_deref().is_some_and(|value| {
                        value.contains("ProviderStopped") || value.contains("DeadlineReached")
                    })
            }
            _ => false,
        }
    }
}

#[allow(
    clippy::too_many_arguments,
    reason = "profile record keeps every workload dimension and cancellation signal explicit"
)]
async fn run_attempt(
    mode: BrowserRunMode,
    environment_label: &'static str,
    artifacts: ArtifactSet,
    workload: Workload,
    target: String,
    deadline_ms: u64,
    cancellation: CancellationToken,
    cancellation_at: Arc<Mutex<Option<Instant>>>,
) -> AttemptRecord {
    let started = Instant::now();
    let attempt_spec =
        match browser_support::spec_with_deadline(&target, artifacts, mode, deadline_ms) {
            Ok(value) => value,
            Err(error) => {
                return AttemptRecord {
                    mode: environment_label,
                    artifact_set: artifacts.label(),
                    workload: workload.name(),
                    adapter_state: None,
                    terminal: None,
                    cleanup_state: None,
                    finalization: format!("spec_error: {error}"),
                    completeness: None,
                    elapsed_ms: started.elapsed().as_millis(),
                    cancellation_requested_after_ms: None,
                    cancellation_to_return_ms: None,
                    bounded_deadline_before_staging: false,
                    unavailable_metrics: vec![
                        "adapter result unavailable because specification construction failed",
                    ],
                };
            }
        };
    let result = capture_attempt(&attempt_spec, &cancellation).await;
    let wall_finished = chrono::DateTime::<Utc>::from(SystemTime::now());
    let elapsed_ms = started.elapsed().as_millis();
    let requested = cancellation_at
        .lock()
        .ok()
        .and_then(|value| *value)
        .map(|at| at.duration_since(started).as_millis());
    match result {
        Ok(result) => {
            let adapter_state = Some(format!("{:?}", result.state()));
            let terminal = Some(format!("{:?}", result.terminal().kind()));
            let cleanup_state = Some(format!("{:?}", result.facts().cleanup()));
            let (finalization, completeness) = match finalize_browser_capture(
                result,
                BrowserFinalizationInput {
                    finished_at: wall_finished,
                    resource_origin: Observation::Unobserved,
                    initiator_origin: Observation::Unobserved,
                },
            ) {
                Ok(bundle) => (
                    "ok".to_owned(),
                    Some(format!("{:?}", bundle.capture().completeness())),
                ),
                Err(error) => (format!("error: {error}"), None),
            };
            AttemptRecord {
                mode: environment_label,
                artifact_set: artifacts.label(),
                workload: workload.name(),
                adapter_state,
                terminal,
                cleanup_state,
                finalization,
                completeness,
                elapsed_ms,
                cancellation_requested_after_ms: requested,
                cancellation_to_return_ms: requested.map(|at| elapsed_ms.saturating_sub(at)),
                bounded_deadline_before_staging: false,
                unavailable_metrics: vec![
                    "close_latency_ms: unavailable; adapter reports cleanup state but no close timestamp",
                ],
            }
        }
        Err(error) => {
            let bounded_deadline_before_staging = matches!(
                &error,
                VoidCrawlAdapterError::DeadlineBeforeOwnership
                    | VoidCrawlAdapterError::DeadlineBeforeStaging
            );
            AttemptRecord {
                mode: environment_label,
                artifact_set: artifacts.label(),
                workload: workload.name(),
                adapter_state: None,
                terminal: None,
                cleanup_state: None,
                finalization: format!("adapter_error: {error}"),
                completeness: None,
                elapsed_ms,
                cancellation_requested_after_ms: requested,
                cancellation_to_return_ms: requested.map(|at| elapsed_ms.saturating_sub(at)),
                bounded_deadline_before_staging,
                unavailable_metrics: vec![
                    "terminal, cleanup, and completeness unavailable because adapter did not return a result",
                    "close_latency_ms: unavailable; adapter reports cleanup state but no close timestamp",
                ],
            }
        }
    }
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<()> {
    let mut mode = BrowserRunMode::Headless;
    let mut environment_label = None;
    let mut artifacts = ArtifactSet::Minimal;
    let mut workload = Workload::Success;
    let mut iterations = NonZeroU32::new(2).context("default iterations")?;
    let mut concurrency = NonZeroU32::MIN;
    let mut deadline_ms = 5_000_u64;
    let mut arguments = env::args().skip(1);
    while let Some(argument) = arguments.next() {
        let value = arguments.next().context("missing option value")?;
        match argument.as_str() {
            "--mode" => mode = BrowserRunMode::parse_native(&value)?,
            "--environment-label" => {
                environment_label = Some(match value.as_str() {
                    "native-headless" => "native-headless",
                    "native-headful" => "native-headful",
                    "container-headless" => "container-headless",
                    "container-headful" => "container-headful",
                    _ => bail!(
                        "environment label must name a native or container headless/headful environment"
                    ),
                });
            }
            "--artifact-set" => artifacts = ArtifactSet::parse(&value)?,
            "--workload" => workload = Workload::parse(&value)?,
            "--iterations" => {
                iterations = NonZeroU32::new(value.parse().context("invalid iterations")?)
                    .context("iterations must be positive")?;
            }
            "--concurrency" => {
                concurrency = NonZeroU32::new(value.parse().context("invalid concurrency")?)
                    .context("concurrency must be positive")?;
            }
            "--deadline-ms" => deadline_ms = value.parse().context("invalid deadline-ms")?,
            _ => bail!(
                "usage: profile_browser [--mode native-headless|native-headful] [--environment-label native-headless|native-headful|container-headless|container-headful] [--artifact-set minimal|full|growth] [--workload success|cancellation|deadline|failure] [--iterations N] [--concurrency N] [--deadline-ms N]"
            ),
        }
    }
    if !(100..=15_000).contains(&deadline_ms) {
        bail!("deadline-ms must be between 100 and 15000")
    }
    let environment_label = environment_label.unwrap_or_else(|| mode.native_label());
    if !matches!(
        (environment_label, mode),
        (
            "native-headless" | "container-headless",
            BrowserRunMode::Headless
        ) | (
            "native-headful" | "container-headful",
            BrowserRunMode::Headful
        )
    ) {
        bail!("environment label contradicts requested browser mode")
    }
    let server =
        LoopbackFixture::start_with_response_mode(artifacts, workload.response_mode()).await?;
    let loopback_target = server.url();
    for _ in 0..iterations.get() {
        let cancellation = CancellationToken::new();
        let cancellation_at = Arc::new(Mutex::new(None));
        let accepted_before = server.accepted_request_count();
        let concurrent_attempts =
            usize::try_from(concurrency.get()).context("convert concurrency to process count")?;
        let mut tasks = Vec::new();
        for _ in 0..concurrency.get() {
            tasks.push(tokio::spawn(run_attempt(
                mode,
                environment_label,
                artifacts,
                workload,
                loopback_target.clone(),
                deadline_ms,
                cancellation.clone(),
                Arc::clone(&cancellation_at),
            )));
        }
        let mut ownership_timeout = false;
        if matches!(workload, Workload::Cancellation) {
            let expected = accepted_before
                .checked_add(concurrent_attempts)
                .context("accepted request count overflow")?;
            ownership_timeout = !server
                .wait_for_accepted_requests(expected, Duration::from_millis(deadline_ms))
                .await;
            if let Ok(mut value) = cancellation_at.lock() {
                *value = Some(Instant::now());
            }
            cancellation.cancel();
        }
        let mut unexpected = false;
        for task in tasks {
            let record = task.await.context("attempt task panicked")?;
            unexpected |= !record.is_expected();
            println!("{}", serde_json::to_string(&record)?);
        }
        if unexpected {
            bail!("one or more browser profile attempts violated the workload contract")
        }
        if ownership_timeout {
            bail!(
                "cancellation ownership timeout: not all concurrent attempts reached delayed loopback server"
            )
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::AttemptRecord;

    #[test]
    fn deadline_before_browser_ownership_is_a_bounded_expected_outcome() {
        for error in [
            "attempt deadline elapsed before browser ownership was established",
            "attempt deadline elapsed after browser ownership but before factual staging",
        ] {
            let record = AttemptRecord {
                mode: "container-headful",
                artifact_set: "full",
                workload: "deadline",
                adapter_state: None,
                terminal: None,
                cleanup_state: None,
                finalization: format!("adapter_error: {error}"),
                completeness: None,
                elapsed_ms: 5_542,
                cancellation_requested_after_ms: None,
                cancellation_to_return_ms: None,
                bounded_deadline_before_staging: true,
                unavailable_metrics: Vec::new(),
            };

            assert!(record.is_expected());
        }
    }
}
