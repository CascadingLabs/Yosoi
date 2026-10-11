use crate::internal::direct_http as yosoi_web_capture_direct_http;

use std::fmt;

use crate::internal::policy::policy::{AcquisitionKind, DocumentSelectionKind};
use crate::internal::types::CaptureId;

use crate::internal::engine::{
    AppliedPolicy, CaptureArchiveRef, PolicyResolutionError, PolicySnapshot,
};

use super::capture_facts::{AttemptCaptureFacts, AttemptCaptureFailureFacts};

/// Safe reason that one authored attempt failed.
#[derive(Clone, Copy, Debug, Eq, PartialEq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AttemptFailureKind {
    /// No executor context exists for the selected acquisition mechanism.
    MissingExecutionContext,
    /// Authored policy could not resolve into a supported acquisition plan.
    PolicyResolution,
    /// Capture acquisition or finalization failed after preparation.
    CaptureExecution,
    /// Acquired evidence could not produce the requested document representation.
    Projection,
}

pub use crate::internal::types::BrowserFailureReason;

/// Bounded, secret-safe diagnostic classification for one attempt failure.
#[derive(Clone, Copy, Debug, Eq, PartialEq, serde::Serialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum AttemptDiagnostic {
    /// Selected acquisition has no configured execution adapter context.
    MissingExecutionContext,
    /// Request policy resolution failed before dispatch.
    PolicyResolutionFailed,
    /// Direct HTTP transport failed with a bounded provider-independent category.
    DirectHttpTransport(yosoi_web_capture_direct_http::DirectHttpTransportErrorKind),
    /// Response-body acquisition failed before usable finalization.
    DirectHttpBodyFailed,
    /// Direct HTTP capture artifact finalization failed.
    DirectHttpFinalizationFailed,
    /// Browser acquisition observed cancellation.
    BrowserCancelled,
    /// Browser acquisition observed cancellation and also failed cleanup.
    BrowserCancelledCleanupFailed,
    /// Browser cleanup failed independently of cancellation classification.
    BrowserCleanupFailed,
    /// Browser capture failed without a more specific available classification.
    BrowserCaptureFailed,
    /// Browser capture failed with the supplied typed reason.
    BrowserFailure(BrowserFailureReason),
    /// Browser capture could not finalize retained artifacts.
    BrowserFinalizationFailed,
    /// This build lacks the selected browser acquisition feature.
    BrowserFeatureDisabled,
    /// Captured evidence could not be projected into requested document outputs.
    ProjectionFailed,
}

/// Failure of one authored acquisition with its policy and bounded diagnostics.
pub struct AttemptFailure {
    pub(super) capture_id: CaptureId,
    pub(super) acquisition: AcquisitionKind,
    pub(super) authored_selection: DocumentSelectionKind,
    pub(super) requested_target: String,
    pub(super) policy_snapshot: PolicySnapshot,
    pub(super) applied_policy: Option<AppliedPolicy>,
    pub(super) capture_archive_ref: Option<CaptureArchiveRef>,
    pub(super) kind: AttemptFailureKind,
    pub(super) diagnostic: AttemptDiagnostic,
    pub(super) resolution_error: Option<PolicyResolutionError>,
    pub(super) capture_failure_facts: Option<AttemptCaptureFailureFacts>,
    pub(super) capture_facts: Option<AttemptCaptureFacts>,
}

