//! Bounded native Chrome download capture for owned browser contexts.

use super::Page;
use crate::internal::browser::vendor::chromiumoxide::{
    browser::Browser,
    cdp::browser_protocol::browser::{
        BrowserContextId, CancelDownloadParams, EventDownloadProgress, EventDownloadWillBegin,
        SetDownloadBehaviorBehavior, SetDownloadBehaviorParams,
    },
    listeners::EventStream,
};
use notify::RecommendedWatcher;
use std::{
    collections::{HashMap, HashSet},
    fmt, future,
    path::PathBuf,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    time::Duration,
};
use thiserror::Error;
use tokio::{
    runtime::Handle,
    sync::{Mutex, OwnedMutexGuard, mpsc, oneshot},
    time::{self as tokio_time, Instant},
};
use tokio_util::sync::CancellationToken;

const DOWNLOAD_EVENT_CAPACITY: usize = 256;

mod arm;
mod wait;

/// Shared per-context exclusivity and cleanup-failure fence for root CDP events.
#[derive(Debug)]
pub(in crate::internal::browser) struct DownloadCaptureCoordinator {
    lease: Arc<Mutex<()>>,
    fenced: Arc<AtomicBool>,
    actions_fenced: Arc<AtomicBool>,
}

impl DownloadCaptureCoordinator {
    /// Creates an independent root-event lease for one browser context.
    pub(in crate::internal::browser) fn new() -> Self {
        Self {
            lease: Arc::new(Mutex::new(())),
            fenced: Arc::new(AtomicBool::new(false)),
            actions_fenced: Arc::new(AtomicBool::new(false)),
        }
    }

    fn acquire(&self) -> Result<DownloadCaptureLease, DownloadCaptureError> {
        if self.fenced.load(Ordering::Acquire) {
            return Err(DownloadCaptureError::Fenced);
        }
        let guard = Arc::clone(&self.lease)
            .try_lock_owned()
            .map_err(|_| DownloadCaptureError::Busy)?;
        if self.fenced.load(Ordering::Acquire) {
            drop(guard);
            return Err(DownloadCaptureError::Fenced);
        }
        Ok(DownloadCaptureLease {
            _guard: Some(guard),
            fenced: Arc::clone(&self.fenced),
        })
    }

    fn fence(&self) {
        self.fenced.store(true, Ordering::Release);
    }

    fn fence_actions(&self) {
        self.fenced.store(true, Ordering::Release);
        self.actions_fenced.store(true, Ordering::Release);
    }

    fn actions_fenced(&self) -> bool {
        self.actions_fenced.load(Ordering::Acquire)
    }
}

struct DownloadCaptureLease {
    _guard: Option<OwnedMutexGuard<()>>,
    fenced: Arc<AtomicBool>,
}

impl DownloadCaptureLease {
    fn fence(&self) {
        self.fenced.store(true, Ordering::Release);
    }

    fn fence_actions(&self, coordinator: &DownloadCaptureCoordinator) {
        coordinator.fence_actions();
        self.fenced.store(true, Ordering::Release);
    }
}

/// Failure from preparing, waiting for, or cleaning up one native download.
#[derive(Debug, Error)]
pub enum DownloadCaptureError {
    /// Another capture already owns this context's exclusive download lease.
    #[error("a native download capture is already active in this browser context")]
    Busy,
    /// A prior capture cleanup made this context unavailable for more captures.
    #[error("native download capture was fenced after cleanup failure")]
    Fenced,
    /// This provider is attached or does not use owned Chrome/CDP.
    #[error("native downloads require an owned Chrome session")]
    Unsupported,
    /// The caller's absolute arm-to-completion deadline elapsed.
    #[error("native browser download timed out")]
    Timeout,
    /// Caller or owning browser cancellation stopped the transfer.
    #[error("native browser download was cancelled")]
    Cancelled,
    /// Provider progress exceeded the maximum retained byte count.
    #[error("native browser download exceeded its {maximum}-byte limit")]
    TooLarge {
        /// Largest payload accepted for this capture.
        maximum: u64,
    },
    /// A required event, frame, or final file was missing or lost.
    #[error("native download capture event stream was incomplete")]
    Incomplete,
    /// Browser event, filesystem watch, or context setup failed.
    #[error("native download capture setup failed")]
    Setup,
    /// The exact GUID-named download file could not be read within bounds.
    #[error("native download file could not be read within its bound")]
    FileRead,
    /// The browser-supplied source URL exceeded the bounded file metadata field.
    #[error("native download source URL exceeds {maximum} metadata bytes: observed {observed}")]
    MetadataTooLong {
        /// Largest source URL size accepted by file metadata.
        maximum: usize,
        /// UTF-8 byte count in the observed source URL.
        observed: usize,
    },
    /// Browser behavior could not be restored; this context's Work is fenced.
    #[error("native download cleanup failed; the browser context is fenced")]
    Cleanup {
        /// Preserved directory when Chrome may still be writing files there.
        recovery_directory: Option<PathBuf>,
    },
    /// A sibling download shared the temporary path, which is preserved below.
    #[error("an unrelated browser download was routed to the capture directory")]
    UnrelatedDownload {
        /// Directory containing the preserved sibling and owned GUID files.
        recovery_directory: PathBuf,
    },
}

