use super::super::{VoidCrawlAdapterError, VoidCrawlAdapterErrorCategory};
use crate as yosoi;

pub(super) fn cleanup_completed(cleanup: &yosoi::BrowserExecutionCleanupReceipt) -> bool {
    cleanup.context() == yosoi::BrowserContextCleanupDisposition::Completed
        && !matches!(
            cleanup.process(),
            yosoi::BrowserProcessCleanupDisposition::DeadlineExceeded
                | yosoi::BrowserProcessCleanupDisposition::Failed
        )
}

pub(super) const fn cleanup_receipt_for_error(
    admission: yosoi::BrowserExecutionAdmissionReceipt,
    error: crate::BrowserExecutionManagerError,
) -> yosoi::BrowserExecutionCleanupReceipt {
    let (context, process) = cleanup_dispositions_for_error(error);
    yosoi::BrowserExecutionCleanupReceipt::new(admission, context, process)
}

pub(super) const fn cleanup_dispositions_for_error(
    error: crate::BrowserExecutionManagerError,
) -> (
    yosoi::BrowserContextCleanupDisposition,
    yosoi::BrowserProcessCleanupDisposition,
) {
    match error {
        crate::BrowserExecutionManagerError::ContextCleanupDeadline => (
            yosoi::BrowserContextCleanupDisposition::DeadlineExceeded,
            yosoi::BrowserProcessCleanupDisposition::DeadlineExceeded,
        ),
        crate::BrowserExecutionManagerError::ProcessCloseDeadline => (
            yosoi::BrowserContextCleanupDisposition::Completed,
            yosoi::BrowserProcessCleanupDisposition::DeadlineExceeded,
        ),
        crate::BrowserExecutionManagerError::ProcessCloseFailed => (
            yosoi::BrowserContextCleanupDisposition::Completed,
            yosoi::BrowserProcessCleanupDisposition::Failed,
        ),
        crate::BrowserExecutionManagerError::QueueFull
        | crate::BrowserExecutionManagerError::QueueWaitDeadline
        | crate::BrowserExecutionManagerError::CallerCancelled
        | crate::BrowserExecutionManagerError::ManagerClosing
        | crate::BrowserExecutionManagerError::ProviderUnavailable
        | crate::BrowserExecutionManagerError::IndependentLeaseHasNoAdditionalTabs
        | crate::BrowserExecutionManagerError::GlobalTabCapacity
        | crate::BrowserExecutionManagerError::SessionTabCapacity
        | crate::BrowserExecutionManagerError::TabReleased
        | crate::BrowserExecutionManagerError::TabCloseFailed
        | crate::BrowserExecutionManagerError::ContextCleanupFailed
        | crate::BrowserExecutionManagerError::ContextAndProcessCleanupFailed
        | crate::BrowserExecutionManagerError::ManagedProfileUnavailable
        | crate::BrowserExecutionManagerError::ManagedProfileExpired
        | crate::BrowserExecutionManagerError::ManagedProfileOwnershipUncertain
        | crate::BrowserExecutionManagerError::ManagedProfileChildExpired
        | crate::BrowserExecutionManagerError::ManagedProfileChildNotCommitted
        | crate::BrowserExecutionManagerError::ManagedProfileChildContractUnavailable
        | crate::BrowserExecutionManagerError::InvalidManagedProfileLimits
        | crate::BrowserExecutionManagerError::InvalidManagedProfileLeaseDuration
        | crate::BrowserExecutionManagerError::ManagedProfileRequiresSessionScope
        | crate::BrowserExecutionManagerError::InternalInvariant => (
            yosoi::BrowserContextCleanupDisposition::Failed,
            yosoi::BrowserProcessCleanupDisposition::Failed,
        ),
    }
}

pub(super) fn managed_terminal_reason(
    finished: &Result<yosoi::BrowserAdapterResult, VoidCrawlAdapterError>,
    primary_terminal_reason: Option<yosoi::BrowserExecutionTerminalReason>,
    cleanup: &yosoi::BrowserExecutionCleanupReceipt,
) -> yosoi::BrowserExecutionTerminalReason {
    match finished {
        Err(error) => terminal_reason_for_error(error),
        Ok(result) if result.is_ready() => yosoi::BrowserExecutionTerminalReason::Completed,
        Ok(result) => terminal_reason_for_result(result, primary_terminal_reason, cleanup),
    }
}

