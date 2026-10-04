use super::{AttemptDiagnostic, BrowserFailureReason};

pub(super) fn browser_error_diagnostic(
    error: &yosoi_web_capture::VoidCrawlAdapterError,
) -> (AttemptDiagnostic, Option<yosoi_web_capture::CleanupState>) {
    use yosoi_web_capture::{
        BrowserExecutionManagerError as ManagerError, VoidCrawlAdapterError as AdapterError,
        VoidCrawlAdapterErrorCategory as Category,
    };

    let classified = |reason| (AttemptDiagnostic::BrowserFailure(reason), None);
    match error {
        yosoi_web_capture::VoidCrawlAdapterError::CancelledBeforeOwnership
        | yosoi_web_capture::VoidCrawlAdapterError::CancelledBeforeStaging => {
            (AttemptDiagnostic::BrowserCancelled, None)
        }
        yosoi_web_capture::VoidCrawlAdapterError::PrimaryAndCleanup { primary, .. } => (
            if matches!(
                browser_error_diagnostic(primary).0,
                AttemptDiagnostic::BrowserCancelled
                    | AttemptDiagnostic::BrowserCancelledCleanupFailed
            ) {
                AttemptDiagnostic::BrowserCancelledCleanupFailed
            } else {
                AttemptDiagnostic::BrowserCleanupFailed
            },
            Some(yosoi_web_capture::CleanupState::Failed),
        ),
        yosoi_web_capture::VoidCrawlAdapterError::ContextDisposal
        | yosoi_web_capture::VoidCrawlAdapterError::SessionClose => (
            AttemptDiagnostic::BrowserCleanupFailed,
            Some(yosoi_web_capture::CleanupState::Failed),
        ),
        yosoi_web_capture::VoidCrawlAdapterError::ManagedExecution { primary, .. } => {
            browser_error_diagnostic(primary)
        }
        AdapterError::DeadlineBeforeOwnership
        | AdapterError::DeadlineBeforeStaging
        | AdapterError::ObservationFinalizationDeadline
        | AdapterError::NavigationFinalizationDeadline => classified(BrowserFailureReason::Timeout),
        AdapterError::HeadfulDisplayUnavailable => {
            classified(BrowserFailureReason::DisplayUnavailable)
        }
        AdapterError::EnvironmentMismatch { .. }
        | AdapterError::EnvironmentNumberMismatch { .. }
        | AdapterError::InvalidEnvironment
        | AdapterError::CapabilityMismatch => classified(BrowserFailureReason::EnvironmentMismatch),
        AdapterError::UnsupportedNavigationPolicy
        | AdapterError::UnsupportedFamily { .. }
        | AdapterError::UnsupportedIsolation
        | AdapterError::UnsupportedRecording
        | AdapterError::InvalidResolvedSpec
        | AdapterError::SourceRequiresFinalizationBoundary => {
            classified(BrowserFailureReason::UnsupportedConfiguration)
        }
        AdapterError::Provider { code, category } => {
            let reason = match *code {
                "voidcrawl.browser.launch_failed" => Some(BrowserFailureReason::Launch),
                "voidcrawl.browser.connection_failed" => Some(BrowserFailureReason::Connection),
                "voidcrawl.navigation.failed"
                | "voidcrawl.navigation.already_active"
                | "voidcrawl.navigation.state_uncertain"
                | "voidcrawl.page.failed" => Some(BrowserFailureReason::Navigation),
                "voidcrawl.browser.closed" => Some(BrowserFailureReason::Closed),
                "voidcrawl.renderer.crashed" => Some(BrowserFailureReason::RendererCrashed),
                "voidcrawl.profile.busy"
                | "voidcrawl.profile.chrome_busy"
                | "voidcrawl.profile.not_found"
                | "voidcrawl.profile.lease_expired" => {
                    Some(BrowserFailureReason::ProfileUnavailable)
                }
                _ => match category {
                    Category::Timeout => Some(BrowserFailureReason::Timeout),
                    Category::Unavailable => Some(BrowserFailureReason::Unavailable),
                    Category::Unsupported => Some(BrowserFailureReason::UnsupportedConfiguration),
                    _ => None,
                },
            };
            reason.map_or((AttemptDiagnostic::BrowserCaptureFailed, None), classified)
        }
        AdapterError::BrowserExecution(source) => match source {
            ManagerError::CallerCancelled => (AttemptDiagnostic::BrowserCancelled, None),
            ManagerError::QueueWaitDeadline => classified(BrowserFailureReason::Timeout),
            ManagerError::QueueFull
            | ManagerError::GlobalTabCapacity
            | ManagerError::SessionTabCapacity => {
                classified(BrowserFailureReason::CapacityExhausted)
            }
            ManagerError::ProviderUnavailable | ManagerError::ManagerClosing => {
                classified(BrowserFailureReason::Unavailable)
            }
            ManagerError::TabReleased => classified(BrowserFailureReason::Closed),
            ManagerError::ManagedProfileUnavailable
            | ManagerError::ManagedProfileExpired
            | ManagerError::ManagedProfileChildExpired
            | ManagerError::ManagedProfileChildNotCommitted
            | ManagerError::ManagedProfileChildContractUnavailable
            | ManagerError::ManagedProfileOwnershipUncertain => {
                classified(BrowserFailureReason::ProfileUnavailable)
            }
            ManagerError::TabCloseFailed
            | ManagerError::ContextCleanupDeadline
            | ManagerError::ContextCleanupFailed
            | ManagerError::ProcessCloseDeadline
            | ManagerError::ProcessCloseFailed
            | ManagerError::ContextAndProcessCleanupFailed => (
                AttemptDiagnostic::BrowserCleanupFailed,
                Some(yosoi_web_capture::CleanupState::Failed),
            ),
            ManagerError::IndependentLeaseHasNoAdditionalTabs
            | ManagerError::InvalidManagedProfileLimits
            | ManagerError::InvalidManagedProfileLeaseDuration
            | ManagerError::ManagedProfileRequiresSessionScope => {
                classified(BrowserFailureReason::UnsupportedConfiguration)
            }
            ManagerError::InternalInvariant => (AttemptDiagnostic::BrowserCaptureFailed, None),
        },
        AdapterError::AttemptStopped
        | AdapterError::InvalidStaging
        | AdapterError::SourceRepresentation(_)
        | AdapterError::InvalidOutput(_) => (AttemptDiagnostic::BrowserCaptureFailed, None),
    }
}
