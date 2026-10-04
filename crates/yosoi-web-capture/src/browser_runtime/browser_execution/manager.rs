use super::{
    Arc, AtomicU64, CancellationToken, Error, Handle, HashMap, ManagedProfileTenancy, ManagerState,
    Mutex, Notify, ProcessSlot, ProcessStatus, SchedulerInner, VecDeque, Weak, fmt, shutdown_inner,
    yosoi,
};
use provider::managed_profile::ManagedProfileLeaseRelease;
use std::{sync::Mutex as SyncMutex, time::Duration};
use void_crawl_core as provider;

/// Launch settings shared by the warm processes owned by one manager.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct BrowserExecutionManagerConfig {
    /// Run Chromium with a visible browser window.
    pub headful: bool,
    /// Use VoidCrawl's reduced CDP-domain mode.
    pub minimal_cdp: bool,
}

/// Secret-safe failure from concrete browser execution management.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum BrowserExecutionManagerError {
    #[error("browser execution admission queue is full")]
    QueueFull,
    #[error("browser execution admission deadline elapsed")]
    QueueWaitDeadline,
    #[error("browser execution request was cancelled")]
    CallerCancelled,
    #[error("browser execution manager is closing")]
    ManagerClosing,
    #[error("browser provider is unavailable")]
    ProviderUnavailable,
    #[error("additional tabs require a session-group lease")]
    IndependentLeaseHasNoAdditionalTabs,
    #[error("global browser tab capacity is exhausted")]
    GlobalTabCapacity,
    #[error("browser session tab capacity is exhausted")]
    SessionTabCapacity,
    #[error("browser tab is no longer owned by an active lease")]
    TabReleased,
    #[error("browser tab close failed")]
    TabCloseFailed,
    #[error("isolated browser context cleanup exceeded its deadline")]
    ContextCleanupDeadline,
    #[error("isolated browser context cleanup failed")]
    ContextCleanupFailed,
    #[error("browser process close or reap exceeded its deadline")]
    ProcessCloseDeadline,
    #[error("browser process close or reap failed")]
    ProcessCloseFailed,
    #[error("isolated browser context cleanup and process close or reap both failed")]
    ContextAndProcessCleanupFailed,
    #[error("browser execution accounting invariant failed")]
    InternalInvariant,
    #[error("managed profile is busy or unavailable")]
    ManagedProfileUnavailable,
    #[error("managed profile lease expired")]
    ManagedProfileExpired,
    #[error("managed profile child contract has expired")]
    ManagedProfileChildExpired,
    #[error("managed profile child contract is pending or not committed")]
    ManagedProfileChildNotCommitted,
    #[error("managed profile child-contract store is unavailable or invalid")]
    ManagedProfileChildContractUnavailable,
    #[error("managed profile ownership is uncertain; profile remains fenced")]
    ManagedProfileOwnershipUncertain,
    #[error("managed profile execution requires exactly one process and one active context")]
    InvalidManagedProfileLimits,
    #[error("managed profile lease duration must be positive")]
    InvalidManagedProfileLeaseDuration,
    #[error("managed profile execution requires a session-group lease")]
    ManagedProfileRequiresSessionScope,
}

impl BrowserExecutionManagerError {
    /// Returns the closed durable outcome when this failure occurred before admission.
    pub const fn pre_admission_outcome(self) -> Option<yosoi::BrowserExecutionPreAdmissionOutcome> {
        match self {
            Self::QueueFull => Some(yosoi::BrowserExecutionPreAdmissionOutcome::QueueFull),
            Self::QueueWaitDeadline => {
                Some(yosoi::BrowserExecutionPreAdmissionOutcome::QueueWaitDeadline)
            }
            Self::CallerCancelled => {
                Some(yosoi::BrowserExecutionPreAdmissionOutcome::CallerCancelled)
            }
            Self::ManagerClosing
            | Self::ManagedProfileExpired
            | Self::ManagedProfileChildExpired
            | Self::ManagedProfileChildNotCommitted
            | Self::ManagedProfileChildContractUnavailable
            | Self::ManagedProfileOwnershipUncertain => {
                Some(yosoi::BrowserExecutionPreAdmissionOutcome::ManagerClosing)
            }
            Self::ProviderUnavailable | Self::ManagedProfileUnavailable => {
                Some(yosoi::BrowserExecutionPreAdmissionOutcome::ProviderUnavailable)
            }
            Self::ProcessCloseDeadline => {
                Some(yosoi::BrowserExecutionPreAdmissionOutcome::ProviderCleanupDeadlineExceeded)
            }
            Self::ProcessCloseFailed | Self::ContextAndProcessCleanupFailed => {
                Some(yosoi::BrowserExecutionPreAdmissionOutcome::ProviderCleanupFailed)
            }
            Self::InternalInvariant => {
                Some(yosoi::BrowserExecutionPreAdmissionOutcome::InternalInvariantFailure)
            }
            _ => None,
        }
    }
}