/// Completed bytes and the browser-suggested display name for a native download.
pub struct NativeDownloadResult {
    /// Exact downloaded bytes, bounded by the capture's maximum size.
    pub bytes: Vec<u8>,
    /// Browser-suggested display name, or a safe fallback for unbounded names.
    pub filename: String,
    /// CDP GUID whose filename was used to locate the completed file.
    pub guid: String,
    /// Exact event URL when supplied by the browser.
    pub source: Option<String>,
}

impl fmt::Debug for NativeDownloadResult {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("NativeDownloadResult")
            .field("bytes_len", &self.bytes.len())
            .field("filename", &self.filename)
            .finish_non_exhaustive()
    }
}

/// One armed capture. Dropping it schedules cancel/reset cleanup and retains the
/// context lease until cleanup settles.
pub struct NativeDownloadCapture {
    arming: Option<CaptureState>,
    result: Option<oneshot::Receiver<Result<NativeDownloadResult, DownloadCaptureError>>>,
    cancellation: CancellationToken,
}

impl fmt::Debug for NativeDownloadCapture {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("NativeDownloadCapture")
            .field("arming", &self.arming.is_some())
            .field("monitoring", &self.result.is_some())
            .finish_non_exhaustive()
    }
}

impl NativeDownloadCapture {
    /// Receives the monitored result while honoring cancellation and waiting for cleanup.
    pub async fn wait_cancellable(
        &mut self,
        wait_timeout: Duration,
        cancellation: &CancellationToken,
        owner_cancellation: &CancellationToken,
        closing: &CancellationToken,
        scoped_cancellation: &CancellationToken,
    ) -> Result<NativeDownloadResult, DownloadCaptureError> {
        let Some(mut receiver) = self.result.take() else {
            return Err(DownloadCaptureError::Incomplete);
        };
        let cancellation_task = self.cancellation.clone();
        let wait_deadline = Instant::now().checked_add(wait_timeout);
        let cancelled = tokio::select! {
            biased;
            () = cancellation.cancelled() => Some(DownloadCaptureError::Cancelled),
            () = owner_cancellation.cancelled() => Some(DownloadCaptureError::Cancelled),
            () = closing.cancelled() => Some(DownloadCaptureError::Cancelled),
            () = scoped_cancellation.cancelled() => Some(DownloadCaptureError::Cancelled),
            () = async move {
                if let Some(deadline) = wait_deadline {
                    tokio_time::sleep_until(deadline).await;
                } else {
                    future::pending::<()>().await;
                }
            } => {
                Some(DownloadCaptureError::Timeout)
            }
            result = &mut receiver => return result.unwrap_or(Err(DownloadCaptureError::Incomplete)),
        };
        cancellation_task.cancel();
        match receiver
            .await
            .unwrap_or(Err(DownloadCaptureError::Incomplete))
        {
            Err(DownloadCaptureError::Cancelled) | Ok(_) => {
                Err(cancelled.unwrap_or(DownloadCaptureError::Cancelled))
            }
            result => result,
        }
    }

