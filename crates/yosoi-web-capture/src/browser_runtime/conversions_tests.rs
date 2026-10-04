use super::*;

fn instrumentation_snapshot(
    configured_mode: provider::InstrumentationMode,
    network_enabled: bool,
    runtime_enabled: bool,
) -> provider::InstrumentationSnapshot {
    provider::InstrumentationSnapshot {
        configured_mode,
        network_enabled,
        runtime_enabled,
        performance_enabled: false,
        log_enabled: false,
        target_auto_attach: false,
        utility_world_enabled: false,
        pre_navigation_stealth: false,
        attached_browser: false,
        escalated_from_minimal: configured_mode == provider::InstrumentationMode::Minimal
            && (network_enabled || runtime_enabled),
    }
}

#[test]
fn effective_instrumentation_modes_require_exact_armed_domains() {
    use yosoi::BrowserInstrumentationMode as Mode;
    let cases = [
        (
            instrumentation_snapshot(provider::InstrumentationMode::Normal, true, true),
            Mode::Normal,
        ),
        (
            instrumentation_snapshot(provider::InstrumentationMode::Minimal, false, false),
            Mode::Minimal,
        ),
        (
            instrumentation_snapshot(provider::InstrumentationMode::Minimal, true, false),
            Mode::MinimalNetworkEscalated,
        ),
        (
            instrumentation_snapshot(provider::InstrumentationMode::Minimal, false, true),
            Mode::MinimalRuntimeEscalated,
        ),
        (
            instrumentation_snapshot(provider::InstrumentationMode::Minimal, true, true),
            Mode::MinimalBothEscalated,
        ),
    ];
    let modes = [
        Mode::Normal,
        Mode::Minimal,
        Mode::MinimalNetworkEscalated,
        Mode::MinimalRuntimeEscalated,
        Mode::MinimalBothEscalated,
    ];
    for (actual, expected) in cases {
        for mode in modes {
            assert_eq!(instrumentation_agrees(actual, mode), mode == expected);
        }
    }
}

fn provider_scope(epoch: provider::DocumentEpoch) -> provider::DocumentScope {
    provider::DocumentScope {
        frame_id: yosoi::BrowserFrameId(1),
        epoch,
        frame: provider::DocumentFrameScope::TopLevel,
        url: None,
    }
}

#[test]
fn source_failure_and_unavailability_remain_distinct() {
    for reason in [
        provider::SourceBodyUnavailableReason::RequestFailed,
        provider::SourceBodyUnavailableReason::InvalidBase64,
    ] {
        assert!(matches!(
            source_unavailable_outcome(Some(reason)).unwrap().state(),
            yosoi::AcquiredPayloadState::Failed { .. }
        ));
    }
    for reason in [
        provider::SourceBodyUnavailableReason::CdpBodyUnavailable,
        provider::SourceBodyUnavailableReason::CaptureEndedBeforeBody,
    ] {
        assert!(matches!(
            source_unavailable_outcome(Some(reason)).unwrap().state(),
            yosoi::AcquiredPayloadState::Unavailable { .. }
        ));
    }
}

#[test]
fn capture_local_scope_is_consistent_and_preserves_provider_epoch() {
    let first = document_scope(&provider_scope(provider::DocumentEpoch::Known(41))).unwrap();
    let second = document_scope(&provider_scope(provider::DocumentEpoch::Known(42))).unwrap();
    assert_eq!(first.frame, second.frame);
    assert_eq!(first.epoch, yosoi::BrowserDocumentEpoch(41));
    assert_eq!(second.epoch, yosoi::BrowserDocumentEpoch(42));
}

#[test]
fn subframes_preserve_provider_issued_capture_local_identity() {
    for frame_id in [2, 3, 4] {
        let scope = provider::DocumentScope {
            frame_id: yosoi::BrowserFrameId(frame_id),
            epoch: provider::DocumentEpoch::Known(1),
            frame: provider::DocumentFrameScope::Frame { url: None },
            url: None,
        };
        assert_eq!(
            document_scope(&scope),
            Some(yosoi::BrowserDocumentScope {
                frame: yosoi::BrowserFrameId(frame_id),
                epoch: yosoi::BrowserDocumentEpoch(1),
            })
        );
    }
}

#[test]
fn unavailable_provider_epoch_does_not_fabricate_scope() {
    assert_eq!(
        document_scope(&provider_scope(
            provider::DocumentEpoch::UnavailableForAttachedPage,
        )),
        None
    );
}