/// Point-in-time, provider-free manager accounting useful for health checks.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BrowserExecutionManagerSnapshot {
    pub active_processes: u32,
    pub active_contexts: u32,
    pub active_tabs: u32,
    pub queued_requests: u32,
    pub closing: bool,
}

/// Yosoi-owned manager of warm VoidCrawl browser sessions and disposable contexts.
#[derive(Clone)]
pub struct BrowserExecutionManager {
    pub(super) inner: Arc<ManagerInner>,
}

impl fmt::Debug for BrowserExecutionManager {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("BrowserExecutionManager")
            .field("id", &self.inner.id)
            .field("limits", &self.inner.limits)
            .finish_non_exhaustive()
    }
}

pub(super) struct ManagerInner {
    pub(super) id: yosoi::BrowserExecutionManagerId,
    pub(super) limits: yosoi::BrowserExecutionLimits,
    pub(super) config: BrowserExecutionManagerConfig,
    pub(super) state: Mutex<ManagerState>,
    pub(super) changed: Notify,
    pub(super) closing: CancellationToken,
    // Provider background tasks must outlive runtimes used only by callers.
    pub(super) provider_executor: Option<Handle>,
    pub(super) next_ticket: AtomicU64,
    pub(super) navigation_scheduler: SyncMutex<Option<Weak<SchedulerInner>>>,
    pub(super) managed_profile: Option<Arc<ManagedProfileTenancy>>,
}

impl BrowserExecutionManager {
    /// Creates a lazy manager. Chromium processes launch on first admission and stay warm.
    pub fn new(
        limits: yosoi::BrowserExecutionLimits,
        config: BrowserExecutionManagerConfig,
    ) -> Self {
        Self::new_inner(limits, config, None)
    }

    /// Creates a lazy manager dedicated to one exclusively leased managed profile.
    /// The registry lock is acquired immediately before the first browser launch.
    #[allow(clippy::too_many_arguments)]
    pub fn new_managed_profile(
        limits: yosoi::BrowserExecutionLimits,
        config: BrowserExecutionManagerConfig,
        registry: provider::ProfileRegistry,
        profile_id: yosoi::BrowserProfileId,
        lifecycle: yosoi::ProfileLifecycleStore,
        generations: Arc<yosoi::BrowserProfileLeaseGenerationRegistry>,
        lease_duration: Duration,
    ) -> Result<Self, BrowserExecutionManagerError> {
        if limits.processes().get() != 1
            || limits.contexts_total().get() != 1
            || limits.contexts_per_process().get() != 1
        {
            return Err(BrowserExecutionManagerError::InvalidManagedProfileLimits);
        }
        let profile = ManagedProfileTenancy::new(
            registry,
            profile_id,
            lifecycle,
            generations,
            lease_duration,
        )?;
        Ok(Self::new_inner(limits, config, Some(Arc::new(profile))))
    }

    /// Creates a manager that takes ownership of an already-held staged
    /// profile lease. The same manager remains responsible for launch,
    /// navigation, and confirmed process shutdown.
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn new_staged_managed_profile(
        limits: yosoi::BrowserExecutionLimits,
        config: BrowserExecutionManagerConfig,
        registry: provider::ProfileRegistry,
        profile_id: yosoi::BrowserProfileId,
        owner_id: yosoi::BrowserProfileOwnerId,
        lifecycle: yosoi::ProfileLifecycleStore,
        generations: Arc<yosoi::BrowserProfileLeaseGenerationRegistry>,
        lease_duration: Duration,
        staged_lease: provider::ManagedProfileLease,
    ) -> Result<Self, BrowserExecutionManagerError> {
        if limits.processes().get() != 1
            || limits.contexts_total().get() != 1
            || limits.contexts_per_process().get() != 1
        {
            return Err(BrowserExecutionManagerError::InvalidManagedProfileLimits);
        }
        if lease_duration.is_zero() || staged_lease.id() != profile_id.as_str() {
            return Err(BrowserExecutionManagerError::ManagedProfileUnavailable);
        }
        let profile = ManagedProfileTenancy::new_staged(
            registry,
            profile_id,
            owner_id,
            lifecycle,
            generations,
            lease_duration,
            staged_lease,
        )?;
        Ok(Self::new_inner(limits, config, Some(Arc::new(profile))))
    }

