use serde::{Deserialize, Serialize};

/// Isolation scope requested for one browser execution lease.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BrowserExecutionScope {
    /// One disposable context and its initial tab for a standalone capture.
    Independent,
    /// One disposable context whose tabs intentionally share session-local state.
    SessionGroup,
}

/// Closed outcome for a request that did not reach provider context ownership.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BrowserExecutionPreAdmissionOutcome {
    QueueFull,
    QueueWaitDeadline,
    CallerCancelled,
    ManagerClosing,
    ProviderUnavailable,
    /// A provider-owned resource could not be cleaned before admission.
    ProviderCleanupFailed,
    /// Cleanup of a provider-owned resource exceeded its configured deadline before admission.
    ProviderCleanupDeadlineExceeded,
    InternalInvariantFailure,
}