fn terminal_reason_for_result(
    result: &yosoi::BrowserAdapterResult,
    primary_terminal_reason: Option<yosoi::BrowserExecutionTerminalReason>,
    cleanup: &yosoi::BrowserExecutionCleanupReceipt,
) -> yosoi::BrowserExecutionTerminalReason {
    match result.terminal().kind() {
        yosoi::BrowserTerminalKind::DeadlineReached { .. } => {
            yosoi::BrowserExecutionTerminalReason::DeadlineExceeded
        }
        yosoi::BrowserTerminalKind::SystemInterrupted { .. } => {
            yosoi::BrowserExecutionTerminalReason::SystemInterrupted
        }
        yosoi::BrowserTerminalKind::CallerCancelled { .. } => {
            yosoi::BrowserExecutionTerminalReason::CallerCancelled
        }
        yosoi::BrowserTerminalKind::ProviderStopped {
            reason: yosoi::BrowserProviderStop::BrowserDisconnected,
        } => yosoi::BrowserExecutionTerminalReason::ProviderDisconnected,
        yosoi::BrowserTerminalKind::ProviderStopped {
            reason: yosoi::BrowserProviderStop::CleanupFailure,
        } => terminal_reason_for_cleanup(cleanup),
        yosoi::BrowserTerminalKind::EventLimitReached
        | yosoi::BrowserTerminalKind::ByteLimitReached { .. } => {
            yosoi::BrowserExecutionTerminalReason::ObservationLimitExceeded
        }
        yosoi::BrowserTerminalKind::ProviderStopped { .. } => primary_terminal_reason
            .unwrap_or(yosoi::BrowserExecutionTerminalReason::ProviderFailure),
        yosoi::BrowserTerminalKind::QuietSettled
        | yosoi::BrowserTerminalKind::ControllerCompleted => {
            yosoi::BrowserExecutionTerminalReason::Completed
        }
    }
}

pub(super) const fn terminal_reason_for_cleanup(
    cleanup: &yosoi::BrowserExecutionCleanupReceipt,
) -> yosoi::BrowserExecutionTerminalReason {
    match cleanup.context() {
        yosoi::BrowserContextCleanupDisposition::Failed => {
            yosoi::BrowserExecutionTerminalReason::ContextCleanupFailed
        }
        yosoi::BrowserContextCleanupDisposition::DeadlineExceeded => {
            yosoi::BrowserExecutionTerminalReason::ContextCleanupDeadlineExceeded
        }
        yosoi::BrowserContextCleanupDisposition::Completed => match cleanup.process() {
            yosoi::BrowserProcessCleanupDisposition::Failed => {
                yosoi::BrowserExecutionTerminalReason::ProcessCleanupFailed
            }
            yosoi::BrowserProcessCleanupDisposition::DeadlineExceeded => {
                yosoi::BrowserExecutionTerminalReason::ProcessCleanupDeadlineExceeded
            }
            yosoi::BrowserProcessCleanupDisposition::WarmRetained
            | yosoi::BrowserProcessCleanupDisposition::NotRequired
            | yosoi::BrowserProcessCleanupDisposition::Completed => {
                yosoi::BrowserExecutionTerminalReason::InternalInvariantFailure
            }
        },
    }
}

pub(super) fn terminal_reason_for_error(
    error: &VoidCrawlAdapterError,
) -> yosoi::BrowserExecutionTerminalReason {
    match error {
        VoidCrawlAdapterError::CancelledBeforeOwnership
        | VoidCrawlAdapterError::CancelledBeforeStaging => {
            yosoi::BrowserExecutionTerminalReason::CallerCancelled
        }
        VoidCrawlAdapterError::DeadlineBeforeOwnership
        | VoidCrawlAdapterError::DeadlineBeforeStaging
        | VoidCrawlAdapterError::ObservationFinalizationDeadline
        | VoidCrawlAdapterError::NavigationFinalizationDeadline => {
            yosoi::BrowserExecutionTerminalReason::DeadlineExceeded
        }
        VoidCrawlAdapterError::Provider {
            code: "voidcrawl.browser.closed",
            ..
        } => yosoi::BrowserExecutionTerminalReason::ProviderDisconnected,
        VoidCrawlAdapterError::Provider {
            category: VoidCrawlAdapterErrorCategory::Unavailable,
            ..
        } => yosoi::BrowserExecutionTerminalReason::ProviderUnavailable,
        VoidCrawlAdapterError::BrowserExecution(error) => terminal_reason_for_manager_error(*error),
        VoidCrawlAdapterError::ContextDisposal => {
            yosoi::BrowserExecutionTerminalReason::ContextCleanupFailed
        }
        VoidCrawlAdapterError::SessionClose => {
            yosoi::BrowserExecutionTerminalReason::ProcessCleanupFailed
        }
        VoidCrawlAdapterError::CapabilityMismatch
        | VoidCrawlAdapterError::EnvironmentMismatch { .. }
        | VoidCrawlAdapterError::EnvironmentNumberMismatch { .. }
        | VoidCrawlAdapterError::InvalidEnvironment
        | VoidCrawlAdapterError::InvalidStaging
        | VoidCrawlAdapterError::InvalidOutput(_)
        | VoidCrawlAdapterError::InvalidResolvedSpec => {
            yosoi::BrowserExecutionTerminalReason::InternalInvariantFailure
        }
        VoidCrawlAdapterError::PrimaryAndCleanup { primary, .. }
        | VoidCrawlAdapterError::ManagedExecution { primary, .. } => {
            terminal_reason_for_error(primary)
        }
        VoidCrawlAdapterError::AttemptStopped
        | VoidCrawlAdapterError::UnsupportedNavigationPolicy
        | VoidCrawlAdapterError::UnsupportedFamily { .. }
        | VoidCrawlAdapterError::SourceRequiresFinalizationBoundary
        | VoidCrawlAdapterError::UnsupportedIsolation
        | VoidCrawlAdapterError::HeadfulDisplayUnavailable
        | VoidCrawlAdapterError::Provider { .. }
        | VoidCrawlAdapterError::UnsupportedRecording
        | VoidCrawlAdapterError::SourceRepresentation(_) => {
            yosoi::BrowserExecutionTerminalReason::ProviderFailure
        }
    }
}

