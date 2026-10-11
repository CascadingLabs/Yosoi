use std::{
    sync::{Arc, Weak, atomic::Ordering},
    time::Duration,
};

use crate::internal::browser as provider;
use tokio::{
    sync::{mpsc, oneshot},
    time::Instant,
};
use tokio_util::sync::CancellationToken;

use crate::internal::web_capture as yosoi;

use super::super::tab::NavigationTabParts;
use super::{BrowserNavigationCommand, SchedulerInner, handle::ReadinessSignal};

mod admission;

use admission::{release_active, remove_queued, wait_for_admission};

use super::progress::{
    ProgressEmitter, elapsed, finish_before_start, finish_started, internal_failure,
    leaves_page_uncertain, map_loss, map_provider_progress, map_termination, nonzero_usize,
    provider_failure,
};

pub(super) struct NavigationJob {
    pub(super) request: yosoi::BrowserNavigationRequest,
    pub(super) command: BrowserNavigationCommand,
    pub(super) tab: NavigationTabParts,
    pub(super) runtime_tab: super::super::RuntimeBrowserTabLease,
    pub(super) ticket: u64,
    pub(super) submitted: Instant,
    pub(super) caller_cancellation: CancellationToken,
    pub(super) handle_cancellation: CancellationToken,
    pub(super) progress_sender: mpsc::Sender<yosoi::BrowserNavigationProgressReceipt>,
    pub(super) readiness_sender: Option<oneshot::Sender<ReadinessSignal>>,
    pub(super) terminal_sender: Option<oneshot::Sender<yosoi::BrowserNavigationTerminalReceipt>>,
}

pub(super) struct JobCountGuard(Weak<SchedulerInner>);

impl JobCountGuard {
    pub(super) const fn new(inner: Weak<SchedulerInner>) -> Self {
        Self(inner)
    }
}

impl Drop for JobCountGuard {
    fn drop(&mut self) {
        let Some(inner) = self.0.upgrade() else {
            return;
        };
        let _ = inner
            .jobs
            .try_update(Ordering::AcqRel, Ordering::Acquire, |jobs| {
                jobs.checked_sub(1)
            });
        inner.jobs_changed.notify_waiters();
    }
}

#[allow(
    clippy::cognitive_complexity,
    clippy::significant_drop_tightening,
    reason = "one explicit navigation state machine owns admission, progress, cancellation, terminal receipt, and tab retirement; the per-tab guard spans provider navigation and is released before retirement"
)]
pub(super) async fn run_navigation_job(
    inner: Arc<SchedulerInner>,
    mut job: NavigationJob,
    _job_count: JobCountGuard,
) {
    let submitted = job.submitted;
    let tab_id = job_tab_id(&job);
    let admission = wait_for_admission(&inner, &job, submitted).await;
    if let Err(outcome) = admission {
        remove_queued(&inner, job.ticket).await;
        finish_before_start(job, submitted, outcome);
        return;
    }
    if job.runtime_tab.authorize_profile_admission().is_err() {
        release_active(&inner, tab_id).await;
        finish_before_start(
            job,
            submitted,
            yosoi::BrowserNavigationOutcome::ManagerShutdown,
        );
        return;
    }
    let gate = Arc::clone(&job.tab.gate);
    let tab_guard = tokio::select! {
        biased;
        () = inner.closing.cancelled() => Err(yosoi::BrowserNavigationOutcome::ManagerShutdown),
        () = inner.manager.inner.closing.cancelled() => Err(yosoi::BrowserNavigationOutcome::ManagerShutdown),
        () = job.tab.closing.cancelled() => Err(yosoi::BrowserNavigationOutcome::TabClosed),
        () = job.caller_cancellation.cancelled() => Err(yosoi::BrowserNavigationOutcome::CancelledBeforeAdmission),
        () = job.handle_cancellation.cancelled() => Err(yosoi::BrowserNavigationOutcome::CancelledBeforeAdmission),
        guard = gate.lock_owned() => Ok(guard),
    };
    let tab_guard = match tab_guard {
        Ok(guard) => guard,
        Err(outcome) => {
            finish_before_start(job, submitted, outcome);
            release_active(&inner, tab_id).await;
            return;
        }
    };
    if job.runtime_tab.authorize_profile_admission().is_err() {
        drop(tab_guard);
        release_active(&inner, tab_id).await;
        finish_before_start(
            job,
            submitted,
            yosoi::BrowserNavigationOutcome::ManagerShutdown,
        );
        return;
    }
    let queue_wait = elapsed(submitted);
    let started = Instant::now();
    let Some(options) = navigation_options(&inner) else {
        finish_started(job, queue_wait, started, provider_failure(), false);
        drop(tab_guard);
        release_active(&inner, tab_id).await;
        return;
    };
    let active_navigation = match job
        .tab
        .page
        .start_navigation(job.command.target().as_str(), options)
        .await
    {
        Ok(active) => active,
        Err(error) => {
            let (outcome, retire) = match error {
                provider::VoidCrawlError::NavigationSetupDeadline => {
                    (yosoi::BrowserNavigationOutcome::DeadlineReached, true)
                }
                provider::VoidCrawlError::NavigationAlreadyActive
                | provider::VoidCrawlError::NavigationStateUncertain => (internal_failure(), true),
                _ => (provider_failure(), false),
            };
            drop(tab_guard);
            let cleanup_complete = if retire {
                job.runtime_tab.close().await.is_ok()
            } else {
                true
            };
            release_active(&inner, tab_id).await;
            finish_started(job, queue_wait, started, outcome, cleanup_complete);
            return;
        }
    };
    let mut emitter = ProgressEmitter::new(
        job.request.clone(),
        job.command.readiness(),
        job.progress_sender.clone(),
        job.readiness_sender.take(),
    );
    let (report, override_outcome) =
        drive_active_navigation(&inner, &job, active_navigation, &mut emitter).await;
    let mut resolution = resolve_navigation(report, override_outcome);
    if resolution.outcome == yosoi::BrowserNavigationOutcome::Completed
        && job.command.readiness()
            == yosoi::BrowserNavigationReadinessCheckpoint::ControllerCompleted
    {
        emitter.emit(
            yosoi::BrowserNavigationProgressKind::ControllerCompleted,
            elapsed(started),
        );
    }
    drop(tab_guard);
    if resolution.retire_tab {
        resolution.cleanup_complete = job.runtime_tab.close().await.is_ok();
    }
    release_active(&inner, tab_id).await;
    emitter.finish_readiness(resolution.outcome);
    let receipt = yosoi::BrowserNavigationTerminalReceipt::new(
        &job.request,
        resolution.outcome,
        emitter.reached(),
        emitter.accounting(),
        resolution.engine_loss,
        resolution.provider_loss,
        queue_wait,
        elapsed(started),
        resolution.cleanup_complete,
        resolution.same_document,
    );
    if let Some(sender) = job.terminal_sender.take() {
        let _ = sender.send(receipt);
    }
}

