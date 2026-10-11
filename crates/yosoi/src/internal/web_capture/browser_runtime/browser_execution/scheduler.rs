use std::{
    collections::{HashMap, VecDeque},
    fmt,
    sync::{
        Arc, Weak,
        atomic::{AtomicU32, AtomicU64, Ordering},
    },
};

use thiserror::Error;
use tokio::{
    runtime::Handle,
    sync::{Mutex, Notify, mpsc, oneshot},
    time::Instant,
};
use tokio_util::sync::CancellationToken;

use crate::internal::web_capture as yosoi;

use super::{
    BrowserExecutionManager, BrowserExecutionManagerError, RuntimeBrowserLease,
    RuntimeBrowserTabLease,
};

mod handle;
mod progress;
mod worker;

pub use handle::BrowserNavigationHandle;
use worker::{JobCountGuard, NavigationJob, run_navigation_job};

/// Secret-safe failure from navigation scheduling or delivery.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum BrowserNavigationSchedulerError {
    #[error("navigation scheduler limits exceed browser execution capacity")]
    InvalidLimits,
    #[error("browser execution manager already owns a navigation scheduler")]
    SchedulerAlreadyAttached,
    #[error("navigation scheduler queue is full")]
    QueueFull,
    #[error("navigation scheduler is closing")]
    SchedulerClosing,
    #[error("navigation readiness requires an unsupported CDP domain")]
    UnsupportedReadiness {
        requested: yosoi::BrowserNavigationReadinessCheckpoint,
    },
    #[error("navigation ended before its requested readiness checkpoint")]
    EndedBeforeReadiness {
        outcome: yosoi::BrowserNavigationOutcome,
    },
    #[error("browser tab is no longer leased")]
    TabReleased,
    #[error("browser execution manager is unavailable")]
    ManagerUnavailable,
    #[error("navigation scheduler requires a Tokio runtime")]
    RuntimeUnavailable,
    #[error("navigation scheduler accounting invariant failed")]
    InternalInvariant,
}

/// One validated navigation command. Its URL is intentionally absent from receipts.
#[derive(Clone, Eq, PartialEq)]
pub struct BrowserNavigationCommand {
    target: yosoi::RequestedWebTarget,
    readiness: yosoi::BrowserNavigationReadinessCheckpoint,
}

impl fmt::Debug for BrowserNavigationCommand {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("BrowserNavigationCommand")
            .field("target", &"<redacted>")
            .field("readiness", &self.readiness)
            .finish()
    }
}

impl BrowserNavigationCommand {
    pub const fn new(
        target: yosoi::RequestedWebTarget,
        readiness: yosoi::BrowserNavigationReadinessCheckpoint,
    ) -> Self {
        Self { target, readiness }
    }

    pub const fn target(&self) -> &yosoi::RequestedWebTarget {
        &self.target
    }

    pub const fn readiness(&self) -> yosoi::BrowserNavigationReadinessCheckpoint {
        self.readiness
    }
}

/// Manager-backed scheduler with runtime-configured, bounded capacity.
///
/// Admission is FIFO within each concrete tab and round-robin across browser
/// sessions. A command blocked behind an active command on its tab does not
/// prevent a runnable command on another tab from using available capacity.
/// Queued commands inherit the execution manager's configured queue-wait
/// deadline and resolve with an explicit terminal receipt when it elapses.
pub struct BrowserNavigationScheduler {
    pub(super) inner: Arc<SchedulerInner>,
}

/// Point-in-time scheduler capacity counters.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BrowserNavigationSchedulerSnapshot {
    pub active_navigations: u32,
    pub queued_navigations: u32,
    pub closing: bool,
}

#[derive(Clone, Copy)]
pub(super) struct QueuedNavigation {
    pub(super) ticket: u64,
    pub(super) tab: yosoi::BrowserTabLeaseId,
    pub(super) session: yosoi::BrowserSessionLeaseId,
}

pub(super) struct SchedulerState {
    pub(super) queue: VecDeque<QueuedNavigation>,
    pub(super) active_tabs: HashMap<yosoi::BrowserTabLeaseId, yosoi::BrowserSessionLeaseId>,
    pub(super) session_order: VecDeque<yosoi::BrowserSessionLeaseId>,
    pub(super) last_dispatched_session: Option<yosoi::BrowserSessionLeaseId>,
    pub(super) active_navigations: u32,
}