pub(super) const fn terminal_reason_for_manager_error(
    error: crate::BrowserExecutionManagerError,
) -> yosoi::BrowserExecutionTerminalReason {
    match error {
        crate::BrowserExecutionManagerError::CallerCancelled => {
            yosoi::BrowserExecutionTerminalReason::CallerCancelled
        }
        crate::BrowserExecutionManagerError::QueueWaitDeadline
        | crate::BrowserExecutionManagerError::ManagedProfileExpired
        | crate::BrowserExecutionManagerError::ManagedProfileChildExpired => {
            yosoi::BrowserExecutionTerminalReason::DeadlineExceeded
        }
        crate::BrowserExecutionManagerError::ManagerClosing => {
            yosoi::BrowserExecutionTerminalReason::SystemInterrupted
        }
        crate::BrowserExecutionManagerError::ProviderUnavailable => {
            yosoi::BrowserExecutionTerminalReason::ProviderUnavailable
        }
        crate::BrowserExecutionManagerError::TabCloseFailed => {
            yosoi::BrowserExecutionTerminalReason::TabCloseFailed
        }
        crate::BrowserExecutionManagerError::ContextCleanupDeadline => {
            yosoi::BrowserExecutionTerminalReason::ContextCleanupDeadlineExceeded
        }
        crate::BrowserExecutionManagerError::ContextCleanupFailed
        | crate::BrowserExecutionManagerError::ContextAndProcessCleanupFailed => {
            yosoi::BrowserExecutionTerminalReason::ContextCleanupFailed
        }
        crate::BrowserExecutionManagerError::ProcessCloseDeadline => {
            yosoi::BrowserExecutionTerminalReason::ProcessCleanupDeadlineExceeded
        }
        crate::BrowserExecutionManagerError::ProcessCloseFailed
        | crate::BrowserExecutionManagerError::ManagedProfileOwnershipUncertain => {
            yosoi::BrowserExecutionTerminalReason::ProcessCleanupFailed
        }
        crate::BrowserExecutionManagerError::InternalInvariant
        | crate::BrowserExecutionManagerError::TabReleased => {
            yosoi::BrowserExecutionTerminalReason::InternalInvariantFailure
        }
        crate::BrowserExecutionManagerError::QueueFull
        | crate::BrowserExecutionManagerError::ManagedProfileUnavailable
        | crate::BrowserExecutionManagerError::ManagedProfileChildNotCommitted
        | crate::BrowserExecutionManagerError::ManagedProfileChildContractUnavailable
        | crate::BrowserExecutionManagerError::InvalidManagedProfileLimits
        | crate::BrowserExecutionManagerError::InvalidManagedProfileLeaseDuration
        | crate::BrowserExecutionManagerError::ManagedProfileRequiresSessionScope
        | crate::BrowserExecutionManagerError::IndependentLeaseHasNoAdditionalTabs
        | crate::BrowserExecutionManagerError::GlobalTabCapacity
        | crate::BrowserExecutionManagerError::SessionTabCapacity => {
            yosoi::BrowserExecutionTerminalReason::ProviderFailure
        }
    }
}
