//! Direct HTTP adapter around provider-neutral bounded acquisition state.

use chrono::{DateTime, Utc};
use thiserror::Error;
use yosoi_types::{ActivityReceiptError, CaptureReceiptError, NamespacedIdError};

#[path = "lifecycle/finalization.rs"]
mod finalization;
#[cfg(test)]
#[path = "lifecycle/overflow_tests.rs"]
mod overflow_tests;
use crate::{
    AcquisitionObservationError, BoundedAcquisitionError, BoundedAcquisitionLifecycle,
    ByteAccountingError, CaptureBundle, CaptureBundleError, CaptureObservationError,
    EventAccountingError, LifecycleFinalizationInput, ObservationWindowError,
    ResolvedDirectHttpCaptureSpec, WebAcquisitionRecordError, WebCaptureError,
};

#[derive(Debug, Error)]
pub enum LifecycleError {
    #[error("event offset {offered} precedes previously observed offset {previous}")]
    NonMonotonic { offered: u64, previous: u64 },
    #[error("final manifest requests do not equal the resolved specification")]
    ManifestMismatch,
    #[error("{family:?} artifact schema is not declared by the resolved specification")]
    SchemaMismatch { family: crate::WebArtifactFamily },
    #[error("event accounting overflowed")]
    EventOverflow,
    #[error("byte accounting overflowed")]
    ByteOverflow,
    #[error("lifecycle is already stopped")]
    AlreadyStopped,
    #[error("lifecycle must be stopped before finalization")]
    StillRunning,
    #[error("terminal offset {terminal} precedes lifecycle offset {observed}")]
    TerminalOffsetBehind { terminal: u64, observed: u64 },
    #[error("terminal offset does not agree with deterministic stop offset")]
    TerminalOffsetMismatch,
    #[error("artifact generation timestamp is outside the observation window")]
    ArtifactTimestampOutsideWindow,
    #[error("artifact generation timestamps are not ordered")]
    ArtifactTimestampsUnordered,
    #[error("activity outcome contradicts the capture termination")]
    ActivityOutcomeMismatch,
    #[error("acquisition lifecycle finalization failed")]
    AcquisitionObservation(#[source] AcquisitionObservationError),
    #[error("wall-clock observation window is invalid")]
    ObservationWindow(#[source] ObservationWindowError),
    #[error("event accounting is invalid")]
    EventAccounting(#[source] EventAccountingError),
    #[error("byte accounting is invalid")]
    ByteAccounting(#[source] ByteAccountingError),
    #[error("capture observation is invalid")]
    Observation(#[source] CaptureObservationError),
    #[error("activity reason code is invalid")]
    Reason(#[source] NamespacedIdError),
    #[error("activity receipt is invalid")]
    ActivityReceipt(#[source] ActivityReceiptError),
    #[error("capture receipt is invalid")]
    CaptureReceipt(#[source] CaptureReceiptError),
    #[error("acquisition record is invalid")]
    AcquisitionRecord(#[source] WebAcquisitionRecordError),
    #[error("web capture is invalid")]
    WebCapture(#[source] WebCaptureError),
    #[error("capture payload bundle is invalid")]
    Bundle(#[source] CaptureBundleError),
}
impl From<BoundedAcquisitionError> for LifecycleError {
    fn from(error: BoundedAcquisitionError) -> Self {
        match error {
            BoundedAcquisitionError::NonMonotonic { offered, previous } => {
                Self::NonMonotonic { offered, previous }
            }
            BoundedAcquisitionError::EventOverflow => Self::EventOverflow,
            BoundedAcquisitionError::ByteOverflow => Self::ByteOverflow,
            BoundedAcquisitionError::AlreadyStopped => Self::AlreadyStopped,
        }
    }
}

pub(super) fn start(
    spec: &ResolvedDirectHttpCaptureSpec,
    started_at: DateTime<Utc>,
) -> BoundedAcquisitionLifecycle {
    BoundedAcquisitionLifecycle::start(spec.capture_id(), spec.observation().clone(), started_at)
}

/// Applies Direct HTTP manifest invariants, then delegates atomic publication to the shared kernel.
pub fn finalize_direct_http_attempt(
    spec: ResolvedDirectHttpCaptureSpec,
    lifecycle: BoundedAcquisitionLifecycle,
    input: LifecycleFinalizationInput,
) -> Result<CaptureBundle, LifecycleError> {
    finalization::finalize(spec, lifecycle, input)
}

#[cfg(test)]
const fn checked_add_events(current: u64, amount: u64) -> Result<u64, LifecycleError> {
    match current.checked_add(amount) {
        Some(total) => Ok(total),
        None => Err(LifecycleError::EventOverflow),
    }
}

#[cfg(test)]
const fn checked_add_bytes(current: u64, amount: u64) -> Result<u64, LifecycleError> {
    match current.checked_add(amount) {
        Some(total) => Ok(total),
        None => Err(LifecycleError::ByteOverflow),
    }
}
