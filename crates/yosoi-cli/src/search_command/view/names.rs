use yosoi::{
    policy::{ProviderDefaultsStatus, search::Provider},
    search::{
        SearchAttemptDiagnostic, SearchFailure, SearchIssueKind, SearchTermination,
        SearchUnavailableReason,
    },
};

pub(in crate::search_command) const fn provider_name(provider: Provider) -> &'static str {
    match provider {
        Provider::Brave => "brave",
        Provider::Bing => "bing",
        Provider::DuckDuckGo => "duckduckgo",
    }
}

pub(in crate::search_command) const fn defaults_status_name(
    status: ProviderDefaultsStatus,
) -> &'static str {
    match status {
        ProviderDefaultsStatus::Unavailable { .. } => "unavailable",
        ProviderDefaultsStatus::Preview { .. } => "preview",
        ProviderDefaultsStatus::Certified { .. } => "certified",
        ProviderDefaultsStatus::Exact => "exact",
    }
}

pub(in crate::search_command) const fn attempt_diagnostic_name(
    diagnostic: SearchAttemptDiagnostic,
) -> &'static str {
    match diagnostic {
        SearchAttemptDiagnostic::MissingExecutionContext => "missing_execution_context",
        SearchAttemptDiagnostic::PolicyResolutionFailed => "policy_resolution_failed",
        SearchAttemptDiagnostic::DirectHttpTransport => "direct_http_transport",
        SearchAttemptDiagnostic::DirectHttpBodyFailed => "direct_http_body_failed",
        SearchAttemptDiagnostic::DirectHttpFinalizationFailed => "direct_http_finalization_failed",
        SearchAttemptDiagnostic::BrowserCancelled => "browser_cancelled",
        SearchAttemptDiagnostic::BrowserCancelledCleanupFailed => {
            "browser_cancelled_cleanup_failed"
        }
        SearchAttemptDiagnostic::BrowserCleanupFailed => "browser_cleanup_failed",
        SearchAttemptDiagnostic::BrowserCaptureFailed => "browser_capture_failed",
        SearchAttemptDiagnostic::BrowserFinalizationFailed => "browser_finalization_failed",
        SearchAttemptDiagnostic::BrowserFeatureDisabled => "browser_feature_disabled",
        SearchAttemptDiagnostic::ProjectionFailed => "projection_failed",
    }
}

pub(in crate::search_command) const fn failure_name(failure: SearchFailure) -> &'static str {
    match failure {
        SearchFailure::RateLimited => "rate_limited",
        SearchFailure::Challenge => "challenge",
        SearchFailure::ProviderUnavailable => "provider_unavailable",
        SearchFailure::MalformedResponse => "malformed_response",
        SearchFailure::QueryMismatch => "query_mismatch",
        SearchFailure::TransportFailure => "transport_failure",
        SearchFailure::BudgetExhausted => "budget_exhausted",
    }
}

pub(in crate::search_command) const fn unavailable_name(
    reason: SearchUnavailableReason,
) -> &'static str {
    match reason {
        SearchUnavailableReason::DefaultUncertified => "default_uncertified",
        SearchUnavailableReason::AdapterUnavailable => "adapter_unavailable",
        SearchUnavailableReason::UnsupportedCapability => "unsupported_capability",
        SearchUnavailableReason::Cancelled => "cancelled",
        SearchUnavailableReason::DeadlineReached => "deadline_reached",
        SearchUnavailableReason::RequestSetupFailed => "request_setup_failed",
    }
}

pub(in crate::search_command) const fn termination_name(
    termination: SearchTermination,
) -> &'static str {
    match termination {
        SearchTermination::Completed => "completed",
        SearchTermination::Cancelled => "cancelled",
        SearchTermination::DeadlineReached => "deadline_reached",
    }
}

pub(in crate::search_command) const fn issue_name(kind: SearchIssueKind) -> &'static str {
    match kind {
        SearchIssueKind::InvalidDestination => "invalid_destination",
        SearchIssueKind::DuplicateDestination => "duplicate_destination",
        SearchIssueKind::MissingRequiredField => "missing_required_field",
        SearchIssueKind::UnrecognizedResultRow => "unrecognized_result_row",
        SearchIssueKind::OutputLimit => "output_limit",
        SearchIssueKind::QueryRelaxed => "query_relaxed",
    }
}
