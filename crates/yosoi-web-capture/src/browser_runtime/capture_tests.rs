use super::*;
use std::ffi::OsStr;

#[test]
fn headful_display_detection_accepts_supported_displays_only() {
    assert!(!headful_display_configured(None, None));
    assert!(!headful_display_configured(
        Some(OsStr::new("")),
        Some(OsStr::new(""))
    ));
    assert!(headful_display_configured(Some(OsStr::new(":0")), None));
    assert!(headful_display_configured(
        None,
        Some(OsStr::new("wayland-0"))
    ));
}

#[test]
fn renderer_crash_maps_to_the_shared_renderer_failure_terminal() {
    let error = VoidCrawlAdapterError::Provider {
        code: "voidcrawl.renderer.crashed",
        category: VoidCrawlAdapterErrorCategory::ProviderFailure,
    };
    assert_eq!(
        provider_stop(&error, false),
        yosoi::BrowserProviderStop::RendererFailure
    );
    assert_eq!(
        provider_stop(&error, true),
        yosoi::BrowserProviderStop::RendererFailure
    );
}

fn navigation_report(
    termination: provider::NavigationCaptureTermination,
) -> provider::NavigationCaptureReport {
    provider::NavigationCaptureReport {
        started_at_unix_ms: None,
        elapsed_micros: 7,
        termination,
        requested_url: None,
        final_url: None,
        redirects: Vec::new(),
        main_document: None,
        resources: Vec::new(),
        events: Vec::new(),
        events_admitted: 0,
        events_retained: 0,
        events_dropped: provider::MeasuredCount::Known { value: 0 },
        resources_dropped: 0,
        additional_loss_unknown: false,
        network_extra_info: provider::NetworkExtraInfoState::UnavailableInCurrentClient,
        cleanup_complete: true,
    }
}

#[test]
fn managed_cleanup_error_mapping_preserves_resource_and_deadline() {
    use crate::BrowserExecutionManagerError as Error;
    let cases = [
        (
            Error::ContextCleanupDeadline,
            yosoi::BrowserContextCleanupDisposition::DeadlineExceeded,
            yosoi::BrowserProcessCleanupDisposition::DeadlineExceeded,
        ),
        (
            Error::ContextCleanupFailed,
            yosoi::BrowserContextCleanupDisposition::Failed,
            yosoi::BrowserProcessCleanupDisposition::Failed,
        ),
        (
            Error::ProcessCloseDeadline,
            yosoi::BrowserContextCleanupDisposition::Completed,
            yosoi::BrowserProcessCleanupDisposition::DeadlineExceeded,
        ),
        (
            Error::ProcessCloseFailed,
            yosoi::BrowserContextCleanupDisposition::Completed,
            yosoi::BrowserProcessCleanupDisposition::Failed,
        ),
        (
            Error::ContextAndProcessCleanupFailed,
            yosoi::BrowserContextCleanupDisposition::Failed,
            yosoi::BrowserProcessCleanupDisposition::Failed,
        ),
    ];
    for (error, expected_context, expected_process) in cases {
        assert_eq!(
            cleanup_dispositions_for_error(error),
            (expected_context, expected_process)
        );
    }
}

#[test]
fn managed_terminal_reason_mapping_is_closed_and_secret_safe() {
    use crate::BrowserExecutionManagerError as ManagerError;
    use yosoi::BrowserExecutionTerminalReason as Reason;

    let manager_cases = [
        (ManagerError::QueueFull, Reason::ProviderFailure),
        (ManagerError::QueueWaitDeadline, Reason::DeadlineExceeded),
        (ManagerError::CallerCancelled, Reason::CallerCancelled),
        (ManagerError::ManagerClosing, Reason::SystemInterrupted),
        (
            ManagerError::ProviderUnavailable,
            Reason::ProviderUnavailable,
        ),
        (
            ManagerError::IndependentLeaseHasNoAdditionalTabs,
            Reason::ProviderFailure,
        ),
        (ManagerError::GlobalTabCapacity, Reason::ProviderFailure),
        (ManagerError::SessionTabCapacity, Reason::ProviderFailure),
        (ManagerError::TabReleased, Reason::InternalInvariantFailure),
        (ManagerError::TabCloseFailed, Reason::TabCloseFailed),
        (
            ManagerError::ContextCleanupDeadline,
            Reason::ContextCleanupDeadlineExceeded,
        ),
        (
            ManagerError::ContextCleanupFailed,
            Reason::ContextCleanupFailed,
        ),
        (
            ManagerError::ProcessCloseDeadline,
            Reason::ProcessCleanupDeadlineExceeded,
        ),
        (
            ManagerError::ProcessCloseFailed,
            Reason::ProcessCleanupFailed,
        ),
        (
            ManagerError::ContextAndProcessCleanupFailed,
            Reason::ContextCleanupFailed,
        ),
        (
            ManagerError::InternalInvariant,
            Reason::InternalInvariantFailure,
        ),
    ];
    for (error, expected) in manager_cases {
        assert_eq!(terminal_reason_for_manager_error(error), expected);
        let encoded = serde_json::to_string(&expected).unwrap();
        for forbidden in ["authorization", "cookie", "https://", "diagnostic"] {
            assert!(!encoded.contains(forbidden));
        }
    }

    let adapter_cases = [
        (
            VoidCrawlAdapterError::Provider {
                code: "voidcrawl.browser.closed",
                category: VoidCrawlAdapterErrorCategory::Unavailable,
            },
            Reason::ProviderDisconnected,
        ),
        (
            VoidCrawlAdapterError::Provider {
                code: "voidcrawl.provider.unavailable",
                category: VoidCrawlAdapterErrorCategory::Unavailable,
            },
            Reason::ProviderUnavailable,
        ),
        (
            VoidCrawlAdapterError::Provider {
                code: "voidcrawl.provider.failed",
                category: VoidCrawlAdapterErrorCategory::ProviderFailure,
            },
            Reason::ProviderFailure,
        ),
        (
            VoidCrawlAdapterError::DeadlineBeforeStaging,
            Reason::DeadlineExceeded,
        ),
        (
            VoidCrawlAdapterError::BrowserExecution(ManagerError::TabCloseFailed),
            Reason::TabCloseFailed,
        ),
        (
            VoidCrawlAdapterError::InvalidStaging,
            Reason::InternalInvariantFailure,
        ),
    ];
    for (error, expected) in adapter_cases {
        assert_eq!(terminal_reason_for_error(&error), expected);
    }

    let nested = VoidCrawlAdapterError::PrimaryAndCleanup {
        primary: Box::new(VoidCrawlAdapterError::Provider {
            code: "voidcrawl.provider.failed",
            category: VoidCrawlAdapterErrorCategory::ProviderFailure,
        }),
        cleanup: "context-disposal",
    };
    assert_eq!(terminal_reason_for_error(&nested), Reason::ProviderFailure);
}