fn layout_snapshot(scope: provider::DocumentScope, page_x: i64) -> provider::LayoutSnapshot {
    provider::LayoutSnapshot {
        scope,
        generated_at_unix_ms: None,
        layout_viewport: provider::LayoutViewportMetrics {
            page_x,
            page_y: 17,
            client_width: 800,
            client_height: 600,
        },
        visual_viewport: provider::VisualViewportMetrics {
            offset_x: 0.0,
            offset_y: 0.0,
            page_x: 0.0,
            page_y: 0.0,
            client_width: 800.0,
            client_height: 600.0,
            scale: 1.0,
            zoom: None,
        },
        content_size: provider::ContentSizeMetrics {
            x: 0.0,
            y: 0.0,
            width: 800.0,
            height: 1200.0,
        },
        device_scale_factor: Some(1.0),
    }
}

#[test]
fn visual_layout_pairing_rejects_mismatched_document_scope() {
    let visual_scope = provider_scope(provider::DocumentEpoch::Known(2));
    let mismatched = (
        layout_snapshot(provider_scope(provider::DocumentEpoch::Known(1)), 91),
        yosoi::CaptureOffset::from_microseconds(7),
    );
    assert_eq!(
        browser_native::visual_layout_facts(&visual_scope, Some(&mismatched)),
        (
            0,
            0,
            yosoi::BrowserVisualLayoutCorrelation::Unavailable,
            None,
        )
    );

    let matching = (
        layout_snapshot(visual_scope.clone(), 23),
        yosoi::CaptureOffset::from_microseconds(8),
    );
    assert_eq!(
        browser_native::visual_layout_facts(&visual_scope, Some(&matching)),
        (
            23,
            17,
            yosoi::BrowserVisualLayoutCorrelation::SameDocumentEpochOnly,
            Some(yosoi::CaptureOffset::from_microseconds(8)),
        )
    );
}

#[test]
fn byte_domain_conversion_is_exhaustive() {
    for (input, expected) in [
        (
            provider::BrowserByteDomain::CdpDecodedBody,
            Some(yosoi::BrowserByteDomain::CdpDecodedBody),
        ),
        (
            provider::BrowserByteDomain::RenderedDomUtf8,
            Some(yosoi::BrowserByteDomain::RenderedDomUtf8),
        ),
        (
            provider::BrowserByteDomain::AccessibilityJsonUtf8,
            Some(yosoi::BrowserByteDomain::AccessibilityJsonUtf8),
        ),
        (
            provider::BrowserByteDomain::RuntimeDiagnosticUtf8,
            Some(yosoi::BrowserByteDomain::RuntimeDiagnosticUtf8),
        ),
        (
            provider::BrowserByteDomain::ScreenshotPng,
            Some(yosoi::BrowserByteDomain::ScreenshotPng),
        ),
        (provider::BrowserByteDomain::RecordingFrame, None),
        (provider::BrowserByteDomain::EncodedRecording, None),
    ] {
        assert_eq!(byte_domain(input).ok(), expected);
    }
}

#[test]
fn payload_extent_conversion_is_exhaustive() {
    let cases = [
        (
            provider::BrowserPayloadExtent::Complete,
            ProviderResultDescriptor::Complete,
        ),
        (
            provider::BrowserPayloadExtent::Truncated {
                complete_bytes: provider::MeasuredBrowserBytes::Known {
                    value: yosoi::ByteCount::new(9),
                },
            },
            ProviderResultDescriptor::Truncated,
        ),
        (
            provider::BrowserPayloadExtent::Discarded {
                observed_bytes: provider::MeasuredBrowserBytes::Known {
                    value: yosoi::ByteCount::new(9),
                },
            },
            ProviderResultDescriptor::Discarded,
        ),
        (
            provider::BrowserPayloadExtent::Unavailable {
                reason: provider::BrowserPayloadUnavailableReason::ProviderDidNotReport,
            },
            ProviderResultDescriptor::Unavailable("provider-did-not-report"),
        ),
        (
            provider::BrowserPayloadExtent::Unavailable {
                reason: provider::BrowserPayloadUnavailableReason::NotCollected,
            },
            ProviderResultDescriptor::Unavailable("not-collected"),
        ),
        (
            provider::BrowserPayloadExtent::Unavailable {
                reason: provider::BrowserPayloadUnavailableReason::Unsupported,
            },
            ProviderResultDescriptor::Unavailable("unsupported"),
        ),
        (
            provider::BrowserPayloadExtent::Failed {
                reason: provider::BrowserPayloadFailureReason::ProviderRejected,
            },
            ProviderResultDescriptor::Failed("provider-rejected"),
        ),
        (
            provider::BrowserPayloadExtent::Failed {
                reason: provider::BrowserPayloadFailureReason::ProviderDisconnected,
            },
            ProviderResultDescriptor::Failed("provider-disconnected"),
        ),
        (
            provider::BrowserPayloadExtent::Failed {
                reason: provider::BrowserPayloadFailureReason::InvalidEncoding,
            },
            ProviderResultDescriptor::Failed("invalid-encoding"),
        ),
        (
            provider::BrowserPayloadExtent::Failed {
                reason: provider::BrowserPayloadFailureReason::Deadline,
            },
            ProviderResultDescriptor::Failed("deadline"),
        ),
        (
            provider::BrowserPayloadExtent::Failed {
                reason: provider::BrowserPayloadFailureReason::Cancelled,
            },
            ProviderResultDescriptor::Failed("cancelled"),
        ),
        (
            provider::BrowserPayloadExtent::Failed {
                reason: provider::BrowserPayloadFailureReason::SinkFailure,
            },
            ProviderResultDescriptor::Failed("sink-failure"),
        ),
    ];
    for (input, expected) in cases {
        assert_eq!(payload_extent(input), expected);
    }
}

