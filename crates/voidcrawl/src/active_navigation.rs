//! Bounded, per-target navigation lifecycle.
//!
//! Navigation observes only Page-domain events. It never enables the Network
//! or Runtime domains.

use std::{
    num::NonZeroUsize,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    time::Duration,
};

use tokio::{
    sync::{mpsc, oneshot},
    task::JoinHandle,
};

use crate::{MeasuredCount, Result, VoidCrawlError};

const DEFAULT_CLEANUP_TIMEOUT: Duration = Duration::from_secs(2);

mod progress;
mod start;
mod worker;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum NavigationStop {
    Cancelled,
    ReadinessSatisfied,
}

/// Caller-resolved bounds for one active navigation.
#[derive(Debug, Clone, Copy)]
pub struct ActiveNavigationOptions {
    progress_capacity: NonZeroUsize,
    provider_event_capacity: NonZeroUsize,
    max_duration: Duration,
    cleanup_timeout: Duration,
}

impl ActiveNavigationOptions {
    pub const fn new(progress_capacity: NonZeroUsize, max_duration: Duration) -> Self {
        Self {
            progress_capacity,
            provider_event_capacity: progress_capacity,
            max_duration,
            cleanup_timeout: DEFAULT_CLEANUP_TIMEOUT,
        }
    }

    pub const fn with_cleanup_timeout(mut self, cleanup_timeout: Duration) -> Self {
        self.cleanup_timeout = cleanup_timeout;
        self
    }

    pub const fn with_provider_event_capacity(mut self, capacity: NonZeroUsize) -> Self {
        self.provider_event_capacity = capacity;
        self
    }

    pub const fn progress_capacity(self) -> NonZeroUsize {
        self.progress_capacity
    }

    pub const fn max_duration(self) -> Duration {
        self.max_duration
    }

    pub const fn provider_event_capacity(self) -> NonZeroUsize {
        self.provider_event_capacity
    }

    pub const fn cleanup_timeout(self) -> Duration {
        self.cleanup_timeout
    }

    const fn validate(self) -> Result<Self> {
        if self.max_duration.is_zero() {
            return Err(VoidCrawlError::InvalidInput {
                operation: "start_navigation",
                reason: "navigation duration must be positive",
            });
        }
        if self.cleanup_timeout.is_zero() {
            return Err(VoidCrawlError::InvalidInput {
                operation: "start_navigation",
                reason: "navigation cleanup timeout must be positive",
            });
        }
        Ok(self)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NavigationProgressKind {
    CommandAccepted,
    DocumentCommitted,
    SameDocumentNavigation,
    DomContentLoaded,
    Load,
    FrameStopped,
}

/// One retained, secret-safe progress notification.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct NavigationProgress {
    pub sequence: u64,
    pub offset_micros: u64,
    pub kind: NavigationProgressKind,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct NavigationProgressAccounting {
    pub admitted: MeasuredCount,
    pub retained: MeasuredCount,
    pub dropped: MeasuredCount,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NavigationFailureReason {
    CommandRejected,
    BecameDownload,
    DocumentIdentityMismatch,
    DocumentIdentityUnavailable,
    EventStreamClosed,
    ProviderFailure,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NavigationTermination {
    Completed,
    Cancelled,
    DeadlineReached,
    PageClosed,
    BrowserClosed,
    Failed { reason: NavigationFailureReason },
}

/// Exactly-once terminal result kept separate from lossy progress.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct NavigationReport {
    pub termination: NavigationTermination,
    pub progress: NavigationProgressAccounting,
    pub provider_events_dropped: MeasuredCount,
    pub cleanup_complete: bool,
    pub same_document: bool,
}

#[derive(Debug, Default)]
pub(crate) struct NavigationState {
    active: AtomicBool,
    uncertain: AtomicBool,
}

impl NavigationState {
    pub(crate) fn begin(&self) -> Result<()> {
        if self.uncertain.load(Ordering::Acquire) {
            return Err(VoidCrawlError::NavigationStateUncertain);
        }
        self.active
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .map(|_| ())
            .map_err(|_| VoidCrawlError::NavigationAlreadyActive)
    }

    pub(crate) fn finish(&self, uncertain: bool) {
        if uncertain {
            self.uncertain.store(true, Ordering::Release);
        }
        self.active.store(false, Ordering::Release);
    }

    pub(crate) fn ensure_usable(&self) -> Result<()> {
        if self.uncertain.load(Ordering::Acquire) {
            Err(VoidCrawlError::NavigationStateUncertain)
        } else {
            Ok(())
        }
    }
}

pub(crate) struct NavigationStartGuard {
    state: Arc<NavigationState>,
    armed: bool,
}

impl NavigationStartGuard {
    pub(crate) const fn new(state: Arc<NavigationState>) -> Self {
        Self { state, armed: true }
    }

    pub(crate) const fn disarm(&mut self) {
        self.armed = false;
    }
}

impl Drop for NavigationStartGuard {
    fn drop(&mut self) {
        if self.armed {
            self.state.finish(true);
        }
    }
}

#[derive(Debug)]
#[must_use = "active navigation must be awaited or cancelled"]
pub struct ActiveNavigation {
    state: Arc<NavigationState>,
    progress: mpsc::Receiver<NavigationProgress>,
    terminal: oneshot::Receiver<NavigationReport>,
    cancel: Option<oneshot::Sender<NavigationStop>>,
    worker: Option<JoinHandle<()>>,
}

impl ActiveNavigation {
    pub async fn next_progress(&mut self) -> Result<Option<NavigationProgress>> {
        Ok(self.progress.recv().await)
    }

    pub async fn wait(mut self) -> Result<NavigationReport> {
        let report = (&mut self.terminal)
            .await
            .map_err(|_| VoidCrawlError::BrowserClosed)?;
        if let Some(worker) = self.worker.take() {
            worker.await.map_err(|_| VoidCrawlError::BrowserClosed)?;
        }
        Ok(report)
    }

    pub async fn cancel(mut self) -> Result<NavigationReport> {
        if let Some(cancel) = self.cancel.take() {
            let _ = cancel.send(NavigationStop::Cancelled);
        }
        self.wait().await
    }

    pub(crate) async fn complete_at_readiness(mut self) -> Result<NavigationReport> {
        if let Some(cancel) = self.cancel.take() {
            let _ = cancel.send(NavigationStop::ReadinessSatisfied);
        }
        self.wait().await
    }
}

impl Drop for ActiveNavigation {
    fn drop(&mut self) {
        if let Some(worker) = self.worker.take() {
            self.state.finish(true);
            worker.abort();
        }
    }
}
