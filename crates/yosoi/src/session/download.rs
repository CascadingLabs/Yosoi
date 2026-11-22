//! Native browser download capture on a retained Work tab.

use super::{ActionKind, SessionError, Work};
#[cfg(feature = "browser")]
use super::{SCOPED_CANCELLATION, Session};
use crate::browser::BrowserEngine;
use crate::documents::{FileDocument, FileDocumentError, MAX_FILE_BYTES};
#[cfg(feature = "browser")]
use crate::documents::{FileLimits, FileMetadata, file_from_bytes};
#[cfg(feature = "browser")]
use crate::internal::{
    browser::{page::DownloadCaptureError, page::NativeDownloadCapture},
    web_capture::{BrowserControlError, RuntimeBrowserControl},
};
use crate::request::CancellationToken;
#[cfg(feature = "browser")]
use crate::timing;
use std::{fmt, path::PathBuf, time::Duration};
use thiserror::Error;
use tokio::time as tokio_time;
#[path = "download/errors.rs"]
mod errors;
#[cfg(feature = "browser")]
use errors::map_browser_error;
use errors::map_session_error;

/// Maximum captured download size unless the caller supplies another bound.
pub const DEFAULT_DOWNLOAD_MAX_BYTES: u64 = 67_108_864;
/// Default time spent waiting for the caller-triggered download to finish.
pub const DEFAULT_DOWNLOAD_TIMEOUT_MS: u64 = 30_000;

/// Byte and time bounds for one caller-triggered native browser download.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct DownloadOptions {
    /// Largest download accepted, from one byte through [`MAX_FILE_BYTES`].
    pub max_bytes: u64,
    /// Absolute arm-to-completion timeout, bounded to a representable runtime deadline.
    pub timeout_ms: u64,
}

impl Default for DownloadOptions {
    fn default() -> Self {
        Self {
            max_bytes: DEFAULT_DOWNLOAD_MAX_BYTES,
            timeout_ms: DEFAULT_DOWNLOAD_TIMEOUT_MS,
        }
    }
}

/// Failure to arm, wait for, cancel, or materialize a native browser download.
#[derive(Debug, Error)]
pub enum DownloadError {
    /// The selected limit was zero, exceeded the file hard cap, or the timeout was zero.
    #[error("invalid download bounds")]
    InvalidOptions,
    /// Native downloads require the owned Chrome/CDP engine.
    #[error("native browser downloads are unsupported by the selected engine")]
    UnsupportedEngine,
    /// Native downloads cannot be captured from an attached browser.
    #[error("native browser downloads are unsupported for attached sessions")]
    AttachedBrowserUnsupported,
    /// Another native capture currently holds this browser context's capture lease.
    #[error("another native download capture is active in this browser context")]
    Busy,
    /// A previous cleanup failure fenced further captures in this context.
    #[error("native download capture is unavailable after a cleanup failure")]
    Fenced,
    /// The transfer or capture wait exceeded its deadline.
    #[error("native browser download timed out")]
    Timeout,
    /// Caller cancellation or owning Session shutdown stopped capture.
    #[error("native browser download was cancelled")]
    Cancelled,
    /// A response or final GUID file exceeded the requested byte bound.
    #[error("native browser download exceeded the {maximum}-byte limit")]
    TooLarge {
        /// Largest payload accepted for this capture.
        maximum: u64,
    },
    /// Required browser or filesystem evidence was lost or incomplete.
    #[error("native browser download evidence was incomplete")]
    Incomplete,
    /// Browser event capture could not be prepared or completed.
    #[error("native browser download provider failed")]
    Provider,
    /// Browser cleanup failed; the optional directory contains recoverable native files.
    #[error("native browser download cleanup failed")]
    Cleanup {
        /// Preserved directory when cleanup may have left Chrome writing there.
        recovery_directory: Option<PathBuf>,
    },
    /// A sibling or additional browser download used this context-scoped directory.
    #[error("an unrelated browser download was preserved at {recovery_directory}")]
    UnrelatedDownload {
        /// Directory retained with the exact GUID-named download files for recovery.
        recovery_directory: PathBuf,
    },
    /// The downloaded bytes could not be converted into a bounded file document.
    #[error(transparent)]
    File(#[from] FileDocumentError),
}

/// A one-use armed download capture that retains its owning Session and tab authority.
///
/// `expect_download` only arms listeners and the browser context. The caller
/// performs the triggering action with its normal Work or Flow methods, then
/// consumes this value with `wait`. Waiting parks without holding browser
/// worker capacity. The owned capture keeps the tab leased even if its Work
/// handle is dropped. Dropping the capture signals provider cancellation and
/// schedules context restoration; explicit [`cancel`](Self::cancel) reports
/// cleanup failure directly.
pub struct DownloadCapture {
    #[cfg(feature = "browser")]
    session: Session,
    #[cfg(feature = "browser")]
    tab_id: String,
    #[cfg(feature = "browser")]
    control: RuntimeBrowserControl,
    capture_id: String,
    options: DownloadOptions,
    #[cfg(feature = "browser")]
    native: Option<NativeDownloadCapture>,
}

impl fmt::Debug for DownloadCapture {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("DownloadCapture")
            .field("capture_id", &self.capture_id)
            .field("options", &self.options)
            .finish_non_exhaustive()
    }
}