#[test]
fn environment_enum_conversions_are_exhaustive() {
    assert_eq!(
        environment_reason(provider::EnvironmentUnavailableReason::AttachedBrowserNotControlled),
        "voidcrawl.environment.attached-browser-not-controlled"
    );
    assert_eq!(
        environment_reason(provider::EnvironmentUnavailableReason::BrowserDidNotReport),
        "voidcrawl.environment.browser-did-not-report"
    );
    assert_eq!(
        environment_reason(provider::EnvironmentUnavailableReason::InvalidBrowserValue),
        "voidcrawl.environment.invalid-browser-value"
    );
    assert_eq!(
        omission_reason(provider::EnvironmentOmissionReason::MinimizeInstrumentation),
        "voidcrawl.environment.minimize-instrumentation"
    );
    assert_eq!(
        omission_reason(provider::EnvironmentOmissionReason::SensitiveValue),
        "voidcrawl.environment.sensitive-value"
    );
    for input in [
        yosoi::ColorScheme::Light,
        yosoi::ColorScheme::Dark,
        yosoi::ColorScheme::NoPreference,
    ] {
        assert_eq!(
            environment_value(provider::EnvironmentObservation::Known { value: input }, Ok)
                .unwrap()
                .as_known(),
            Some(&input)
        );
    }
}

#[test]
fn capability_classes_and_resource_outcomes_are_exhaustive() {
    assert_eq!(
        capability_class(provider::CapabilityState::Supported),
        CapabilityClass::Supported
    );
    assert_eq!(
        capability_class(provider::CapabilityState::Disabled {
            reason: provider::CapabilityDisabledReason::MinimalCdpMode
        }),
        CapabilityClass::Disabled
    );
    assert_eq!(
        capability_class(provider::CapabilityState::Unavailable {
            reason: provider::CapabilityUnavailableReason::AttachedBrowserStateNotControlled
        }),
        CapabilityClass::Unavailable
    );
    assert_eq!(
        capability_class(provider::CapabilityState::Unsupported {
            reason: provider::CapabilityUnsupportedReason::NotImplemented
        }),
        CapabilityClass::Unsupported
    );
    for input in [
        yosoi::BrowserResourceOutcome::Pending,
        yosoi::BrowserResourceOutcome::ResponseReceived,
        yosoi::BrowserResourceOutcome::Redirected,
        yosoi::BrowserResourceOutcome::Complete,
        yosoi::BrowserResourceOutcome::Failed {
            cancelled: false,
            blocked: false,
        },
        yosoi::BrowserResourceOutcome::Failed {
            cancelled: true,
            blocked: false,
        },
        yosoi::BrowserResourceOutcome::Failed {
            cancelled: false,
            blocked: true,
        },
        yosoi::BrowserResourceOutcome::Failed {
            cancelled: true,
            blocked: true,
        },
    ] {
        let expected: yosoi::BrowserResourceOutcome = input;
        assert_eq!(input, expected);
    }
}

