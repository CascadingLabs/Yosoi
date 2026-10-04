use serde::{Deserialize, Serialize};

/// Stable request-level failure category.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RequestAttemptFailureKind {
    MissingExecutionContext,
    PolicyResolution,
    CaptureExecution,
    Projection,
}

/// Stable Direct HTTP redirect failure detail.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RequestDirectHttpRedirectDiagnostic {
    MissingLocation,
    MalformedLocation,
    CredentialsNotAllowed,
    UnsupportedScheme,
    TargetRefused,
    Loop,
    HopLimit,
}

/// Stable Direct HTTP transport failure detail.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RequestDirectHttpTransportDiagnostic {
    Dns,
    Connect,
    Tls,
    Timeout,
    Protocol,
    Client,
    Cancelled,
    UnsupportedProfile,
    UnsupportedSession,
    UnsupportedRedirects,
    Redirect(RequestDirectHttpRedirectDiagnostic),
}

/// Bounded, secret-safe failure diagnostic retained by Archive.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RequestAttemptDiagnostic {
    MissingExecutionContext,
    PolicyResolutionFailed,
    DirectHttpTransport(RequestDirectHttpTransportDiagnostic),
    DirectHttpBodyFailed,
    DirectHttpFinalizationFailed,
    BrowserCancelled,
    BrowserCancelledCleanupFailed,
    BrowserCleanupFailed,
    BrowserCaptureFailed,
    BrowserFinalizationFailed,
    BrowserFeatureDisabled,
    ProjectionFailed,
}

/// Closed reason an authored request attempt never started.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RequestNotStartedReason {
    Cancelled,
}