impl AttemptFailure {
    pub const fn capture_id(&self) -> CaptureId {
        self.capture_id
    }
    pub const fn acquisition(&self) -> AcquisitionKind {
        self.acquisition
    }
    pub const fn authored_selection(&self) -> DocumentSelectionKind {
        self.authored_selection
    }
    pub fn requested_target(&self) -> &str {
        &self.requested_target
    }
    pub const fn policy_snapshot(&self) -> &PolicySnapshot {
        &self.policy_snapshot
    }
    pub const fn applied_policy(&self) -> Option<&AppliedPolicy> {
        self.applied_policy.as_ref()
    }
    /// Returns the committed Capture when archival succeeded before a later failure.
    pub const fn capture_archive_ref(&self) -> Option<&CaptureArchiveRef> {
        self.capture_archive_ref.as_ref()
    }
    pub const fn kind(&self) -> AttemptFailureKind {
        self.kind
    }
    pub const fn diagnostic(&self) -> AttemptDiagnostic {
        self.diagnostic
    }
    pub const fn resolution_error(&self) -> Option<&PolicyResolutionError> {
        self.resolution_error.as_ref()
    }
    pub const fn capture_failure_facts(&self) -> Option<&AttemptCaptureFailureFacts> {
        self.capture_failure_facts.as_ref()
    }
    pub const fn capture_facts(&self) -> Option<&AttemptCaptureFacts> {
        self.capture_facts.as_ref()
    }
    pub(super) fn observed_cancellation(&self) -> bool {
        matches!(
            self.diagnostic,
            AttemptDiagnostic::DirectHttpTransport(
                yosoi_web_capture_direct_http::DirectHttpTransportErrorKind::Cancelled
            ) | AttemptDiagnostic::BrowserCancelled
                | AttemptDiagnostic::BrowserCancelledCleanupFailed
        ) || self
            .capture_failure_facts
            .as_ref()
            .is_some_and(AttemptCaptureFailureFacts::observed_cancellation)
            || self
                .capture_facts
                .as_ref()
                .is_some_and(AttemptCaptureFacts::observed_cancellation)
    }
}

impl fmt::Debug for AttemptFailure {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("AttemptFailure")
            .field("capture_id", &self.capture_id)
            .field("acquisition", &self.acquisition)
            .field("authored_selection", &self.authored_selection)
            .field("requested_target", &"[redacted]")
            .field("kind", &self.kind)
            .field("diagnostic", &self.diagnostic)
            .field("resolution_error", &self.resolution_error)
            .field(
                "has_capture_archive_ref",
                &self.capture_archive_ref.is_some(),
            )
            .field("capture_failure_facts", &self.capture_failure_facts)
            .field("has_capture_facts", &self.capture_facts.is_some())
            .finish_non_exhaustive()
    }
}

/// Planned acquisition that was not invoked because cancellation was observed.
pub struct NotStartedAttempt {
    pub(super) planned_capture_id: CaptureId,
    pub(super) acquisition: AcquisitionKind,
    pub(super) authored_selection: DocumentSelectionKind,
    pub(super) requested_target: String,
    pub(super) policy_snapshot: PolicySnapshot,
    pub(super) reason: NotStartedReason,
}

impl NotStartedAttempt {
    pub const fn planned_capture_id(&self) -> CaptureId {
        self.planned_capture_id
    }
    pub const fn acquisition(&self) -> AcquisitionKind {
        self.acquisition
    }
    pub const fn authored_selection(&self) -> DocumentSelectionKind {
        self.authored_selection
    }
    pub fn requested_target(&self) -> &str {
        &self.requested_target
    }
    pub const fn policy_snapshot(&self) -> &PolicySnapshot {
        &self.policy_snapshot
    }
    pub const fn reason(&self) -> NotStartedReason {
        self.reason
    }
}

impl fmt::Debug for NotStartedAttempt {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("NotStartedAttempt")
            .field("planned_capture_id", &self.planned_capture_id)
            .field("acquisition", &self.acquisition)
            .field("authored_selection", &self.authored_selection)
            .field("requested_target", &"[redacted]")
            .field("reason", &self.reason)
            .finish_non_exhaustive()
    }
}

/// Reason a planned acquisition never started, retained instead of silently dropping its slot.
#[derive(Clone, Copy, Debug, Eq, PartialEq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NotStartedReason {
    /// Execution observed cancellation before this authored acquisition was invoked.
    Cancelled,
}
