//! Browser scopes shared by retained Sessions and ephemeral Requests.
use crate::internal::web_capture as capture;
use std::fmt;
use std::mem as std_mem;
use std::sync as std_sync;
use std::{
    num::{NonZeroU32, NonZeroU64},
    sync::{
        Arc, OnceLock,
        atomic::{AtomicBool, Ordering},
    },
};
use tokio::runtime as tokio_runtime;
use tokio::sync as tokio_sync;
use tokio::time as tokio_time;
use tokio::{
    sync::Mutex,
    time::{Duration, Instant},
};
use tokio_util::sync::CancellationToken;

#[derive(Clone)]
pub struct BrowserSession {
    inner: Arc<Inner>,
}
impl fmt::Debug for BrowserSession {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("BrowserSession")
            .field("closing", &self.inner.closing.load(Ordering::Acquire))
            .finish_non_exhaustive()
    }
}
struct Inner {
    manager: capture::BrowserExecutionManager,
    lease: capture::RuntimeBrowserLease,
    tabs: Mutex<Vec<capture::RuntimeBrowserTabLease>>,
    closing: AtomicBool,
    cancellation: CancellationToken,
    budget: std_sync::Mutex<Option<BudgetGuard>>,
}

struct BudgetGuard {
    manager: capture::BrowserExecutionManager,
    permit: Option<tokio_sync::OwnedSemaphorePermit>,
    executor: tokio_runtime::Handle,
}
impl BudgetGuard {
    fn released(&mut self) {
        let _ = self.permit.take();
    }
}

fn process_budget() -> Arc<tokio_sync::Semaphore> {
    static BUDGET: OnceLock<Arc<tokio_sync::Semaphore>> = OnceLock::new();
    Arc::clone(BUDGET.get_or_init(|| Arc::new(tokio_sync::Semaphore::new(2))))
}
fn wait_budget() -> Arc<tokio_sync::Semaphore> {
    static WAITERS: OnceLock<Arc<tokio_sync::Semaphore>> = OnceLock::new();
    Arc::clone(WAITERS.get_or_init(|| Arc::new(tokio_sync::Semaphore::new(32))))
}
fn quarantine(permit: tokio_sync::OwnedSemaphorePermit) {
    static QUARANTINED: OnceLock<std_sync::Mutex<Vec<tokio_sync::OwnedSemaphorePermit>>> =
        OnceLock::new();
    if let Ok(mut permits) = QUARANTINED
        .get_or_init(|| std_sync::Mutex::new(Vec::new()))
        .lock()
    {
        permits.push(permit);
    } else {
        // Preserve the slot rather than admitting another process after uncertainty.
        std_mem::forget(permit);
    }
}

