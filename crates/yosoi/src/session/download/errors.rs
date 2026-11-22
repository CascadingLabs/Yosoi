//! Provider and session error projection for native downloads.

use super::{DownloadError, SessionError};
#[cfg(feature = "browser")]
use crate::documents::FileDocumentError;
#[cfg(feature = "browser")]
use crate::internal::browser::{
    VoidCrawlError, page::DownloadCaptureError as ProviderDownloadError,
};
#[cfg(feature = "browser")]
use crate::internal::web_capture::BrowserControlError;

pub(super) const fn map_session_error(error: &SessionError) -> DownloadError {
    match error {
        SessionError::InvalidInput | SessionError::InvalidPolicy => DownloadError::InvalidOptions,
        SessionError::BrowserFeatureDisabled
        | SessionError::Denied
        | SessionError::Execution(_)
        | SessionError::Unknown
        | SessionError::EvidenceUnavailable
        | SessionError::InputTargetLost
        | SessionError::ResultLimit { .. }
        | SessionError::AssertionEvaluation(_)
        | SessionError::WatchLagged(_)
        | SessionError::WatchDeadline
        | SessionError::Recording => DownloadError::Provider,
        SessionError::Cancelled | SessionError::Closed => DownloadError::Cancelled,
        SessionError::Deadline
        | SessionError::TimeoutAfterDispatch
        | SessionError::AcquisitionDeadline => DownloadError::Timeout,
        SessionError::Admission | SessionError::ExecutionCapacity(_) => DownloadError::Busy,
        SessionError::Unsupported(_) => DownloadError::UnsupportedEngine,
        SessionError::Cleanup => DownloadError::Cleanup {
            recovery_directory: None,
        },
    }
}

#[cfg(feature = "browser")]
pub(super) fn map_browser_error(error: BrowserControlError) -> DownloadError {
    match error {
        BrowserControlError::DownloadCapture(error) => match error {
            ProviderDownloadError::Busy => DownloadError::Busy,
            ProviderDownloadError::Fenced => DownloadError::Fenced,
            ProviderDownloadError::Unsupported => DownloadError::AttachedBrowserUnsupported,
            ProviderDownloadError::Timeout => DownloadError::Timeout,
            ProviderDownloadError::Cancelled => DownloadError::Cancelled,
            ProviderDownloadError::TooLarge { maximum } => DownloadError::TooLarge { maximum },
            ProviderDownloadError::MetadataTooLong { maximum, observed } => {
                DownloadError::File(FileDocumentError::MetadataTooLong {
                    field: "source",
                    maximum,
                    observed,
                })
            }
            ProviderDownloadError::Incomplete => DownloadError::Incomplete,
            ProviderDownloadError::Cleanup { recovery_directory } => {
                DownloadError::Cleanup { recovery_directory }
            }
            ProviderDownloadError::UnrelatedDownload { recovery_directory } => {
                DownloadError::UnrelatedDownload { recovery_directory }
            }
            ProviderDownloadError::FileRead | ProviderDownloadError::Setup => {
                DownloadError::Provider
            }
        },
        BrowserControlError::Provider(VoidCrawlError::UnsupportedCapability { .. }) => {
            DownloadError::UnsupportedEngine
        }
        BrowserControlError::Cancelled | BrowserControlError::ConditionWaitLost => {
            DownloadError::Cancelled
        }
        BrowserControlError::Deadline => DownloadError::Timeout,
        BrowserControlError::Ownership(_) => DownloadError::Cancelled,
        BrowserControlError::Capacity => DownloadError::Busy,
        _ => DownloadError::Provider,
    }
}
