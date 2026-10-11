use super::*;

#[test]
fn terminal_tie_priority_is_independent_of_candidate_order() {
    let signals = [
        BrowserTerminalSignal::SystemInterrupted { reason: reason() },
        BrowserTerminalSignal::CallerInterrupted { reason: reason() },
        BrowserTerminalSignal::CleanupFailed,
        BrowserTerminalSignal::ProviderFailed {
            reason: BrowserProviderStop::InternalFailure,
        },
        BrowserTerminalSignal::EventLimitReached,
        BrowserTerminalSignal::ByteLimitReached {
            domain: BrowserByteDomain::ScreenshotPng,
        },
        BrowserTerminalSignal::QuietSettled,
        BrowserTerminalSignal::ControllerCompleted,
    ];
    let max = CaptureDeadline::try_from(100).unwrap();
    for (index, first) in signals.iter().enumerate() {
        let first =
            BrowserTerminalCandidate::new(CaptureOffset::from_microseconds(20), first.clone());
        let expected = resolve_browser_terminal(slice::from_ref(&first), max);
        for second in signals.iter().skip(index) {
            let second =
                BrowserTerminalCandidate::new(CaptureOffset::from_microseconds(20), second.clone());
            assert_eq!(
                resolve_browser_terminal(&[first.clone(), second.clone()], max),
                expected
            );
            assert_eq!(
                resolve_browser_terminal(&[second, first.clone()], max),
                expected
            );
        }
    }
}
#[test]
fn accounting_is_derived_checked_and_preserves_unknown_loss() {
    let discarded =
        |domain, observed| ArtifactStagingOutcome::discarded(domain, observed, reason());
    let slot = |family, outcome| {
        BrowserStagingSlot::new(BrowserStagingFamily::Artifact(family), outcome).unwrap()
    };
    for loss in [
        LossExtent::Known(0),
        LossExtent::Known(1),
        LossExtent::Unknown,
    ] {
        let staged = BrowserArtifactStaging::new(
            slot(
                FAMILIES[0],
                discarded(
                    BrowserByteDomain::CdpDecodedBody,
                    LossExtent::Known(u64::MAX),
                ),
            ),
            BrowserStagingSlot::new(
                BrowserStagingFamily::SourceRepresentation,
                ArtifactStagingOutcome::unavailable(reason()),
            )
            .unwrap(),
            slot(
                FAMILIES[1],
                discarded(BrowserByteDomain::RenderedDomUtf8, loss),
            ),
            slot(FAMILIES[2], ArtifactStagingOutcome::unrequested()),
            slot(FAMILIES[3], ArtifactStagingOutcome::unrequested()),
            slot(FAMILIES[4], ArtifactStagingOutcome::unrequested()),
            slot(FAMILIES[5], ArtifactStagingOutcome::unrequested()),
            slot(FAMILIES[6], ArtifactStagingOutcome::unrequested()),
            slot(FAMILIES[7], ArtifactStagingOutcome::unrequested()),
            slot(FAMILIES[8], ArtifactStagingOutcome::unrequested()),
        )
        .unwrap();
        if loss == LossExtent::Known(1) {
            assert_eq!(
                staged.accounting(),
                Err(BrowserAdapterOutputError::Overflow)
            );
        } else {
            let accounting = staged.accounting().unwrap();
            assert_eq!(accounting.observed(), u64::MAX);
            assert_eq!(accounting.retained(), 0);
            assert_eq!(
                accounting.lost(),
                if loss == LossExtent::Unknown {
                    LossExtent::Unknown
                } else {
                    LossExtent::Known(u64::MAX)
                }
            );
        }
    }
}
#[test]
fn quiet_settlement_requires_policy_evidence_and_extracts_all_facts() {
    let policy = QuietPeriodPolicy::new(
        SettlementPolicyId::new("test.quiet").unwrap(),
        QuietPeriod::try_from(10).unwrap(),
        ActivityCount::new(0),
    );
    let spec = spec(
        WebArtifactFamily::Visual,
        ArtifactRequest::NotRequested,
        false,
        None,
        SettlementPolicy::QuietPeriod(policy.clone()),
    )
    .unwrap();
    let staging = staging(
        WebArtifactFamily::Visual,
        ArtifactStagingOutcome::unrequested(),
    );
    let events = EventAccounting::new(
        EventCount::new(0),
        EventCount::new(0),
        MeasuredCount::Known(EventCount::new(0)),
    )
    .unwrap();
    let at = CaptureOffset::from_microseconds(20);
    let evidence = SettlementEvidence::new(
        policy.id().clone(),
        CaptureOffset::from_microseconds(10),
        at,
        ActivityCount::new(0),
        events.clone(),
    )
    .unwrap();
    let facts = BrowserAdapterFacts::new(
        at,
        staging.clone(),
        environment(),
        spec.clone(),
        events.clone(),
        InFlightActivity::new(ActivityCount::new(0), ActivityCount::new(0)).unwrap(),
        true,
        Some(evidence.clone()),
        CleanupState::Complete,
        BrowserChallengeFact::unavailable(
            BrowserResponseSignalUnavailableReason::NavigationNotCollected,
        ),
    )
    .unwrap();
    let quiet = resolve_browser_terminal(
        &[BrowserTerminalCandidate::new(
            at,
            BrowserTerminalSignal::QuietSettled,
        )],
        CaptureDeadline::try_from(100).unwrap(),
    )
    .unwrap();
    let result = BrowserAdapterResult::ready_for_finalization(quiet, facts.clone()).unwrap();
    assert!(result.is_ready());
    assert_eq!(result.facts().spec(), &spec);
    assert_eq!(facts.settlement(), Some(&evidence));
    assert_eq!(facts.events(), &events);
    assert_eq!(facts.environment(), &environment());
    let parts = result.into_parts().2.into_parts();
    assert_eq!(parts.spec, spec);
    assert_eq!(parts.staging, staging);
    assert_eq!(parts.observed_through, at);
    assert_eq!(parts.settlement, Some(evidence));
    let controller = resolve_browser_terminal(
        &[BrowserTerminalCandidate::new(
            at,
            BrowserTerminalSignal::ControllerCompleted,
        )],
        CaptureDeadline::try_from(100).unwrap(),
    )
    .unwrap();
    assert_eq!(
        BrowserAdapterResult::ready_for_finalization(controller, facts),
        Err(BrowserAdapterOutputError::InvalidReadyState)
    );
}
#[test]
fn bounds_zero_duplicate_and_enforcement() {
    assert!(NonZeroU64::new(0).is_none());
    assert!(CaptureDeadline::try_from(0).is_err());
    let bound = BrowserByteBound::new(
        BrowserByteDomain::ScreenshotPng,
        NonZeroU64::MIN,
        BrowserLimitEnforcement::RetentionAfterProviderMaterialization,
        BrowserBudgetScope::PerPayload,
    );
    assert_eq!(
        BrowserProviderBounds::new(
            vec![bound, bound],
            NonZeroU64::MIN,
            NonZeroU32::MIN,
            NonZeroU32::MIN
        ),
        Err(BrowserBoundsError::DuplicateByteDomain)
    );
    for domain in [
        BrowserByteDomain::CdpDecodedBody,
        BrowserByteDomain::RenderedDomUtf8,
        BrowserByteDomain::AccessibilityJsonUtf8,
        BrowserByteDomain::RuntimeDiagnosticUtf8,
        BrowserByteDomain::ScreenshotPng,
    ] {
        let streaming = BrowserByteBound::new(
            domain,
            NonZeroU64::MIN,
            BrowserLimitEnforcement::StreamingAdmission,
            BrowserBudgetScope::PerPayload,
        );
        assert_eq!(
            BrowserProviderBounds::new(
                vec![streaming],
                NonZeroU64::MIN,
                NonZeroU32::MIN,
                NonZeroU32::MIN
            ),
            Err(BrowserBoundsError::UnsupportedEnforcement),
            "{domain:?}"
        );
    }
}
#[test]
fn ready_stopped_and_offset_state_sets() {
    for signal in [
        BrowserTerminalSignal::QuietSettled,
        BrowserTerminalSignal::ControllerCompleted,
        BrowserTerminalSignal::EventLimitReached,
    ] {
        for observed in [19, 20, 21] {
            let spec = spec(
                WebArtifactFamily::Visual,
                ArtifactRequest::NotRequested,
                false,
                None,
                SettlementPolicy::Disabled,
            )
            .unwrap();
            let facts = facts(
                spec,
                staging(
                    WebArtifactFamily::Visual,
                    ArtifactStagingOutcome::unrequested(),
                ),
                observed,
            )
            .unwrap();
            let terminal = resolve_browser_terminal(
                &[BrowserTerminalCandidate::new(
                    CaptureOffset::from_microseconds(20),
                    signal.clone(),
                )],
                CaptureDeadline::try_from(100).unwrap(),
            )
            .unwrap();
            assert_eq!(
                BrowserAdapterResult::ready_for_finalization(terminal.clone(), facts.clone())
                    .is_ok(),
                observed == 20 && signal == BrowserTerminalSignal::ControllerCompleted
            );
            assert_eq!(
                BrowserAdapterResult::stopped(terminal, facts).is_ok(),
                observed == 20 && signal == BrowserTerminalSignal::EventLimitReached
            );
        }
    }
}