impl BrowserSession {
    pub async fn acquire(
        mode: capture::BrowserMode,
        tabs: u32,
        minimal_cdp: bool,
        cancellation: &CancellationToken,
    ) -> Result<Self, capture::VoidCrawlAdapterError> {
        let executor = tokio_runtime::Handle::try_current()
            .map_err(|_| capture::VoidCrawlAdapterError::InvalidResolvedSpec)?;
        let waiting = wait_budget()
            .try_acquire_owned()
            .map_err(|_| capture::BrowserExecutionManagerError::QueueFull)?;
        let budget = tokio::select! {
            biased;
            () = cancellation.cancelled() => return Err(capture::VoidCrawlAdapterError::CancelledBeforeOwnership),
            permit = tokio_time::timeout(Duration::from_secs(10), process_budget().acquire_owned()) =>
                permit.map_err(|_| capture::BrowserExecutionManagerError::QueueWaitDeadline)?
                    .map_err(|_| capture::BrowserExecutionManagerError::ManagerClosing)?,
        };
        drop(waiting);
        let tabs =
            NonZeroU32::new(tabs).ok_or(capture::VoidCrawlAdapterError::InvalidResolvedSpec)?;
        let limits = capture::BrowserExecutionLimits::new(
            capture::BrowserProcessLimit::new(NonZeroU32::MIN),
            capture::BrowserContextTotalLimit::new(NonZeroU32::MIN),
            capture::BrowserContextsPerProcessLimit::new(NonZeroU32::MIN),
            capture::BrowserTabTotalLimit::new(tabs),
            capture::BrowserTabsPerSessionLimit::new(tabs),
            capture::BrowserQueueDepthLimit::new(NonZeroU32::MIN),
            capture::BrowserQueueWaitLimit::new(
                NonZeroU64::new(10_000)
                    .ok_or(capture::VoidCrawlAdapterError::InvalidResolvedSpec)?,
            ),
            capture::BrowserCleanupDeadline::new(
                NonZeroU64::new(5_000)
                    .ok_or(capture::VoidCrawlAdapterError::InvalidResolvedSpec)?,
            ),
            capture::BrowserRecycleThreshold::new(NonZeroU32::MIN),
        )
        .map_err(|_| capture::VoidCrawlAdapterError::InvalidResolvedSpec)?;
        let manager = capture::BrowserExecutionManager::new(
            limits,
            capture::BrowserExecutionManagerConfig {
                headful: matches!(mode, capture::BrowserMode::Headful),
                minimal_cdp,
            },
        );
        let mut budget = BudgetGuard {
            manager: manager.clone(),
            permit: Some(budget),
            executor,
        };
        let lease = match manager.acquire_session(cancellation).await {
            Ok(lease) => lease,
            Err(error) => {
                if manager.shutdown().await.is_ok() {
                    budget.released();
                }
                return Err(error.into());
            }
        };
        let initial = lease.initial_tab().clone();
        Ok(Self {
            inner: Arc::new(Inner {
                manager,
                lease,
                tabs: Mutex::new(vec![initial]),
                closing: AtomicBool::new(false),
                cancellation: CancellationToken::new(),
                budget: std_sync::Mutex::new(Some(budget)),
            }),
        })
    }
    pub fn id(&self) -> String {
        self.inner.lease.admission().session().session().to_string()
    }
    pub fn initial_tab(&self) -> capture::RuntimeBrowserTabLease {
        self.inner.lease.initial_tab().clone()
    }
    pub fn cancellation(&self) -> CancellationToken {
        self.inner.cancellation.clone()
    }
    pub fn is_closed(&self) -> bool {
        self.inner.closing.load(Ordering::Acquire)
    }
    pub async fn new_tab(
        &self,
    ) -> Result<capture::RuntimeBrowserTabLease, capture::BrowserExecutionManagerError> {
        if self.is_closed() {
            return Err(capture::BrowserExecutionManagerError::TabReleased);
        }
        let tab = self.inner.lease.new_tab(&self.inner.cancellation).await?;
        self.inner.tabs.lock().await.push(tab.clone());
        Ok(tab)
    }
    pub async fn control(
        &self,
        tab: &capture::RuntimeBrowserTabLease,
        maximum: Duration,
    ) -> Result<capture::RuntimeBrowserControl, capture::BrowserControlError> {
        if self.is_closed() {
            return Err(capture::BrowserExecutionManagerError::TabReleased.into());
        }
        let deadline = Instant::now()
            .checked_add(maximum)
            .ok_or(capture::BrowserControlError::InvalidInput)?;
        tab.control_before(&self.inner.cancellation, deadline).await
    }
    pub async fn close(&self) -> Result<(), capture::BrowserExecutionManagerError> {
        self.inner.closing.store(true, Ordering::Release);
        self.inner.cancellation.cancel();
        let release = self.inner.lease.release().await;
        let shutdown = self.inner.manager.shutdown().await;
        if shutdown.is_ok()
            && let Some(mut budget) = self
                .inner
                .budget
                .lock()
                .map_err(|_| capture::BrowserExecutionManagerError::InternalInvariant)?
                .take()
        {
            budget.released();
        }
        release?;
        shutdown
    }
}

impl Drop for BudgetGuard {
    fn drop(&mut self) {
        let Some(permit) = self.permit.take() else {
            return;
        };
        let manager = self.manager.clone();
        self.executor.spawn(async move {
            if manager.shutdown().await.is_err() {
                quarantine(permit);
            }
            // Otherwise the slot returns only after the owned processes close.
        });
    }
}

pub fn control_error(error: &capture::BrowserControlError) -> capture::VoidCrawlAdapterError {
    match error {
        capture::BrowserControlError::Ownership(error) => (*error).into(),
        capture::BrowserControlError::Cancelled => {
            capture::VoidCrawlAdapterError::CancelledBeforeStaging
        }
        capture::BrowserControlError::Deadline => {
            capture::VoidCrawlAdapterError::DeadlineBeforeStaging
        }
        capture::BrowserControlError::IncompleteCapture
        | capture::BrowserControlError::InvalidInput
        | capture::BrowserControlError::InputTargetLost
        | capture::BrowserControlError::Capacity => capture::VoidCrawlAdapterError::InvalidStaging,
        capture::BrowserControlError::ConditionWaitLost => {
            capture::VoidCrawlAdapterError::InvalidStaging
        }
        capture::BrowserControlError::Provider(_) => capture::VoidCrawlAdapterError::Provider {
            code: "session.control",
            category: capture::VoidCrawlAdapterErrorCategory::ProviderFailure,
        },
    }
}