impl DownloadCapture {
    /// Waits for the matching root/frame GUID file to finalize, then returns
    /// its immutable bounded [`FileDocument`]. This consumes the capture once.
    pub async fn wait(self) -> Result<FileDocument, DownloadError> {
        let cancellation = CancellationToken::new();
        self.wait_cancellable(&cancellation).await
    }

    /// Waits for the matching download while observing caller cancellation.
    /// Cancellation first cancels the provider download when possible, restores
    /// browser context behavior, and releases the capture lease before returning.
    #[allow(
        unused_mut,
        reason = "the browser-enabled implementation takes the native receiver"
    )]
    pub async fn wait_cancellable(
        mut self,
        cancellation: &CancellationToken,
    ) -> Result<FileDocument, DownloadError> {
        #[cfg(feature = "browser")]
        {
            let mut native = self.native.take().ok_or(DownloadError::Incomplete)?;
            let mut maximum_wait = Duration::from_millis(self.options.timeout_ms);
            if let Some(remaining) = timing::remaining() {
                maximum_wait = maximum_wait.min(remaining);
            }
            let scoped = SCOPED_CANCELLATION
                .try_with(Clone::clone)
                .unwrap_or_default();
            let session_cancel = self.session.inner.backend.cancellation();
            let result = self
                .control
                .wait_download_capture(
                    &mut native,
                    maximum_wait,
                    cancellation,
                    &session_cancel,
                    &scoped,
                )
                .await;
            drop(native);
            let result = match result {
                Ok(result) => result,
                Err(error) => {
                    let error = map_browser_error(error);
                    if matches!(error, DownloadError::Cleanup { .. }) {
                        self.control.fence();
                    }
                    return Err(error);
                }
            };
            let mut metadata = FileMetadata::new().with_filename(result.filename)?;
            if let Some(source) = result.source {
                metadata = metadata.with_source(source)?;
            }
            metadata = metadata
                .with_capture_id(self.capture_id.clone())?
                .with_session_id(self.session.inner.backend.id())?
                .with_tab_id(self.tab_id.clone())?
                .with_download_id(result.guid)?;
            file_from_bytes(
                self.capture_id.clone(),
                result.bytes,
                metadata,
                FileLimits {
                    max_bytes: self.options.max_bytes,
                },
            )
            .map_err(DownloadError::File)
        }
        #[cfg(not(feature = "browser"))]
        {
            let _ = self;
            let _ = cancellation;
            Err(DownloadError::Provider)
        }
    }

    /// Cancels the matching provider download when its GUID is known, restores
    /// browser context settings, and releases the capture lease.
    pub async fn cancel(self) -> Result<(), DownloadError> {
        #[cfg(feature = "browser")]
        {
            let mut native = self.native.ok_or(DownloadError::Incomplete)?;
            let result = self.control.cancel_download_capture(&mut native).await;
            drop(native);
            match result {
                Ok(()) => Ok(()),
                Err(error) => {
                    let error = map_browser_error(error);
                    if matches!(error, DownloadError::Cleanup { .. }) {
                        self.control.fence();
                    }
                    Err(error)
                }
            }
        }
        #[cfg(not(feature = "browser"))]
        {
            let _ = self;
            Err(DownloadError::Provider)
        }
    }
}

