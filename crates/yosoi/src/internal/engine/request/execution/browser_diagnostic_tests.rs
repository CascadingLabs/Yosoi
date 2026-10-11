use crate::internal::web_capture::{
    BrowserExecutionManagerError, CleanupState, VoidCrawlAdapterError,
    VoidCrawlAdapterErrorCategory,
};

use super::{AttemptDiagnostic, BrowserFailureReason, browser_error_diagnostic};

#[test]
fn browser_diagnostics_classify_provider_and_adapter_failures_without_raw_values() {
    let cases = [
        (
            VoidCrawlAdapterError::Provider {
                code: "voidcrawl.browser.launch_failed",
                category: VoidCrawlAdapterErrorCategory::ProviderFailure,
            },
            BrowserFailureReason::Launch,
        ),
        (
            VoidCrawlAdapterError::Provider {
                code: "voidcrawl.browser.connection_failed",
                category: VoidCrawlAdapterErrorCategory::ProviderFailure,
            },
            BrowserFailureReason::Connection,
        ),
        (
            VoidCrawlAdapterError::Provider {
                code: "voidcrawl.navigation.failed",
                category: VoidCrawlAdapterErrorCategory::ProviderFailure,
            },
            BrowserFailureReason::Navigation,
        ),
        (
            VoidCrawlAdapterError::Provider {
                code: "voidcrawl.renderer.crashed",
                category: VoidCrawlAdapterErrorCategory::ProviderFailure,
            },
            BrowserFailureReason::RendererCrashed,
        ),
        (
            VoidCrawlAdapterError::Provider {
                code: "voidcrawl.navigation.timeout",
                category: VoidCrawlAdapterErrorCategory::Timeout,
            },
            BrowserFailureReason::Timeout,
        ),
        (
            VoidCrawlAdapterError::HeadfulDisplayUnavailable,
            BrowserFailureReason::DisplayUnavailable,
        ),
        (
            VoidCrawlAdapterError::EnvironmentMismatch {
                field: "private-value",
            },
            BrowserFailureReason::EnvironmentMismatch,
        ),
        (
            VoidCrawlAdapterError::DeadlineBeforeOwnership,
            BrowserFailureReason::Timeout,
        ),
    ];
    for (source, expected) in cases {
        let (diagnostic, cleanup) = browser_error_diagnostic(&source);
        assert_eq!(diagnostic, AttemptDiagnostic::BrowserFailure(expected));
        assert_eq!(cleanup, None);
        assert!(!format!("{diagnostic:?}").contains("private-value"));
    }
    let unknown = VoidCrawlAdapterError::Provider {
        code: "private-unknown-provider-code",
        category: VoidCrawlAdapterErrorCategory::UnknownFuture,
    };
    let diagnostic = browser_error_diagnostic(&unknown).0;
    assert_eq!(diagnostic, AttemptDiagnostic::BrowserCaptureFailed);
    assert!(!format!("{diagnostic:?}").contains("private-unknown"));
}

#[test]
fn browser_diagnostics_classify_admission_and_preserve_cancellation_cleanup() {
    for (source, expected) in [
        (
            BrowserExecutionManagerError::ProviderUnavailable,
            BrowserFailureReason::Unavailable,
        ),
        (
            BrowserExecutionManagerError::QueueFull,
            BrowserFailureReason::CapacityExhausted,
        ),
        (
            BrowserExecutionManagerError::ManagedProfileUnavailable,
            BrowserFailureReason::ProfileUnavailable,
        ),
    ] {
        assert_eq!(
            browser_error_diagnostic(&VoidCrawlAdapterError::BrowserExecution(source)).0,
            AttemptDiagnostic::BrowserFailure(expected)
        );
    }
    assert_eq!(
        browser_error_diagnostic(&VoidCrawlAdapterError::BrowserExecution(
            BrowserExecutionManagerError::CallerCancelled
        ))
        .0,
        AttemptDiagnostic::BrowserCancelled
    );
    let failed_cleanup = VoidCrawlAdapterError::PrimaryAndCleanup {
        primary: Box::new(VoidCrawlAdapterError::CancelledBeforeOwnership),
        cleanup: "private-cleanup-detail",
    };
    assert_eq!(
        browser_error_diagnostic(&failed_cleanup),
        (
            AttemptDiagnostic::BrowserCancelledCleanupFailed,
            Some(CleanupState::Failed)
        )
    );
}