fn navigation_options(inner: &SchedulerInner) -> Option<provider::ActiveNavigationOptions> {
    let progress_capacity = nonzero_usize(inner.limits.engine_progress_capacity().get())?;
    let provider_capacity = nonzero_usize(inner.limits.provider_event_capacity().get())?;
    Some(
        provider::ActiveNavigationOptions::new(
            progress_capacity,
            Duration::from_millis(inner.limits.navigation_deadline().milliseconds()),
        )
        .with_provider_event_capacity(provider_capacity)
        .with_cleanup_timeout(Duration::from_millis(
            inner.manager.limits().cleanup_deadline().milliseconds(),
        )),
    )
}

struct NavigationResolution {
    outcome: yosoi::BrowserNavigationOutcome,
    engine_loss: yosoi::LossExtent,
    provider_loss: yosoi::LossExtent,
    cleanup_complete: bool,
    same_document: bool,
    retire_tab: bool,
}

fn resolve_navigation(
    report: Result<provider::NavigationReport, yosoi::BrowserNavigationOutcome>,
    override_outcome: Option<yosoi::BrowserNavigationOutcome>,
) -> NavigationResolution {
    match report {
        Ok(report) => {
            let provider_outcome = map_termination(report.termination);
            let outcome = if matches!(
                report.termination,
                provider::NavigationTermination::Cancelled
            ) {
                override_outcome.unwrap_or(provider_outcome)
            } else {
                provider_outcome
            };
            NavigationResolution {
                outcome,
                engine_loss: map_loss(report.progress.dropped),
                provider_loss: map_loss(report.provider_events_dropped),
                cleanup_complete: report.cleanup_complete,
                same_document: report.same_document,
                retire_tab: !report.cleanup_complete || leaves_page_uncertain(outcome),
            }
        }
        Err(outcome) => NavigationResolution {
            outcome: override_outcome.unwrap_or(outcome),
            engine_loss: yosoi::LossExtent::Unknown,
            provider_loss: yosoi::LossExtent::Unknown,
            cleanup_complete: false,
            same_document: false,
            retire_tab: true,
        },
    }
}

const fn job_tab_id(job: &NavigationJob) -> yosoi::BrowserTabLeaseId {
    job.request.tab().tab()
}

async fn drive_active_navigation(
    inner: &Arc<SchedulerInner>,
    job: &NavigationJob,
    mut active: provider::ActiveNavigation,
    emitter: &mut ProgressEmitter,
) -> (
    Result<provider::NavigationReport, yosoi::BrowserNavigationOutcome>,
    Option<yosoi::BrowserNavigationOutcome>,
) {
    loop {
        enum Event {
            Progress(Option<provider::NavigationProgress>),
            Stop(yosoi::BrowserNavigationOutcome),
        }
        let event = tokio::select! {
            biased;
            () = inner.closing.cancelled() => Event::Stop(yosoi::BrowserNavigationOutcome::ManagerShutdown),
            () = inner.manager.inner.closing.cancelled() => Event::Stop(yosoi::BrowserNavigationOutcome::ManagerShutdown),
            () = job.tab.closing.cancelled() => Event::Stop(yosoi::BrowserNavigationOutcome::TabClosed),
            () = job.caller_cancellation.cancelled() => Event::Stop(yosoi::BrowserNavigationOutcome::CancelledDuringNavigation),
            () = job.handle_cancellation.cancelled() => Event::Stop(yosoi::BrowserNavigationOutcome::CancelledDuringNavigation),
            progress = active.next_progress() => match progress {
                Ok(progress) => Event::Progress(progress),
                Err(_) => return (Err(provider_failure()), None),
            },
        };
        match event {
            Event::Progress(Some(progress)) => emitter.emit(
                map_provider_progress(progress.kind),
                yosoi::CaptureDuration::from_microseconds(progress.offset_micros),
            ),
            Event::Progress(None) => {
                return (active.wait().await.map_err(|_| provider_failure()), None);
            }
            Event::Stop(outcome) => {
                return (
                    active.cancel().await.map_err(|_| provider_failure()),
                    Some(outcome),
                );
            }
        }
    }
}
