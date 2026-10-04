use std::{
    collections::{HashMap, VecDeque},
    fmt,
    num::NonZeroU64,
    sync::{
        Arc, Weak,
        atomic::{AtomicU64, Ordering},
    },
    time::Duration,
};

use crate as yosoi;
use thiserror::Error;
use tokio::{
    runtime::Handle,
    sync::{Mutex, Notify, mpsc, oneshot},
    task::JoinHandle,
    time::{Instant, sleep_until, timeout_at},
};
use tokio_util::sync::CancellationToken;
use void_crawl_core as provider;

mod admission;
mod cleanup;
mod lease;
mod manager;
mod process;
mod profile;
mod scheduler;
mod shutdown;
mod state;
mod tab;

use cleanup::{
    ReleaseExecutor, cleanup_deadline, release_wait_deadline, restart_release_on_current,
    start_release, wait_for_release, wait_for_release_before,
};
pub use lease::RuntimeBrowserLease;
use lease::{
    ExecutionPageContext, LeaseResource, LeaseState, ReleaseCompletion, ReleaseProgress, TabEntry,
};
use manager::ManagerInner;
pub use manager::{
    BrowserExecutionManager, BrowserExecutionManagerConfig, BrowserExecutionManagerError,
    BrowserExecutionManagerSnapshot,
};
use process::{
    close_process_slot, close_process_slot_outcome, poison_slot, rollback_abandoned_creation,
    rollback_creation_inner,
};
use profile::ManagedProfileTenancy;
pub use scheduler::{
    BrowserNavigationCommand, BrowserNavigationHandle, BrowserNavigationScheduler,
    BrowserNavigationSchedulerError, BrowserNavigationSchedulerSnapshot,
};
use scheduler::{SchedulerInner, drain_navigation_scheduler};
use shutdown::shutdown_inner;
use state::{
    CloseAction, ManagerState, ProcessCloseOutcome, ProcessSlot, ProcessStatus, QueuedRequestGuard,
    Reservation, ReserveDecision, enqueue_request, find_slot_mut, remove_ticket, reserve_capacity,
    rollback_reserved_capacity,
};
use tab::create_additional_tab;
pub use tab::{BrowserTabInstrumentationState, RuntimeBrowserTabLease};

#[cfg(test)]
#[path = "browser_execution_tests.rs"]
mod tests;
