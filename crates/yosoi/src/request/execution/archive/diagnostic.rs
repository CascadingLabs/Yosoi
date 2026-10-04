use yosoi_archive::{
    RequestAttemptDiagnostic, RequestAttemptFailureKind, RequestDirectHttpRedirectDiagnostic,
    RequestDirectHttpTransportDiagnostic,
};
use yosoi_web_capture_direct_http::{DirectHttpRedirectErrorKind, DirectHttpTransportErrorKind};

use super::super::{AttemptDiagnostic, AttemptFailureKind};

pub(super) const fn failure_kind(kind: AttemptFailureKind) -> RequestAttemptFailureKind {
    match kind {
        AttemptFailureKind::MissingExecutionContext => {
            RequestAttemptFailureKind::MissingExecutionContext
        }
        AttemptFailureKind::PolicyResolution => RequestAttemptFailureKind::PolicyResolution,
        AttemptFailureKind::CaptureExecution => RequestAttemptFailureKind::CaptureExecution,
        AttemptFailureKind::Projection => RequestAttemptFailureKind::Projection,
    }
}

pub(super) const fn diagnostic(value: AttemptDiagnostic) -> RequestAttemptDiagnostic {
    match value {
        AttemptDiagnostic::MissingExecutionContext => {
            RequestAttemptDiagnostic::MissingExecutionContext
        }
        AttemptDiagnostic::PolicyResolutionFailed => {
            RequestAttemptDiagnostic::PolicyResolutionFailed
        }
        AttemptDiagnostic::DirectHttpTransport(kind) => {
            RequestAttemptDiagnostic::DirectHttpTransport(direct_http_transport(kind))
        }
        AttemptDiagnostic::DirectHttpBodyFailed => RequestAttemptDiagnostic::DirectHttpBodyFailed,
        AttemptDiagnostic::DirectHttpFinalizationFailed => {
            RequestAttemptDiagnostic::DirectHttpFinalizationFailed
        }
        AttemptDiagnostic::BrowserCancelled => RequestAttemptDiagnostic::BrowserCancelled,
        AttemptDiagnostic::BrowserCancelledCleanupFailed => {
            RequestAttemptDiagnostic::BrowserCancelledCleanupFailed
        }
        AttemptDiagnostic::BrowserCleanupFailed => RequestAttemptDiagnostic::BrowserCleanupFailed,
        AttemptDiagnostic::BrowserCaptureFailed => RequestAttemptDiagnostic::BrowserCaptureFailed,
        AttemptDiagnostic::BrowserFailure(reason) => {
            RequestAttemptDiagnostic::BrowserFailure(reason)
        }
        AttemptDiagnostic::BrowserFinalizationFailed => {
            RequestAttemptDiagnostic::BrowserFinalizationFailed
        }
        AttemptDiagnostic::BrowserFeatureDisabled => {
            RequestAttemptDiagnostic::BrowserFeatureDisabled
        }
        AttemptDiagnostic::ProjectionFailed => RequestAttemptDiagnostic::ProjectionFailed,
    }
}

const fn direct_http_transport(
    value: DirectHttpTransportErrorKind,
) -> RequestDirectHttpTransportDiagnostic {
    match value {
        DirectHttpTransportErrorKind::Dns => RequestDirectHttpTransportDiagnostic::Dns,
        DirectHttpTransportErrorKind::Connect => RequestDirectHttpTransportDiagnostic::Connect,
        DirectHttpTransportErrorKind::Tls => RequestDirectHttpTransportDiagnostic::Tls,
        DirectHttpTransportErrorKind::Timeout => RequestDirectHttpTransportDiagnostic::Timeout,
        DirectHttpTransportErrorKind::Protocol => RequestDirectHttpTransportDiagnostic::Protocol,
        DirectHttpTransportErrorKind::Client => RequestDirectHttpTransportDiagnostic::Client,
        DirectHttpTransportErrorKind::Cancelled => RequestDirectHttpTransportDiagnostic::Cancelled,
        DirectHttpTransportErrorKind::UnsupportedProfile => {
            RequestDirectHttpTransportDiagnostic::UnsupportedProfile
        }
        DirectHttpTransportErrorKind::UnsupportedSession => {
            RequestDirectHttpTransportDiagnostic::UnsupportedSession
        }
        DirectHttpTransportErrorKind::UnsupportedRedirects => {
            RequestDirectHttpTransportDiagnostic::UnsupportedRedirects
        }
        DirectHttpTransportErrorKind::Redirect(kind) => {
            RequestDirectHttpTransportDiagnostic::Redirect(direct_http_redirect(kind))
        }
    }
}

const fn direct_http_redirect(
    value: DirectHttpRedirectErrorKind,
) -> RequestDirectHttpRedirectDiagnostic {
    match value {
        DirectHttpRedirectErrorKind::MissingLocation => {
            RequestDirectHttpRedirectDiagnostic::MissingLocation
        }
        DirectHttpRedirectErrorKind::MalformedLocation => {
            RequestDirectHttpRedirectDiagnostic::MalformedLocation
        }
        DirectHttpRedirectErrorKind::CredentialsNotAllowed => {
            RequestDirectHttpRedirectDiagnostic::CredentialsNotAllowed
        }
        DirectHttpRedirectErrorKind::UnsupportedScheme => {
            RequestDirectHttpRedirectDiagnostic::UnsupportedScheme
        }
        DirectHttpRedirectErrorKind::TargetRefused => {
            RequestDirectHttpRedirectDiagnostic::TargetRefused
        }
        DirectHttpRedirectErrorKind::Loop => RequestDirectHttpRedirectDiagnostic::Loop,
        DirectHttpRedirectErrorKind::HopLimit => RequestDirectHttpRedirectDiagnostic::HopLimit,
    }
}

#[cfg(test)]
mod tests {
    use super::{AttemptDiagnostic, RequestAttemptDiagnostic, diagnostic};
    use crate::BrowserFailureReason;

    #[test]
    #[allow(clippy::panic_in_result_fn)] // Assertions intentionally fail archive contract checks.
    fn detailed_browser_failures_are_retained_in_archive_v1() -> Result<(), serde_json::Error> {
        for reason in [
            BrowserFailureReason::Launch,
            BrowserFailureReason::Connection,
            BrowserFailureReason::Navigation,
            BrowserFailureReason::Timeout,
            BrowserFailureReason::DisplayUnavailable,
            BrowserFailureReason::EnvironmentMismatch,
            BrowserFailureReason::ProfileUnavailable,
            BrowserFailureReason::Unavailable,
            BrowserFailureReason::CapacityExhausted,
            BrowserFailureReason::Closed,
            BrowserFailureReason::RendererCrashed,
            BrowserFailureReason::UnsupportedConfiguration,
        ] {
            let persisted = diagnostic(AttemptDiagnostic::BrowserFailure(reason));
            assert_eq!(persisted, RequestAttemptDiagnostic::BrowserFailure(reason));
            let encoded = serde_json::to_vec(&persisted)?;
            let decoded: RequestAttemptDiagnostic = serde_json::from_slice(&encoded)?;
            assert_eq!(decoded, persisted);
        }
        assert_eq!(yosoi_archive::ARCHIVE_FORMAT_VERSION, 1);
        Ok(())
    }
}
