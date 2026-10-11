use super::*;

#[test]
fn all_nine_request_schema_combinations() {
    for family in FAMILIES {
        for request in [
            ArtifactRequest::NotRequested,
            ArtifactRequest::Optional,
            ArtifactRequest::Required,
        ] {
            for has_schema in [false, true] {
                let result = spec(
                    family,
                    request,
                    has_schema,
                    None,
                    SettlementPolicy::Disabled,
                );
                let requested = request != ArtifactRequest::NotRequested;
                let supported_scope = !matches!(
                    family,
                    WebArtifactFamily::Cookies | WebArtifactFamily::Storage
                );
                assert_eq!(
                    result.is_ok(),
                    requested == has_schema && (!requested || supported_scope),
                    "{family:?} {request:?} {has_schema}"
                );
            }
        }
    }
}
#[test]
fn byte_families_require_exact_domain_bound() {
    for (family, domain) in [
        (FAMILIES[0], BrowserByteDomain::CdpDecodedBody),
        (FAMILIES[1], BrowserByteDomain::RenderedDomUtf8),
        (FAMILIES[2], BrowserByteDomain::AccessibilityJsonUtf8),
        (FAMILIES[7], BrowserByteDomain::ScreenshotPng),
        (FAMILIES[8], BrowserByteDomain::RuntimeDiagnosticUtf8),
    ] {
        for request in [ArtifactRequest::Optional, ArtifactRequest::Required] {
            assert_eq!(
                spec(
                    family,
                    request,
                    true,
                    Some(domain),
                    SettlementPolicy::Disabled
                ),
                Err(BrowserCaptureSpecError::MissingByteBound { family })
            );
        }
    }
}
#[test]
fn instrumentation_domain_matrix() {
    for mode in [
        BrowserInstrumentationMode::Normal,
        BrowserInstrumentationMode::Minimal,
        BrowserInstrumentationMode::MinimalNetworkEscalated,
        BrowserInstrumentationMode::MinimalRuntimeEscalated,
        BrowserInstrumentationMode::MinimalBothEscalated,
    ] {
        for network in [false, true] {
            for runtime in [false, true] {
                let expected = match mode {
                    BrowserInstrumentationMode::Normal
                    | BrowserInstrumentationMode::MinimalBothEscalated => network && runtime,
                    BrowserInstrumentationMode::Minimal => !network && !runtime,
                    BrowserInstrumentationMode::MinimalNetworkEscalated => network && !runtime,
                    BrowserInstrumentationMode::MinimalRuntimeEscalated => !network && runtime,
                };
                assert_eq!(
                    capabilities(mode, network, runtime).is_ok(),
                    expected,
                    "{mode:?} {network} {runtime}"
                );
            }
        }
    }
}
#[test]
fn all_nine_outcome_request_agreement() {
    for family in FAMILIES {
        for request in [
            ArtifactRequest::NotRequested,
            ArtifactRequest::Optional,
            ArtifactRequest::Required,
        ] {
            let Ok(spec) = spec(
                family,
                request,
                request != ArtifactRequest::NotRequested,
                None,
                SettlementPolicy::Disabled,
            ) else {
                continue;
            };
            for outcome in [
                ArtifactStagingOutcome::unrequested(),
                ArtifactStagingOutcome::unavailable(reason()),
                ArtifactStagingOutcome::failed(reason()),
                ArtifactStagingOutcome::disabled(reason()),
                ArtifactStagingOutcome::unsupported(reason()),
            ] {
                let expected = if request == ArtifactRequest::NotRequested {
                    outcome.state() == StagingState::Unrequested
                } else {
                    matches!(
                        outcome.state(),
                        StagingState::Unavailable | StagingState::Failed
                    )
                };
                assert_eq!(
                    facts(spec.clone(), staging(family, outcome.clone()), 20).is_ok(),
                    expected,
                    "{family:?} {request:?} {:?}",
                    outcome.state()
                );
            }
        }
    }
}
#[test]
fn discarded_domain_and_owned_payloads() {
    let family = BrowserStagingFamily::Artifact(WebArtifactFamily::Source);
    assert_eq!(
        BrowserStagingSlot::new(
            family,
            ArtifactStagingOutcome::discarded(
                BrowserByteDomain::ScreenshotPng,
                LossExtent::Known(8),
                reason(),
            )
        ),
        Err(StagingSlotError)
    );
    let mapping =
        BrowserArtifactMapping::new(family, BrowserByteLayer::DecodedResponseBody).unwrap();
    let bytes: Arc<[u8]> = Arc::from(b"abc".as_slice());
    for outcome in [
        ArtifactStagingOutcome::complete(mapping, bytes.clone(), 3).unwrap(),
        ArtifactStagingOutcome::partial(mapping, bytes.clone(), 5, LossExtent::Known(2), reason())
            .unwrap(),
        ArtifactStagingOutcome::truncated(mapping, bytes.clone(), 5, LossExtent::Unknown, reason())
            .unwrap(),
        ArtifactStagingOutcome::discarded(
            BrowserByteDomain::CdpDecodedBody,
            LossExtent::Known(5),
            reason(),
        ),
    ] {
        assert_eq!(outcome.parts(), &outcome.clone().into_parts());
        let accounting = outcome.accounting().unwrap();
        match outcome.into_parts() {
            BrowserStagingParts::Complete { bytes: owned, .. }
            | BrowserStagingParts::Partial { bytes: owned, .. }
            | BrowserStagingParts::Truncated { bytes: owned, .. } => {
                assert_eq!(owned, bytes);
                assert_eq!(accounting.retained(), 3);
            }
            BrowserStagingParts::Discarded { observed, .. } => {
                assert_eq!(observed, LossExtent::Known(5));
                assert_eq!(accounting.retained(), 0);
            }
            _ => panic!("unexpected fixture"),
        }
    }
}
#[test]
fn structured_network_loss_and_owned_extraction() {
    for loss in [
        LossExtent::Known(0),
        LossExtent::Known(1),
        LossExtent::Unknown,
    ] {
        for partial in [false, true] {
            let evidence = BrowserStructuredEvidence::Network {
                requested_url: None,
                final_url: None,
                redirects: vec![],
                main_document: None,
                extra_info: BrowserExtraInfoEvidence::UnavailableInCurrentClient,
                resources: vec![],
                events: vec![],
                resource_accounting: BrowserResourceAccounting::new(
                    u64::from(matches!(loss, LossExtent::Known(value) if value > 0)),
                    0,
                    loss,
                )
                .unwrap(),
                event_accounting: EventAccounting::new(
                    EventCount::new(0),
                    EventCount::new(0),
                    MeasuredCount::Known(EventCount::new(0)),
                )
                .unwrap(),
            };
            let outcome =
                ArtifactStagingOutcome::structured(evidence.clone(), partial.then(reason));
            assert_eq!(outcome.is_ok(), partial || loss == LossExtent::Known(0));
            if let Ok(outcome) = outcome {
                assert_eq!(
                    outcome.into_parts(),
                    BrowserStagingParts::Structured {
                        evidence,
                        reason: partial.then(reason)
                    }
                );
            }
        }
    }
}
#[test]
fn every_terminal_preserves_offset_and_explicit_deadline() {
    let signals = [
        BrowserTerminalSignal::DeadlineReached,
        BrowserTerminalSignal::SystemInterrupted { reason: reason() },
        BrowserTerminalSignal::CallerInterrupted { reason: reason() },
        BrowserTerminalSignal::CleanupFailed,
        BrowserTerminalSignal::ProviderFailed {
            reason: BrowserProviderStop::RendererFailure,
        },
        BrowserTerminalSignal::EventLimitReached,
        BrowserTerminalSignal::ByteLimitReached {
            domain: BrowserByteDomain::ScreenshotPng,
        },
        BrowserTerminalSignal::QuietSettled,
        BrowserTerminalSignal::ControllerCompleted,
    ];
    for signal in signals {
        for offset in [20, 100, 101] {
            let terminal = resolve_browser_terminal(
                &[BrowserTerminalCandidate::new(
                    CaptureOffset::from_microseconds(offset),
                    signal.clone(),
                )],
                CaptureDeadline::try_from(100).unwrap(),
            )
            .unwrap();
            assert_eq!(
                terminal.at(),
                CaptureOffset::from_microseconds(
                    if signal == BrowserTerminalSignal::DeadlineReached {
                        100
                    } else {
                        offset.min(100)
                    }
                )
            );
            if offset >= 100 || signal == BrowserTerminalSignal::DeadlineReached {
                assert!(matches!(
                    terminal.kind(),
                    BrowserTerminalKind::DeadlineReached { .. }
                ));
            }
        }
    }
}
