use std::num::{NonZeroU32, NonZeroU64};

use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use thiserror::Error;

macro_rules! nonzero_u32_limit {
    ($name:ident) => {
        #[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
        #[serde(transparent)]
        pub struct $name(NonZeroU32);

        impl $name {
            /// Creates this validated non-zero limit.
            pub const fn new(value: NonZeroU32) -> Self {
                Self(value)
            }

            /// Returns the configured limit.
            pub const fn get(self) -> u32 {
                self.0.get()
            }
        }
    };
}

nonzero_u32_limit!(BrowserProcessLimit);
nonzero_u32_limit!(BrowserContextTotalLimit);
nonzero_u32_limit!(BrowserContextsPerProcessLimit);
nonzero_u32_limit!(BrowserTabTotalLimit);
nonzero_u32_limit!(BrowserTabsPerSessionLimit);
nonzero_u32_limit!(BrowserQueueDepthLimit);
nonzero_u32_limit!(BrowserRecycleThreshold);

macro_rules! nonzero_millisecond_limit {
    ($name:ident) => {
        #[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
        #[serde(transparent)]
        pub struct $name(NonZeroU64);

        impl $name {
            /// Creates this validated non-zero millisecond limit.
            pub const fn new(milliseconds: NonZeroU64) -> Self {
                Self(milliseconds)
            }

            /// Returns the configured duration in milliseconds.
            pub const fn milliseconds(self) -> u64 {
                self.0.get()
            }
        }
    };
}

nonzero_millisecond_limit!(BrowserQueueWaitLimit);
nonzero_millisecond_limit!(BrowserCleanupDeadline);

/// Error returned when execution limits describe an impossible resource scope.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum BrowserExecutionLimitsError {
    #[error("contexts allowed per process cannot exceed total contexts")]
    ContextsPerProcessExceedsTotal,
    #[error("total context capacity exceeds the configured process slots")]
    ContextCapacityExceedsProcesses,
    #[error("process context capacity overflowed")]
    ContextCapacityOverflow,
    #[error("total tab capacity cannot be lower than total context capacity")]
    TabsBelowContexts,
    #[error("tabs allowed per session cannot exceed total tabs")]
    TabsPerSessionExceedsTotal,
}

/// Provider-neutral resource and timing limits for browser execution.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserExecutionLimits {
    processes: BrowserProcessLimit,
    contexts_total: BrowserContextTotalLimit,
    contexts_per_process: BrowserContextsPerProcessLimit,
    tabs_total: BrowserTabTotalLimit,
    tabs_per_session: BrowserTabsPerSessionLimit,
    queue_depth: BrowserQueueDepthLimit,
    queue_wait: BrowserQueueWaitLimit,
    cleanup_deadline: BrowserCleanupDeadline,
    recycle_threshold: BrowserRecycleThreshold,
}

impl BrowserExecutionLimits {
    #[allow(clippy::too_many_arguments)]
    pub const fn new(
        processes: BrowserProcessLimit,
        contexts_total: BrowserContextTotalLimit,
        contexts_per_process: BrowserContextsPerProcessLimit,
        tabs_total: BrowserTabTotalLimit,
        tabs_per_session: BrowserTabsPerSessionLimit,
        queue_depth: BrowserQueueDepthLimit,
        queue_wait: BrowserQueueWaitLimit,
        cleanup_deadline: BrowserCleanupDeadline,
        recycle_threshold: BrowserRecycleThreshold,
    ) -> Result<Self, BrowserExecutionLimitsError> {
        if contexts_per_process.get() > contexts_total.get() {
            return Err(BrowserExecutionLimitsError::ContextsPerProcessExceedsTotal);
        }
        let Some(context_capacity) = processes.get().checked_mul(contexts_per_process.get()) else {
            return Err(BrowserExecutionLimitsError::ContextCapacityOverflow);
        };
        if contexts_total.get() > context_capacity {
            return Err(BrowserExecutionLimitsError::ContextCapacityExceedsProcesses);
        }
        if tabs_total.get() < contexts_total.get() {
            return Err(BrowserExecutionLimitsError::TabsBelowContexts);
        }
        if tabs_per_session.get() > tabs_total.get() {
            return Err(BrowserExecutionLimitsError::TabsPerSessionExceedsTotal);
        }
        Ok(Self {
            processes,
            contexts_total,
            contexts_per_process,
            tabs_total,
            tabs_per_session,
            queue_depth,
            queue_wait,
            cleanup_deadline,
            recycle_threshold,
        })
    }

    pub const fn processes(&self) -> BrowserProcessLimit {
        self.processes
    }

    pub const fn contexts_total(&self) -> BrowserContextTotalLimit {
        self.contexts_total
    }

    pub const fn contexts_per_process(&self) -> BrowserContextsPerProcessLimit {
        self.contexts_per_process
    }

    pub const fn tabs_total(&self) -> BrowserTabTotalLimit {
        self.tabs_total
    }

    pub const fn tabs_per_session(&self) -> BrowserTabsPerSessionLimit {
        self.tabs_per_session
    }

    pub const fn queue_depth(&self) -> BrowserQueueDepthLimit {
        self.queue_depth
    }

    pub const fn queue_wait(&self) -> BrowserQueueWaitLimit {
        self.queue_wait
    }

    pub const fn cleanup_deadline(&self) -> BrowserCleanupDeadline {
        self.cleanup_deadline
    }

    pub const fn recycle_threshold(&self) -> BrowserRecycleThreshold {
        self.recycle_threshold
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BrowserExecutionLimitsWire {
    processes: BrowserProcessLimit,
    contexts_total: BrowserContextTotalLimit,
    contexts_per_process: BrowserContextsPerProcessLimit,
    tabs_total: BrowserTabTotalLimit,
    tabs_per_session: BrowserTabsPerSessionLimit,
    queue_depth: BrowserQueueDepthLimit,
    queue_wait: BrowserQueueWaitLimit,
    cleanup_deadline: BrowserCleanupDeadline,
    recycle_threshold: BrowserRecycleThreshold,
}

impl TryFrom<BrowserExecutionLimitsWire> for BrowserExecutionLimits {
    type Error = BrowserExecutionLimitsError;

    fn try_from(value: BrowserExecutionLimitsWire) -> Result<Self, Self::Error> {
        Self::new(
            value.processes,
            value.contexts_total,
            value.contexts_per_process,
            value.tabs_total,
            value.tabs_per_session,
            value.queue_depth,
            value.queue_wait,
            value.cleanup_deadline,
            value.recycle_threshold,
        )
    }
}

impl<'de> Deserialize<'de> for BrowserExecutionLimits {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        BrowserExecutionLimitsWire::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}