    fn new_inner(
        limits: yosoi::BrowserExecutionLimits,
        config: BrowserExecutionManagerConfig,
        managed_profile: Option<Arc<ManagedProfileTenancy>>,
    ) -> Self {
        let mut slots = VecDeque::new();
        for _ in 0..limits.processes().get() {
            slots.push_back(ProcessSlot {
                id: yosoi::BrowserProcessSlotId::random(),
                generation: 0,
                status: ProcessStatus::Vacant,
                session: None,
                active_contexts: 0,
                completed_contexts: 0,
            });
        }
        Self {
            inner: Arc::new(ManagerInner {
                id: yosoi::BrowserExecutionManagerId::random(),
                limits,
                config,
                state: Mutex::new(ManagerState {
                    slots,
                    next_slot: 0,
                    active_contexts: 0,
                    active_tabs: 0,
                    queue: VecDeque::new(),
                    resources: HashMap::new(),
                    in_flight_creations: 0,
                    closing: false,
                    shutdown_complete: false,
                    maintenance_errors: VecDeque::new(),
                    creations: HashMap::new(),
                    #[cfg(test)]
                    process_close_outcomes: VecDeque::new(),
                    #[cfg(test)]
                    context_cleanup_dispositions: VecDeque::new(),
                    #[cfg(test)]
                    creation_pause: None,
                    #[cfg(test)]
                    context_creation_pause: None,
                    #[cfg(test)]
                    tab_reservation_pause: None,
                    #[cfg(test)]
                    tab_creation_pause: None,
                    #[cfg(test)]
                    release_pause: None,
                    #[cfg(test)]
                    last_created_tab: None,
                }),
                changed: Notify::new(),
                closing: CancellationToken::new(),
                provider_executor: Handle::try_current().ok(),
                next_ticket: AtomicU64::new(1),
                navigation_scheduler: SyncMutex::new(None),
                managed_profile,
            }),
        }
    }

    pub fn id(&self) -> yosoi::BrowserExecutionManagerId {
        self.inner.id
    }

    pub fn limits(&self) -> yosoi::BrowserExecutionLimits {
        self.inner.limits
    }

    pub fn config(&self) -> BrowserExecutionManagerConfig {
        self.inner.config
    }

    /// Reports whether this manager is bound to a persistent managed profile.
    pub fn is_managed_profile(&self) -> bool {
        self.inner.managed_profile.is_some()
    }

    /// Returns provider-free current capacity counters.
    pub async fn snapshot(
        &self,
    ) -> Result<BrowserExecutionManagerSnapshot, BrowserExecutionManagerError> {
        let state = self.inner.state.lock().await;
        let active_processes = state.slots.iter().try_fold(0_u32, |count, slot| {
            if matches!(slot.status, ProcessStatus::Vacant) {
                Ok(count)
            } else {
                count
                    .checked_add(1)
                    .ok_or(BrowserExecutionManagerError::InternalInvariant)
            }
        })?;
        Ok(BrowserExecutionManagerSnapshot {
            active_processes,
            active_contexts: state.active_contexts,
            active_tabs: state.active_tabs,
            queued_requests: u32::try_from(state.queue.len())
                .map_err(|_| BrowserExecutionManagerError::InternalInvariant)?,
            closing: state.closing,
        })
    }

    /// Closes admission, disposes every live context, and closes every owned process.
    /// A failed close remains owned and a later call retries it.
    pub async fn shutdown(&self) -> Result<(), BrowserExecutionManagerError> {
        let result = shutdown_inner(Arc::clone(&self.inner)).await;
        if result.is_err()
            && let Some(profile) = &self.inner.managed_profile
            && profile.ownership_is_held()
        {
            let _ownership_error = profile.mark_ownership_uncertain();
            return Err(BrowserExecutionManagerError::ManagedProfileOwnershipUncertain);
        }
        result
    }

    /// Returns the active or terminal secret-safe managed-profile lease facts.
    pub fn managed_profile_lease_receipt(&self) -> Option<yosoi::BrowserProfileLeaseReceipt> {
        self.inner
            .managed_profile
            .as_ref()
            .and_then(|profile| profile.lease_receipt())
    }

    /// Returns the terminal profile lease receipt after confirmed process close.
    pub fn managed_profile_terminal_receipt(
        &self,
    ) -> Option<yosoi::BrowserProfileLeaseTerminalReceipt> {
        self.inner
            .managed_profile
            .as_ref()
            .and_then(|profile| profile.terminal_receipt())
    }

    /// Takes the staging release token after shutdown has confirmed that no
    /// browser process can still be using the staged profile.
    pub(crate) fn take_managed_profile_staging_release(
        &self,
    ) -> Option<ManagedProfileLeaseRelease> {
        self.inner
            .managed_profile
            .as_ref()
            .and_then(|profile| profile.take_staging_release())
    }
}

impl Drop for BrowserExecutionManager {
    fn drop(&mut self) {
        if Arc::strong_count(&self.inner) != 1 {
            return;
        }
        let handle = self
            .inner
            .provider_executor
            .clone()
            .or_else(|| Handle::try_current().ok());
        let Some(handle) = handle else {
            return;
        };
        let inner = Arc::clone(&self.inner);
        handle.spawn(async move {
            let _ = shutdown_inner(inner).await;
        });
    }
}
