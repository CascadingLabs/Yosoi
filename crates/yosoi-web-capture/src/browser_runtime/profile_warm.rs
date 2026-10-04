//! Bounded, provider-backed provisioning of managed browser profiles.

use std::{
    fmt,
    sync::Arc,
    time::{Duration, SystemTime},
};

use chrono::{DateTime, Utc};
use provider::managed_profile::{
    ManagedProfileLeaseRelease, ManagedProfileStagingDisposition, StagedManagedProfile,
};
use thiserror::Error;
use tokio::time::{Instant, sleep_until};
use tokio_util::sync::CancellationToken;
use void_crawl_core as provider;

use crate::browser_execution::{
    BrowserExecutionLimits, BrowserNavigationSchedulerLimits,
    BrowserProfileLeaseGenerationRegistry, BrowserProfileLifecycleEvent, ProfileLifecycleStore,
    ProfileLifecycleStoreError,
};
use crate::{
    BrowserNavigationOutcome, BrowserNavigationProgressKind, BrowserNavigationReadinessCheckpoint,
    BrowserProfileId, NewProfileSpec, ProfileWarmPlan, ProfileWarmProcessCleanup,
    ProfileWarmProfileDisposition, ProfileWarmStepOutcome, ProfileWarmStepReceipt,
    ProfileWarmTerminalReason, ProfileWarmTerminalReceipt,
};

use super::{
    BrowserExecutionManager, BrowserExecutionManagerConfig, BrowserNavigationCommand,
    BrowserNavigationScheduler, BrowserNavigationSchedulerError,
};

mod execution;
mod service;

use execution::{empty_steps, execute_warm_plan, readiness_reached};

/// Inputs required to warm one newly staged managed profile.
pub struct ManagedProfileWarmService {
    registry: provider::ProfileRegistry,
    lifecycle: ProfileLifecycleStore,
    generations: Arc<BrowserProfileLeaseGenerationRegistry>,
    manager_limits: BrowserExecutionLimits,
    manager_config: BrowserExecutionManagerConfig,
    scheduler_limits: BrowserNavigationSchedulerLimits,
    lease_duration: Duration,
}

struct ProfileWarmCleanupOutcome {
    succeeded: bool,
    staging_release: Option<ManagedProfileLeaseRelease>,
}

impl fmt::Debug for ManagedProfileWarmService {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ManagedProfileWarmService")
            .finish_non_exhaustive()
    }
}

fn wall_now() -> DateTime<Utc> {
    SystemTime::now().into()
}

#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum ProfileWarmServiceError {
    #[error("managed profile warm-up requires exactly one process and context")]
    InvalidManagerLimits,
    #[error("managed profile warm-up lease duration must be positive")]
    InvalidLeaseDuration,
    #[error("managed profile warm-up scheduler capacity exceeds the single-tab manager")]
    InvalidSchedulerLimits,
    #[error("managed profile warm-up overall deadline exceeds supported time")]
    DeadlineOverflow,
    #[error("managed profile warm-up receipt invariant failed")]
    ReceiptInvariant,
}

#[cfg(test)]
#[allow(
    clippy::panic_in_result_fn,
    reason = "test assertions provide clearer warm transaction diagnostics"
)]
#[path = "profile_warm_tests.rs"]
mod tests;