fn runtime_report(termination: provider::ObservationTermination) -> provider::ObservationReport {
    let known_zero = provider::MeasuredCount::Known { value: 0 };
    provider::ObservationReport {
        started_at_unix_ms: None,
        elapsed_micros: 0,
        termination,
        events: Vec::new(),
        diagnostics: Vec::new(),
        diagnostic_bytes_retained: 0,
        diagnostic_bytes_dropped: 0,
        diagnostic_byte_limit: yosoi::ByteLimit::one(),
        accounting: provider::ObservationAccounting {
            events: provider::ObservationCountAccounting {
                admitted: known_zero,
                retained: known_zero,
                dropped: known_zero,
            },
            runtime_events: provider::ObservationCountAccounting {
                admitted: known_zero,
                retained: known_zero,
                dropped: known_zero,
            },
            runtime_bytes: provider::ObservationCountAccounting {
                admitted: known_zero,
                retained: known_zero,
                dropped: known_zero,
            },
            in_flight_requests: known_zero,
        },
        cleanup_complete: true,
    }
}

#[test]
fn runtime_diagnostics_preserve_only_provider_observed_document_scope() {
    for (provider_epoch, expected) in [
        (
            provider::DocumentEpoch::Known(41),
            Some(yosoi::BrowserDocumentScope {
                frame: yosoi::BrowserFrameId(1),
                epoch: yosoi::BrowserDocumentEpoch(41),
            }),
        ),
        (provider::DocumentEpoch::UnavailableForAttachedPage, None),
    ] {
        let scope = document_scope(&provider_scope(provider_epoch));
        let outcome = browser_native::runtime(
            &runtime_report(provider::ObservationTermination::Finished),
            0,
            scope,
        )
        .unwrap();
        let yosoi::BrowserStagingParts::Structured { evidence, .. } = outcome.parts() else {
            panic!("runtime evidence must be structured");
        };
        let yosoi::BrowserStructuredEvidence::RuntimeDiagnostics { scope, .. } = evidence else {
            panic!("runtime evidence family must be retained");
        };
        assert_eq!(*scope, expected);
        let json = evidence.to_canonical_json().unwrap();
        let parsed = yosoi::BrowserStructuredEvidence::from_json(&json).unwrap();
        assert_eq!(&parsed, evidence);
    }
}

#[test]
fn early_observation_termination_leaves_runtime_byte_loss_unknown() {
    let finished = browser_native::runtime_byte_accounting(&runtime_report(
        provider::ObservationTermination::Finished,
    ))
    .unwrap();
    assert_eq!(finished.lost, yosoi::LossExtent::Known(0));
    assert!(finished.complete);

    for termination in [
        provider::ObservationTermination::Cancelled,
        provider::ObservationTermination::Interrupted,
        provider::ObservationTermination::DeadlineReached,
        provider::ObservationTermination::EventLimitReached,
        provider::ObservationTermination::ProviderDisconnected,
    ] {
        let accounting =
            browser_native::runtime_byte_accounting(&runtime_report(termination)).unwrap();
        assert_eq!(accounting.lost, yosoi::LossExtent::Unknown);
        assert!(!accounting.complete);
    }
}

#[test]
fn failed_observation_never_claims_known_zero_event_loss() {
    let failed = missing_observation_accounting(true).unwrap();
    assert_eq!(failed.admitted().get(), 0);
    assert_eq!(failed.retained().get(), 0);
    assert!(matches!(
        failed.dropped(),
        yosoi::MeasuredCount::Unavailable { reason }
            if reason.as_str() == "voidcrawl.observation.finalization-failed"
    ));

    let unrequested = missing_observation_accounting(false).unwrap();
    assert!(matches!(
        unrequested.dropped(),
        yosoi::MeasuredCount::Known(count) if count.get() == 0
    ));
}

#[test]
fn provider_event_loss_is_preserved_without_inventing_retention() {
    let known = event_accounting(7, 0, provider::MeasuredCount::Known { value: 7 }).unwrap();
    assert_eq!(known.admitted().get(), 7);
    assert_eq!(known.retained().get(), 0);
    assert!(matches!(known.dropped(), yosoi::MeasuredCount::Known(v) if v.get() == 7));

    let unavailable = event_accounting(
        7,
        0,
        provider::MeasuredCount::Unavailable {
            reason: provider::MeasurementUnavailableReason::ProviderDidNotReport,
        },
    )
    .unwrap();
    assert_eq!(unavailable.admitted().get(), 7);
    assert_eq!(unavailable.retained().get(), 0);
    assert!(matches!(
        unavailable.dropped(),
        yosoi::MeasuredCount::Unavailable { .. }
    ));
    assert!(event_accounting(7, 0, provider::MeasuredCount::Known { value: 6 }).is_err());
}