impl Work {
    /// Arms native download capture on this owned Chrome tab. Perform the
    /// triggering click, navigation, or Flow action after this returns, then
    /// call `capture.wait()`. No click or retry is performed automatically.
    pub async fn expect_download(
        &self,
        options: DownloadOptions,
    ) -> Result<DownloadCapture, DownloadError> {
        if options.max_bytes == 0
            || options.max_bytes > MAX_FILE_BYTES
            || options.timeout_ms == 0
            || tokio_time::Instant::now()
                .checked_add(Duration::from_millis(options.timeout_ms))
                .is_none()
        {
            return Err(DownloadError::InvalidOptions);
        }
        if self.session.policy().browser.engine != BrowserEngine::Chrome {
            return Err(DownloadError::UnsupportedEngine);
        }
        #[cfg(feature = "browser")]
        self.control.check_authority().map_err(map_browser_error)?;
        let _operation = self
            .operation()
            .map_err(|error| map_session_error(&error))?;
        self.authorize(ActionKind::Download, "")
            .map_err(|error| map_session_error(&error))?;
        #[cfg(feature = "browser")]
        {
            let native = start_capture(self, options.max_bytes, options.timeout_ms).await?;
            Ok(DownloadCapture {
                session: self.session.clone(),
                tab_id: self.tab_id.clone(),
                control: self.control.clone(),
                capture_id: super::new_operation_id(),
                options,
                native: Some(native),
            })
        }
        #[cfg(not(feature = "browser"))]
        {
            Err(DownloadError::Provider)
        }
    }
}

#[cfg(all(test, feature = "browser"))]
#[path = "download_tests.rs"]
mod tests;

#[cfg(feature = "browser")]
async fn start_capture(
    work: &Work,
    max_bytes: u64,
    timeout_ms: u64,
) -> Result<NativeDownloadCapture, DownloadError> {
    if work.timeout().is_zero() {
        return Err(DownloadError::Timeout);
    }
    let deadline = timing::deadline()
        .or_else(|| timing::checked_deadline(work.timeout()))
        .ok_or(DownloadError::InvalidOptions)?;
    let _permit = work
        .execution_permit(deadline)
        .await
        .map_err(|error| map_session_error(&error))?;
    work.control.check_authority().map_err(map_browser_error)?;
    let scoped = SCOPED_CANCELLATION
        .try_with(Clone::clone)
        .unwrap_or_default();
    let session_cancel = work.session.inner.backend.cancellation();
    let closing = work.control.closing();
    let mut dispatch = super::DispatchFence {
        control: &work.control,
        unresolved: true,
    };
    let result = tokio::select! {
        biased;
        () = scoped.cancelled() => {
            dispatch.unresolved = false;
            return Err(DownloadError::Cancelled);
        }
        () = session_cancel.cancelled() => {
            dispatch.unresolved = false;
            return Err(DownloadError::Cancelled);
        }
        () = closing.cancelled() => {
            dispatch.unresolved = false;
            return Err(DownloadError::Cancelled);
        }
        result = tokio_time::timeout_at(deadline, work.control.start_download_capture(max_bytes, Duration::from_millis(timeout_ms))) => {
            match result {
                Ok(result) => result,
                Err(_) => return Err(DownloadError::Timeout),
            }
        }
    };
    dispatch.unresolved = result
        .as_ref()
        .err()
        .is_some_and(BrowserControlError::requires_fence);
    let capture = result.map_err(|error| {
        if matches!(
            error,
            BrowserControlError::DownloadCapture(DownloadCaptureError::Cleanup { .. })
        ) {
            work.control.fence();
        }
        map_browser_error(error)
    })?;
    dispatch.unresolved = false;
    Ok(capture)
}
