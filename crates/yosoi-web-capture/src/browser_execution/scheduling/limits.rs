use std::num::{NonZeroU32, NonZeroU64};

use serde::{Deserialize, Serialize};

use super::super::BrowserQueueDepthLimit;

macro_rules! nonzero_navigation_limit {
    ($name:ident) => {
        #[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
        #[serde(transparent)]
        pub struct $name(NonZeroU32);

        impl $name {
            /// Creates this caller-resolved non-zero limit.
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

nonzero_navigation_limit!(BrowserActiveNavigationLimit);
nonzero_navigation_limit!(BrowserNavigationProgressCapacity);
nonzero_navigation_limit!(BrowserEngineProgressCapacity);
nonzero_navigation_limit!(BrowserProviderEventCapacity);

/// Runtime-resolved maximum duration for one navigation, in milliseconds.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(transparent)]
pub struct BrowserNavigationDeadline(NonZeroU64);

impl BrowserNavigationDeadline {
    pub const fn new(milliseconds: NonZeroU64) -> Self {
        Self(milliseconds)
    }

    pub const fn milliseconds(self) -> u64 {
        self.0.get()
    }
}

/// Runtime-resolved bounds for one navigation scheduler.
///
/// No source-level tab ceiling exists: callers choose the active and queued
/// work bounds for each scheduler instance.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserNavigationSchedulerLimits {
    active_navigations: BrowserActiveNavigationLimit,
    queue_depth: BrowserQueueDepthLimit,
    progress_capacity: BrowserNavigationProgressCapacity,
    engine_progress_capacity: BrowserEngineProgressCapacity,
    provider_event_capacity: BrowserProviderEventCapacity,
    navigation_deadline: BrowserNavigationDeadline,
}

impl BrowserNavigationSchedulerLimits {
    pub const fn new(
        active_navigations: BrowserActiveNavigationLimit,
        queue_depth: BrowserQueueDepthLimit,
        progress_capacity: BrowserNavigationProgressCapacity,
        engine_progress_capacity: BrowserEngineProgressCapacity,
        provider_event_capacity: BrowserProviderEventCapacity,
        navigation_deadline: BrowserNavigationDeadline,
    ) -> Self {
        Self {
            active_navigations,
            queue_depth,
            progress_capacity,
            engine_progress_capacity,
            provider_event_capacity,
            navigation_deadline,
        }
    }

    pub const fn active_navigations(self) -> BrowserActiveNavigationLimit {
        self.active_navigations
    }

    pub const fn queue_depth(self) -> BrowserQueueDepthLimit {
        self.queue_depth
    }

    pub const fn progress_capacity(self) -> BrowserNavigationProgressCapacity {
        self.progress_capacity
    }

    pub const fn engine_progress_capacity(self) -> BrowserEngineProgressCapacity {
        self.engine_progress_capacity
    }

    pub const fn provider_event_capacity(self) -> BrowserProviderEventCapacity {
        self.provider_event_capacity
    }

    pub const fn navigation_deadline(self) -> BrowserNavigationDeadline {
        self.navigation_deadline
    }
}

/// The page-domain point at which a navigation becomes ready for its caller.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BrowserNavigationReadinessCheckpoint {
    CommandAccepted,
    DocumentCommitted,
    DomContentLoaded,
    Load,
    ControllerCompleted,
    /// Intentionally unsupported by the Page-only V1 scheduler.
    NetworkIdle,
}

/// Stable Yosoi milestone translated from bounded provider progress.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BrowserNavigationProgressKind {
    CommandAccepted,
    DocumentCommitted,
    SameDocumentNavigation,
    DomContentLoaded,
    Load,
    FrameStopped,
    ControllerCompleted,
}
