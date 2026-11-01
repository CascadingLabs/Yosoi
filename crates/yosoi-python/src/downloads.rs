//! Python context management for one-use native download captures.

use std::{error::Error, fmt, path::PathBuf, sync::Arc};
use yosoi::request::CancellationToken;

use pyo3::prelude::*;
use serde_json::json;
use tokio::sync::{Mutex, Notify};
use yosoi::session::{DownloadCapture, DownloadError as SdkDownloadError};

use crate::{async_runtime, errors, media::NativeFileDocument};

fn download_error(error: &SdkDownloadError) -> PyErr {
    let (variant, details) = match error {
        SdkDownloadError::InvalidOptions => ("InvalidOptions", json!({})),
        SdkDownloadError::UnsupportedEngine => ("UnsupportedEngine", json!({})),
        SdkDownloadError::AttachedBrowserUnsupported => ("AttachedBrowserUnsupported", json!({})),
        SdkDownloadError::Busy => ("Busy", json!({})),
        SdkDownloadError::Fenced => ("Fenced", json!({})),
        SdkDownloadError::Timeout => ("Timeout", json!({})),
        SdkDownloadError::Cancelled => ("Cancelled", json!({})),
        SdkDownloadError::TooLarge { maximum } => ("TooLarge", json!({"maximum": maximum})),
        SdkDownloadError::Incomplete => ("Incomplete", json!({})),
        SdkDownloadError::Provider => ("Provider", json!({})),
        SdkDownloadError::Cleanup { recovery_directory } => (
            "Cleanup",
            json!({
                "recovery_directory": recovery_directory
                    .as_ref()
                    .map(|path| path.to_string_lossy().into_owned())
            }),
        ),
        SdkDownloadError::UnrelatedDownload { recovery_directory } => (
            "UnrelatedDownload",
            json!({"recovery_directory": recovery_directory.to_string_lossy()}),
        ),
        SdkDownloadError::File(source) => (
            "File",
            json!({"source": {"rust_type": "yosoi::documents::FileDocumentError", "message": source.to_string()}}),
        ),
    };
    let sources = Error::source(error)
        .map(|source| vec![source.to_string()])
        .unwrap_or_default();
    Python::attach(|py| {
        errors::with_metadata(
            py,
            errors::DownloadError::new_err(error.to_string()),
            "yosoi::session::DownloadError",
            Some(variant),
            details,
            &sources,
        )
    })
}

#[derive(Clone)]
enum CaptureCleanupFailure {
    Cleanup { recovery_directory: Option<PathBuf> },
    UnrelatedDownload { recovery_directory: PathBuf },
}

impl CaptureCleanupFailure {
    fn sdk_error(self) -> SdkDownloadError {
        match self {
            Self::Cleanup { recovery_directory } => {
                SdkDownloadError::Cleanup { recovery_directory }
            }
            Self::UnrelatedDownload { recovery_directory } => {
                SdkDownloadError::UnrelatedDownload { recovery_directory }
            }
        }
    }
}

struct CaptureSlot {
    capture: Option<DownloadCapture>,
    waiting: bool,
    cleanup_failure: Option<CaptureCleanupFailure>,
    changed: Arc<Notify>,
}

type CaptureState = Arc<Mutex<CaptureSlot>>;

#[pyclass(
    frozen,
    skip_from_py_object,
    module = "yosoi._native",
    name = "DownloadCapture"
)]
pub struct NativeDownloadCapture {
    state: CaptureState,
    cancellation: CancellationToken,
}

impl fmt::Debug for NativeDownloadCapture {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("NativeDownloadCapture")
            .finish_non_exhaustive()
    }
}

impl NativeDownloadCapture {
    pub(crate) fn new(capture: DownloadCapture) -> Self {
        Self {
            state: Arc::new(Mutex::new(CaptureSlot {
                capture: Some(capture),
                waiting: false,
                cleanup_failure: None,
                changed: Arc::new(Notify::new()),
            })),
            cancellation: CancellationToken::new(),
        }
    }
}

impl Drop for NativeDownloadCapture {
    fn drop(&mut self) {
        self.cancellation.cancel();
    }
}

#[pymethods]
impl NativeDownloadCapture {
    /// Wait for a completed file while retaining native cleanup on cancellation.
    fn wait<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let state = Arc::clone(&self.state);
        let cancellation = self.cancellation.clone();
        async_runtime::bridge(py, None, move |bridge_cancellation| async move {
            let bridge_token = bridge_cancellation.clone();
            let wait_token = cancellation.clone();
            let watcher = tokio::spawn(async move {
                bridge_token.cancelled().await;
                wait_token.cancel();
            });
            let result = {
                let capture = {
                    let mut slot = state.lock().await;
                    if slot.waiting {
                        drop(slot);
                        watcher.abort();
                        return Err(download_error(&SdkDownloadError::Busy));
                    }
                    let Some(capture) = slot.capture.take() else {
                        drop(slot);
                        watcher.abort();
                        return Err(download_error(&SdkDownloadError::Incomplete));
                    };
                    slot.waiting = true;
                    drop(slot);
                    capture
                };
                capture.wait_cancellable(&cancellation).await
            };
            let changed = {
                let mut slot = state.lock().await;
                slot.waiting = false;
                slot.cleanup_failure = match &result {
                    Err(SdkDownloadError::Cleanup { recovery_directory }) => {
                        Some(CaptureCleanupFailure::Cleanup {
                            recovery_directory: recovery_directory.clone(),
                        })
                    }
                    Err(SdkDownloadError::UnrelatedDownload { recovery_directory }) => {
                        Some(CaptureCleanupFailure::UnrelatedDownload {
                            recovery_directory: recovery_directory.clone(),
                        })
                    }
                    _ => None,
                };
                Arc::clone(&slot.changed)
            };
            changed.notify_waiters();
            watcher.abort();
            result
                .map(NativeFileDocument::new)
                .map_err(|error| download_error(&error))
        })
    }

    /// Cancel a pending download and await browser-context cleanup.
    fn cancel<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let state = Arc::clone(&self.state);
        let cancellation = self.cancellation.clone();
        cancellation.cancel();
        async_runtime::bridge(py, None, move |_| async move {
            loop {
                let changed = {
                    let slot = state.lock().await;
                    Arc::clone(&slot.changed)
                };
                let notified = changed.notified();
                tokio::pin!(notified);
                notified.as_mut().enable();
                let (waiting, capture, cleanup_failure) = {
                    let mut slot = state.lock().await;
                    if slot.waiting {
                        (true, None, None)
                    } else {
                        let capture = slot.capture.take();
                        if capture.is_some() {
                            slot.waiting = true;
                        }
                        let failure = if capture.is_none() {
                            slot.cleanup_failure.take()
                        } else {
                            None
                        };
                        (false, capture, failure)
                    }
                };
                if waiting {
                    notified.await;
                    continue;
                }
                if let Some(capture) = capture {
                    let result = capture.cancel().await;
                    let changed = {
                        let mut slot = state.lock().await;
                        slot.waiting = false;
                        Arc::clone(&slot.changed)
                    };
                    changed.notify_waiters();
                    return result.map_err(|error| download_error(&error));
                }
                if let Some(failure) = cleanup_failure {
                    return Err(download_error(&failure.sdk_error()));
                }
                return Ok(());
            }
        })
    }
}

pub fn download_error_for_browser(error: &SdkDownloadError) -> PyErr {
    download_error(error)
}