    /// Cancels the monitor and waits for provider cleanup to settle.
    pub async fn cancel(&mut self) -> Result<(), DownloadCaptureError> {
        self.cancellation.cancel();
        let Some(receiver) = self.result.take() else {
            if let Some(state) = self.arming.as_mut() {
                let result = state.cleanup(true).await;
                self.arming.take();
                return result;
            }
            return Ok(());
        };
        match receiver
            .await
            .unwrap_or(Err(DownloadCaptureError::Incomplete))
        {
            Ok(_) | Err(DownloadCaptureError::Cancelled) => Ok(()),
            Err(error) => Err(error),
        }
    }
}

impl Drop for NativeDownloadCapture {
    fn drop(&mut self) {
        if let Some(mut state) = self.arming.take() {
            let handle = state.runtime.clone();
            handle.spawn(async move {
                if state.cleanup(true).await.is_err() {
                    state.coordinator.fence();
                    state.lease.fence();
                }
            });
        } else {
            self.cancellation.cancel();
        }
    }
}

struct CaptureState {
    browser: Arc<Mutex<Browser>>,
    coordinator: Arc<DownloadCaptureCoordinator>,
    lease: DownloadCaptureLease,
    runtime: Handle,
    deadline: Instant,
    context_id: Option<BrowserContextId>,
    context_key: Option<String>,
    target_id: String,
    frame_ids: HashSet<String>,
    frame_contexts: HashMap<String, Option<String>>,
    directory: Option<tempfile::TempDir>,
    watcher: Option<RecommendedWatcher>,
    file_events: mpsc::Receiver<()>,
    watcher_failed: Arc<AtomicBool>,
    will_begin: EventStream<EventDownloadWillBegin>,
    progress: EventStream<EventDownloadProgress>,
    max_bytes: u64,
    guid: Option<String>,
    filename: Option<String>,
    source: Option<String>,
    unrelated_download: bool,
    terminal: bool,
    armed: bool,
}

impl CaptureState {
    async fn cleanup(&mut self, cancel: bool) -> Result<(), DownloadCaptureError> {
        if !self.armed {
            return Ok(());
        }
        wait::drain_download_begins(self).await;
        let mut failed = false;
        if cancel
            && !self.terminal
            && let Some(guid) = self.guid.as_deref()
        {
            let mut command = CancelDownloadParams::builder().guid(guid);
            if let Some(context_id) = &self.context_id {
                command = command.browser_context_id(context_id.clone());
            }
            if let Ok(command) = command.build() {
                if self.browser.lock().await.execute(command).await.is_err() {
                    failed = true;
                }
            } else {
                failed = true;
            }
        }
        let mut reset = SetDownloadBehaviorParams::builder()
            .behavior(SetDownloadBehaviorBehavior::Default)
            .events_enabled(false);
        if let Some(context_id) = &self.context_id {
            reset = reset.browser_context_id(context_id.clone());
        }
        let mut reset_failed = false;
        if let Ok(reset) = reset.build() {
            if self.browser.lock().await.execute(reset).await.is_err() {
                failed = true;
                reset_failed = true;
            }
        } else {
            failed = true;
            reset_failed = true;
        }
        wait::drain_download_begins(self).await;
        self.armed = false;
        self.watcher.take();
        if reset_failed {
            self.lease.fence_actions(&self.coordinator);
        }
        if self.unrelated_download {
            self.coordinator.fence();
            self.lease.fence();
            let Some(directory) = self.directory.take() else {
                return Err(DownloadCaptureError::Cleanup {
                    recovery_directory: None,
                });
            };
            let recovery_directory = directory.keep();
            return Err(DownloadCaptureError::UnrelatedDownload { recovery_directory });
        }
        if failed {
            if !reset_failed {
                self.coordinator.fence();
                self.lease.fence();
            }
            let recovery_directory = self.directory.take().map(tempfile::TempDir::keep);
            Err(DownloadCaptureError::Cleanup { recovery_directory })
        } else {
            Ok(())
        }
    }
}

impl Page {
    /// Returns a typed failure when an earlier reset error fenced this context.
    pub(crate) fn ensure_download_context_available(&self) -> Result<(), DownloadCaptureError> {
        if self.download_coordinator.actions_fenced() {
            Err(DownloadCaptureError::Fenced)
        } else {
            Ok(())
        }
    }
}