#[test]
fn cleanup_terminal_reason_preserves_the_exact_failed_resource() {
    use yosoi::BrowserExecutionTerminalReason as Reason;

    let cases = [
        (
            yosoi::BrowserContextCleanupDisposition::Failed,
            yosoi::BrowserProcessCleanupDisposition::Completed,
            Reason::ContextCleanupFailed,
        ),
        (
            yosoi::BrowserContextCleanupDisposition::DeadlineExceeded,
            yosoi::BrowserProcessCleanupDisposition::Completed,
            Reason::ContextCleanupDeadlineExceeded,
        ),
        (
            yosoi::BrowserContextCleanupDisposition::Completed,
            yosoi::BrowserProcessCleanupDisposition::Failed,
            Reason::ProcessCleanupFailed,
        ),
        (
            yosoi::BrowserContextCleanupDisposition::Completed,
            yosoi::BrowserProcessCleanupDisposition::DeadlineExceeded,
            Reason::ProcessCleanupDeadlineExceeded,
        ),
        (
            yosoi::BrowserContextCleanupDisposition::Failed,
            yosoi::BrowserProcessCleanupDisposition::Failed,
            Reason::ContextCleanupFailed,
        ),
    ];
    for (context, process, expected) in cases {
        let admission = test_admission();
        let cleanup = yosoi::BrowserExecutionCleanupReceipt::new(admission, context, process);
        assert_eq!(terminal_reason_for_cleanup(&cleanup), expected);
    }
}

fn test_admission() -> yosoi::BrowserExecutionAdmissionReceipt {
    use std::num::NonZeroU64;

    let process = yosoi::BrowserProcessSlotLease::new(
        yosoi::BrowserExecutionManagerId::random(),
        yosoi::BrowserProcessSlotId::random(),
        yosoi::BrowserProcessGeneration::new(NonZeroU64::MIN),
    );
    let execution = yosoi::BrowserExecutionLease::new(process, yosoi::BrowserExecutionId::random());
    let context =
        yosoi::BrowserContextLease::new(execution.clone(), yosoi::BrowserContextLeaseId::random());
    let session =
        yosoi::BrowserSessionLease::new(context.clone(), yosoi::BrowserSessionLeaseId::random());
    let tab = yosoi::BrowserTabLease::new(session.clone(), yosoi::BrowserTabLeaseId::random());
    yosoi::BrowserExecutionAdmissionReceipt::new(
        yosoi::BrowserExecutionScope::Independent,
        execution,
        context,
        session,
        tab,
    )
    .unwrap()
}

#[test]
fn source_only_navigation_terminals_are_admitted_without_observation() {
    let cancellation = CancellationToken::new();
    for (termination, expected) in [
        (
            provider::NavigationCaptureTermination::DeadlineReached,
            yosoi::BrowserTerminalSignal::DeadlineReached,
        ),
        (
            provider::NavigationCaptureTermination::EventLimitReached,
            yosoi::BrowserTerminalSignal::EventLimitReached,
        ),
        (
            provider::NavigationCaptureTermination::ProviderDisconnected,
            yosoi::BrowserTerminalSignal::ProviderFailed {
                reason: yosoi::BrowserProviderStop::BrowserDisconnected,
            },
        ),
    ] {
        let mut candidates = Vec::new();
        add_observation_terminal(
            None,
            None,
            Some(&navigation_report(termination)),
            Some(11),
            &cancellation,
            &mut candidates,
        )
        .unwrap();
        assert_eq!(candidates.len(), 1);
        assert_eq!(candidates[0].offset().as_microseconds(), 18);
        assert_eq!(candidates[0].signal(), &expected);
    }

    cancellation.cancel();
    let mut candidates = Vec::new();
    add_observation_terminal(
        None,
        None,
        Some(&navigation_report(
            provider::NavigationCaptureTermination::Cancelled,
        )),
        Some(11),
        &cancellation,
        &mut candidates,
    )
    .unwrap();
    assert!(matches!(
        candidates[0].signal(),
        yosoi::BrowserTerminalSignal::CallerInterrupted { .. }
    ));
}