impl fmt::Debug for BrowserNavigationScheduler {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("BrowserNavigationScheduler")
            .field("id", &self.inner.id)
            .field("limits", &self.inner.limits)
            .finish_non_exhaustive()
    }
}

pub(super) struct SchedulerInner {
    pub(super) id: yosoi::BrowserNavigationSchedulerId,
    pub(super) manager: BrowserExecutionManager,
    pub(super) limits: yosoi::BrowserNavigationSchedulerLimits,
    pub(super) state: Mutex<SchedulerState>,
    pub(super) state_changed: Notify,
    pub(super) closing: CancellationToken,
    pub(super) jobs: AtomicU32,
    pub(super) jobs_changed: Notify,
    pub(super) next_ticket: AtomicU64,
    pub(super) executor: Handle,
}

impl BrowserNavigationScheduler {
    pub fn new(
        manager: BrowserExecutionManager,
        limits: yosoi::BrowserNavigationSchedulerLimits,
    ) -> Result<Self, BrowserNavigationSchedulerError> {
        if limits.active_navigations().get() > manager.limits().tabs_total().get() {
            return Err(BrowserNavigationSchedulerError::InvalidLimits);
        }
        usize::try_from(limits.queue_depth().get())
            .map_err(|_| BrowserNavigationSchedulerError::InvalidLimits)?;
        usize::try_from(limits.active_navigations().get())
            .map_err(|_| BrowserNavigationSchedulerError::InvalidLimits)?;
        let executor = manager
            .inner
            .provider_executor
            .clone()
            .or_else(|| Handle::try_current().ok())
            .ok_or(BrowserNavigationSchedulerError::RuntimeUnavailable)?;
        let inner = Arc::new(SchedulerInner {
            id: yosoi::BrowserNavigationSchedulerId::random(),
            manager,
            limits,
            state: Mutex::new(SchedulerState {
                queue: VecDeque::new(),
                active_tabs: HashMap::new(),
                session_order: VecDeque::new(),
                last_dispatched_session: None,
                active_navigations: 0,
            }),
            state_changed: Notify::new(),
            closing: CancellationToken::new(),
            jobs: AtomicU32::new(0),
            jobs_changed: Notify::new(),
            next_ticket: AtomicU64::new(1),
            executor,
        });
        {
            let mut attached = inner
                .manager
                .inner
                .navigation_scheduler
                .lock()
                .map_err(|_| BrowserNavigationSchedulerError::InternalInvariant)?;
            if attached.as_ref().and_then(Weak::upgrade).is_some() {
                return Err(BrowserNavigationSchedulerError::SchedulerAlreadyAttached);
            }
            *attached = Some(Arc::downgrade(&inner));
        }
        Ok(Self { inner })
    }

    pub fn id(&self) -> yosoi::BrowserNavigationSchedulerId {
        self.inner.id
    }

    pub fn limits(&self) -> yosoi::BrowserNavigationSchedulerLimits {
        self.inner.limits
    }

    pub async fn snapshot(
        &self,
    ) -> Result<BrowserNavigationSchedulerSnapshot, BrowserNavigationSchedulerError> {
        let state = self.inner.state.lock().await;
        let queued_navigations = u32::try_from(state.queue.len())
            .map_err(|_| BrowserNavigationSchedulerError::InternalInvariant)?;
        Ok(BrowserNavigationSchedulerSnapshot {
            active_navigations: state.active_navigations,
            queued_navigations,
            closing: self.inner.closing.is_cancelled(),
        })
    }

    pub async fn acquire_session(
        &self,
        cancellation: &CancellationToken,
    ) -> Result<RuntimeBrowserLease, BrowserNavigationSchedulerError> {
        if self.inner.closing.is_cancelled() {
            return Err(BrowserNavigationSchedulerError::SchedulerClosing);
        }
        self.inner
            .manager
            .acquire_session(cancellation)
            .await
            .map_err(map_manager_error)
    }

