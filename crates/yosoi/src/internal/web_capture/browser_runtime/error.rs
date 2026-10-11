use crate::internal::web_capture as yosoi_web_capture;

use crate::internal::web_capture::WebArtifactFamily;
use thiserror::Error;

/// Secret-safe, adapter-owned classification of a provider failure.
///
/// `UnknownFuture` deliberately handles categories added to VoidCrawl's
/// non-exhaustive enum without making provider types part of this API.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum VoidCrawlAdapterErrorCategory {
    InvalidInput,
    Unsupported,
    Timeout,
    Interrupted,
    Unavailable,
    ProviderFailure,
    Internal,
    UnknownFuture,
}

#[derive(Debug, Error)]
pub enum VoidCrawlAdapterError {
    #[error("browser attempt stopped before becoming ready for finalization")]
    AttemptStopped,
    #[error("caller cancelled before browser ownership was established")]
    CancelledBeforeOwnership,
    #[error("caller cancelled after browser ownership but before factual staging")]
    CancelledBeforeStaging,
    #[error("attempt deadline elapsed before browser ownership was established")]
    DeadlineBeforeOwnership,
    #[error("attempt deadline elapsed after browser ownership but before factual staging")]
    DeadlineBeforeStaging,
    #[error("navigation completion policy is unsupported by the CAS-329 controller path")]
    UnsupportedNavigationPolicy,
    #[error("requested artifact family is unsupported by CAS-329: {family:?}")]
    UnsupportedFamily { family: WebArtifactFamily },
    #[error("source capture requires the later artifact-finalization boundary")]
    SourceRequiresFinalizationBoundary,
    #[error("the resolved browser isolation mode is unsupported")]
    UnsupportedIsolation,
    #[error("headful browser mode requires a configured X11 or Wayland display")]
    HeadfulDisplayUnavailable,
    #[error("provider capability contradicts the resolved Yosoi specification")]
    CapabilityMismatch,
    #[error("provider environment contradicts the resolved Yosoi specification ({field})")]
    EnvironmentMismatch { field: &'static str },
    #[error(
        "provider environment contradicts the resolved Yosoi specification ({field}: expected {expected}, observed {observed})"
    )]
    EnvironmentNumberMismatch {
        field: &'static str,
        expected: f64,
        observed: f64,
    },
    #[error("provider returned an invalid environment observation")]
    InvalidEnvironment,
    #[error("provider operation failed ({code}, {category:?})")]
    Provider {
        code: &'static str,
        category: VoidCrawlAdapterErrorCategory,
    },
    #[error("isolated browser context disposal failed")]
    ContextDisposal,
    #[error("browser session close failed")]
    SessionClose,
    #[error(transparent)]
    BrowserExecution(#[from] yosoi_web_capture::BrowserExecutionManagerError),
    #[error("observation collector finalization exceeded its cleanup deadline")]
    ObservationFinalizationDeadline,
    #[error("navigation collector finalization exceeded its cleanup deadline")]
    NavigationFinalizationDeadline,
    #[error("managed browser execution failed: {primary}")]
    ManagedExecution {
        #[source]
        primary: Box<Self>,
        receipt: Box<yosoi_web_capture::BrowserExecutionReceipt>,
    },
    #[error("{primary}; cleanup also failed ({cleanup})")]
    PrimaryAndCleanup {
        #[source]
        primary: Box<Self>,
        cleanup: &'static str,
    },
    #[error("recording byte domains are outside the CAS-329 supported subset")]
    UnsupportedRecording,
    #[error("a resolved bound or environment override could not be represented by the provider")]
    InvalidResolvedSpec,
    #[error("provider output could not satisfy the Yosoi staging invariants")]
    InvalidStaging,
    #[error("source representation staging failed: {0}")]
    SourceRepresentation(#[from] yosoi_web_capture::BrowserSourceRepresentationError),
    #[error("provider output contradicts the validated Yosoi adapter contract: {0}")]
    InvalidOutput(#[from] yosoi_web_capture::BrowserAdapterOutputError),
}

impl VoidCrawlAdapterError {
    /// Returns the durable execution receipt when failure happened after admission.
    pub fn execution_receipt(&self) -> Option<&yosoi_web_capture::BrowserExecutionReceipt> {
        match self {
            Self::ManagedExecution { receipt, .. } => Some(receipt),
            _ => None,
        }
    }
}
