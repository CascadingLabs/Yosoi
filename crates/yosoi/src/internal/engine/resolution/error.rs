use crate::internal::direct_http::DirectHttpCaptureSpecError;
use crate::internal::types::{ByteLimitError, CaptureDeadlineError};
use crate::internal::web_capture::{
    BrowserBoundsError, BrowserByteDomain, BrowserCaptureSpecError, BrowserFamilyCapabilities,
    BrowserInstrumentationMode, NavigationCompletionPolicy,
};
use thiserror::Error;

use crate::internal::engine::policy::{AcquisitionKind, DocumentRequest};
use crate::internal::web_capture::WebArtifactFamily;

use super::PolicyResolutionContextKind;

/// Failure to prepare a complete attempt-specific capture specification.
#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum PolicyResolutionError {
    /// The selected attempt does not belong to the supplied prepared request.
    #[error("prepared attempt does not belong to the supplied prepared page request")]
    PreparedAttemptNotInRequest,
    /// The policy selected a different acquisition context than the caller supplied.
    #[error(
        "policy acquisition {policy_acquisition:?} does not match supplied {supplied_context:?} context"
    )]
    AcquisitionContextMismatch {
        /// The acquisition selected by the policy.
        policy_acquisition: AcquisitionKind,
        /// The provider context supplied by the caller.
        supplied_context: PolicyResolutionContextKind,
    },
    /// The selected acquisition cannot produce the requested document view.
    #[error("{acquisition:?} cannot produce requested document {document:?}")]
    UnsupportedDocument {
        /// Acquisition selected for this prepared attempt.
        acquisition: AcquisitionKind,
        /// Public document request that is unsupported by its adapter.
        document: DocumentRequest,
    },
    /// The Direct HTTP executor does not support the selected transport profile.
    #[error("Direct HTTP execution requires the Standard transport profile")]
    UnsupportedDirectHttpProfile,
    /// The Direct HTTP executor does not support runtime-provided session state.
    #[error("Direct HTTP execution requires an isolated session")]
    UnsupportedDirectHttpSession,
    /// The concrete browser adapter cannot execute this navigation completion mode.
    #[error("browser execution does not support completion mode {completion:?}")]
    UnsupportedBrowserCompletion {
        completion: NavigationCompletionPolicy,
    },
    /// The concrete browser adapter's escalation state does not match its collectors.
    #[error("browser instrumentation {instrumentation:?} does not match resolved collectors")]
    BrowserInstrumentationMismatch {
        instrumentation: BrowserInstrumentationMode,
    },
    /// A checked byte limit failed conversion to the capture-domain quantity.
    #[error("policy byte limit could not be represented by the capture specification")]
    ByteLimitConversion(#[from] ByteLimitError),
    /// A policy deadline failed conversion to the shared capture deadline.
    #[error("policy deadline could not be represented by the capture specification")]
    DeadlineConversion(#[from] CaptureDeadlineError),
    /// A positive policy value unexpectedly failed nonzero conversion.
    #[error("a validated policy count could not be represented as a positive browser bound")]
    InvalidBrowserBound,
    /// The canonical Direct HTTP spec rejected its resolved values.
    #[error("Direct HTTP capture specification rejected the resolved policy")]
    DirectHttpSpec(#[from] DirectHttpCaptureSpecError),
    /// The canonical browser spec rejected its resolved values or certification.
    #[error("browser capture specification rejected the resolved policy")]
    BrowserSpec(#[from] BrowserCaptureSpecError),
    /// Canonical browser bounds rejected policy-mapped limits.
    #[error("browser capture bounds rejected the resolved policy limits")]
    BrowserBounds(#[from] BrowserBoundsError),
    /// A certified browser family list was unexpectedly incomplete.
    #[error("browser certification has no status for {family:?}")]
    MissingBrowserCapability { family: WebArtifactFamily },
    /// The existing browser capture model has no byte domain for requested evidence.
    #[error("browser capture has no byte domain for requested family {family:?}")]
    MissingBrowserByteDomain { family: WebArtifactFamily },
    /// A provider byte domain was not part of this attempt's policy resolution.
    #[error("unexpected browser byte domain for policy resolution: {domain:?}")]
    UnexpectedBrowserByteDomain { domain: BrowserByteDomain },
}

impl PolicyResolutionError {
    pub(in crate::internal::engine) fn required_capability_error(
        capabilities: &BrowserFamilyCapabilities,
        family: WebArtifactFamily,
    ) -> Option<Self> {
        match capabilities.get(family) {
            Some(status) if status.is_supported() => None,
            Some(_) => Some(Self::BrowserSpec(
                BrowserCaptureSpecError::RequiredCapabilityMismatch { family },
            )),
            None => Some(Self::MissingBrowserCapability { family }),
        }
    }
}