    pub async fn schedule(
        &self,
        tab: &RuntimeBrowserTabLease,
        command: BrowserNavigationCommand,
        cancellation: &CancellationToken,
    ) -> Result<BrowserNavigationHandle, BrowserNavigationSchedulerError> {
        if command.readiness() == yosoi::BrowserNavigationReadinessCheckpoint::NetworkIdle {
            return Err(BrowserNavigationSchedulerError::UnsupportedReadiness {
                requested: command.readiness(),
            });
        }
        if self.inner.closing.is_cancelled() {
            return Err(BrowserNavigationSchedulerError::SchedulerClosing);
        }
        let runtime_tab = tab.clone();
        let tab = tab.navigation_parts().await.map_err(map_manager_error)?;
        let request = yosoi::BrowserNavigationRequest::new(
            self.inner.id,
            yosoi::BrowserNavigationRequestId::random(),
            tab.lease.clone(),
            command.readiness(),
        );
        let submitted = Instant::now();
        let progress_capacity = usize::try_from(self.inner.limits.progress_capacity().get())
            .map_err(|_| BrowserNavigationSchedulerError::InvalidLimits)?;
        let (progress_sender, progress) = mpsc::channel(progress_capacity);
        let (readiness_sender, readiness) = oneshot::channel();
        let (terminal_sender, terminal) = oneshot::channel();
        let handle_cancellation = CancellationToken::new();
        let ticket = {
            let mut state = self.inner.state.lock().await;
            let queue_depth = usize::try_from(self.inner.limits.queue_depth().get())
                .map_err(|_| BrowserNavigationSchedulerError::InvalidLimits)?;
            if state.queue.len() >= queue_depth {
                return Err(BrowserNavigationSchedulerError::QueueFull);
            }
            let ticket = self
                .inner
                .next_ticket
                .try_update(Ordering::AcqRel, Ordering::Acquire, |ticket| {
                    ticket.checked_add(1)
                })
                .map_err(|_| BrowserNavigationSchedulerError::InternalInvariant)?;
            self.inner
                .jobs
                .try_update(Ordering::AcqRel, Ordering::Acquire, |jobs| {
                    jobs.checked_add(1)
                })
                .map_err(|_| BrowserNavigationSchedulerError::InternalInvariant)?;
            let session = tab.lease.session().session();
            if !state.session_order.contains(&session) {
                state.session_order.push_back(session);
            }
            state.queue.push_back(QueuedNavigation {
                ticket,
                tab: tab.lease.tab(),
                session,
            });
            ticket
        };
        self.inner.state_changed.notify_waiters();
        let job = NavigationJob {
            request,
            command,
            tab,
            runtime_tab,
            ticket,
            submitted,
            caller_cancellation: cancellation.clone(),
            handle_cancellation: handle_cancellation.clone(),
            progress_sender,
            readiness_sender: Some(readiness_sender),
            terminal_sender: Some(terminal_sender),
        };
        let handle_request = job.request.clone();
        let inner = Arc::clone(&self.inner);
        let registration = JobCountGuard::new(Arc::downgrade(&self.inner));
        self.inner.executor.spawn(async move {
            run_navigation_job(inner, job, registration).await;
        });
        Ok(BrowserNavigationHandle::new(
            handle_request,
            progress,
            readiness,
            terminal,
            handle_cancellation,
        ))
    }

    pub async fn shutdown(&self) -> Result<(), BrowserNavigationSchedulerError> {
        self.inner.closing.cancel();
        loop {
            let notified = self.inner.jobs_changed.notified();
            tokio::pin!(notified);
            notified.as_mut().enable();
            if self.inner.jobs.load(Ordering::Acquire) == 0 {
                break;
            }
            notified.await;
        }
        self.inner
            .manager
            .shutdown()
            .await
            .map_err(map_manager_error)
    }
}

impl Drop for BrowserNavigationScheduler {
    fn drop(&mut self) {
        self.inner.closing.cancel();
    }
}

const fn map_manager_error(error: BrowserExecutionManagerError) -> BrowserNavigationSchedulerError {
    match error {
        BrowserExecutionManagerError::TabReleased => BrowserNavigationSchedulerError::TabReleased,
        BrowserExecutionManagerError::ManagerClosing => {
            BrowserNavigationSchedulerError::SchedulerClosing
        }
        _ => BrowserNavigationSchedulerError::ManagerUnavailable,
    }
}

pub(super) async fn drain_navigation_scheduler(
    manager: &Arc<super::ManagerInner>,
) -> Result<(), BrowserExecutionManagerError> {
    let scheduler = manager
        .navigation_scheduler
        .lock()
        .map_err(|_| BrowserExecutionManagerError::InternalInvariant)?
        .as_ref()
        .and_then(Weak::upgrade);
    let Some(scheduler) = scheduler else {
        return Ok(());
    };
    scheduler.closing.cancel();
    loop {
        let notified = scheduler.jobs_changed.notified();
        tokio::pin!(notified);
        notified.as_mut().enable();
        if scheduler.jobs.load(Ordering::Acquire) == 0 {
            return Ok(());
        }
        notified.await;
    }
}
