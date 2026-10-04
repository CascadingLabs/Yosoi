use std::{error::Error, fmt};

use thiserror::Error;
use yosoi_types::NamespacedIdError;

use crate::{
    BoundedAcquisitionLifecycle, CaptureResolution, LifecycleError, ResolvedDirectHttpCaptureSpec,
};

use super::DirectHttpTransportError;

/// A failure encountered while recording termination after the primary transport failure.
///
/// This error is secondary evidence: it never replaces the transport or redirect classification.
#[derive(Debug, Error)]
pub enum DirectHttpTerminationFailure {
    #[error("direct HTTP termination reason was invalid")]
    InvalidReason(#[source] NamespacedIdError),
    #[error("direct HTTP lifecycle termination failed")]
    Lifecycle(#[source] LifecycleError),
}

/// Failed response-head acquisition with its stopped lifecycle retained.
pub struct DirectHttpFailure {
    pub(super) spec: Box<ResolvedDirectHttpCaptureSpec>,
    pub(super) lifecycle: Box<BoundedAcquisitionLifecycle>,
    pub(super) error: DirectHttpTransportError,
    pub(super) response: Option<Box<wreq::Response>>,
    pub(super) resolution: Option<Box<CaptureResolution>>,
    pub(super) termination_failure: Option<DirectHttpTerminationFailure>,
}

impl DirectHttpFailure {
    pub const fn spec(&self) -> &ResolvedDirectHttpCaptureSpec {
        &self.spec
    }
    pub const fn lifecycle(&self) -> &BoundedAcquisitionLifecycle {
        &self.lifecycle
    }
    pub const fn error(&self) -> &DirectHttpTransportError {
        &self.error
    }
    pub fn resolution(&self) -> Option<&CaptureResolution> {
        self.resolution.as_deref()
    }
    pub const fn has_unconsumed_response(&self) -> bool {
        self.response.is_some()
    }
    /// Returns the received response status when redirect handling stopped with an unread body.
    pub fn response_status(&self) -> Option<u16> {
        self.response
            .as_ref()
            .map(|response| response.status().as_u16())
    }
    pub const fn termination_failure(&self) -> Option<&DirectHttpTerminationFailure> {
        self.termination_failure.as_ref()
    }
    /// Transfers all response, resolution, lifecycle, primary, and secondary failure evidence.
    pub fn into_parts(
        self,
    ) -> (
        Option<wreq::Response>,
        Option<CaptureResolution>,
        ResolvedDirectHttpCaptureSpec,
        BoundedAcquisitionLifecycle,
        DirectHttpTransportError,
        Option<DirectHttpTerminationFailure>,
    ) {
        (
            self.response.map(|response| *response),
            self.resolution.map(|resolution| *resolution),
            *self.spec,
            *self.lifecycle,
            self.error,
            self.termination_failure,
        )
    }
}

impl fmt::Display for DirectHttpFailure {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.error.fmt(formatter)
    }
}

impl fmt::Debug for DirectHttpFailure {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("DirectHttpFailure")
            .field("spec", &"[redacted]")
            .field("capture_id", &self.lifecycle.capture_id())
            .field("termination", &self.lifecycle.termination())
            .field("error", &self.error)
            .field("response", &self.response.as_ref().map(|_| "[opaque]"))
            .field(
                "resolution",
                &self.resolution.as_ref().map(|_| "[redacted]"),
            )
            .field("termination_failure", &self.termination_failure)
            .finish()
    }
}

impl Error for DirectHttpFailure {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        Some(&self.error)
    }
}
