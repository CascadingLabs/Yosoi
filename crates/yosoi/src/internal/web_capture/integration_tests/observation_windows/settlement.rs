use super::{support::*, *};

#[test]
fn settled_requires_matching_quiet_period_evidence() {
    let settlement_id = SettlementPolicyId::new("com.cascadinglabs.yosoi.network-quiet").unwrap();
    let settlement = SettlementPolicy::QuietPeriod(QuietPeriodPolicy::new(
        settlement_id.clone(),
        QuietPeriod::try_from(500_000).unwrap(),
        ActivityCount::new(0),
    ));
    let policy = policy(
        CaptureDeadline::try_from(5_000_000).unwrap(),
        None,
        None,
        settlement,
    );
    let evidence = SettlementEvidence::new(
        settlement_id,
        CaptureOffset::from_microseconds(400_000),
        CaptureOffset::from_microseconds(900_000),
        ActivityCount::new(0),
        quiet_event_accounting(),
    )
    .unwrap();

    let observation = CaptureObservation::new(
        policy,
        window(900_000),
        terminal_state_at(900_000, 20, 2_000, 3, 0),
        CaptureTermination::Settled(evidence),
    )
    .unwrap();

    assert!(matches!(
        observation.termination(),
        CaptureTermination::Settled(_)
    ));
}

#[test]
fn insufficient_or_contradictory_settlement_evidence_is_rejected() {
    let settlement_id = SettlementPolicyId::new("com.cascadinglabs.yosoi.dom-quiet").unwrap();
    let policy = quiet_policy(settlement_id.clone(), 500_000, 0);

    let too_short = SettlementEvidence::new(
        settlement_id.clone(),
        CaptureOffset::from_microseconds(600_000),
        CaptureOffset::from_microseconds(999_999),
        ActivityCount::new(0),
        quiet_event_accounting(),
    )
    .unwrap();
    assert_eq!(
        CaptureObservation::new(
            policy.clone(),
            window(1_000_000),
            terminal_state(10, 100, 0, 0),
            CaptureTermination::Settled(too_short),
        ),
        Err(CaptureObservationError::QuietPeriodNotSatisfied)
    );

    let wrong_policy = SettlementEvidence::new(
        SettlementPolicyId::new("com.cascadinglabs.yosoi.ax-quiet").unwrap(),
        CaptureOffset::from_microseconds(0),
        CaptureOffset::from_microseconds(500_000),
        ActivityCount::new(0),
        quiet_event_accounting(),
    )
    .unwrap();
    assert_eq!(
        CaptureObservation::new(
            policy.clone(),
            window(1_000_000),
            terminal_state(10, 100, 0, 0),
            CaptureTermination::Settled(wrong_policy),
        ),
        Err(CaptureObservationError::SettlementPolicyMismatch)
    );

    let too_much_activity = SettlementEvidence::new(
        settlement_id.clone(),
        CaptureOffset::from_microseconds(0),
        CaptureOffset::from_microseconds(500_000),
        ActivityCount::new(1),
        quiet_event_accounting(),
    )
    .unwrap();
    assert_eq!(
        CaptureObservation::new(
            policy.clone(),
            window(1_000_000),
            terminal_state(10, 100, 1, 1),
            CaptureTermination::Settled(too_much_activity),
        ),
        Err(CaptureObservationError::SettlementInFlightExceeded)
    );

    let outside_window = SettlementEvidence::new(
        settlement_id.clone(),
        CaptureOffset::from_microseconds(500_000),
        CaptureOffset::from_microseconds(1_000_001),
        ActivityCount::new(0),
        quiet_event_accounting(),
    )
    .unwrap();
    assert_eq!(
        CaptureObservation::new(
            policy.clone(),
            window(1_000_000),
            terminal_state(10, 100, 0, 0),
            CaptureTermination::Settled(outside_window),
        ),
        Err(CaptureObservationError::SettlementOutsideWindow)
    );

    let terminal_mismatch = SettlementEvidence::new(
        settlement_id,
        CaptureOffset::from_microseconds(500_000),
        CaptureOffset::from_microseconds(1_000_000),
        ActivityCount::new(0),
        quiet_event_accounting(),
    )
    .unwrap();
    assert_eq!(
        CaptureObservation::new(
            policy,
            window(1_000_000),
            terminal_state(10, 100, 1, 1),
            CaptureTermination::Settled(terminal_mismatch),
        ),
        Err(CaptureObservationError::SettlementTerminalStateMismatch)
    );
}

#[test]
fn accounting_and_settlement_coverage_reject_contradictory_loss() {
    assert!(
        EventAccounting::new(
            EventCount::new(10),
            EventCount::new(9),
            MeasuredCount::Known(EventCount::new(0)),
        )
        .is_err()
    );
    assert!(
        ByteAccounting::new(
            ByteCount::new(10),
            ByteCount::new(11),
            MeasuredCount::Known(ByteCount::new(0)),
        )
        .is_err()
    );

    let policy_id = SettlementPolicyId::new("com.cascadinglabs.yosoi.quiet").unwrap();
    assert!(
        SettlementEvidence::new(
            policy_id.clone(),
            CaptureOffset::from_microseconds(0),
            CaptureOffset::from_microseconds(500_000),
            ActivityCount::new(0),
            EventAccounting::new(
                EventCount::new(1),
                EventCount::new(0),
                MeasuredCount::Known(EventCount::new(1)),
            )
            .unwrap(),
        )
        .is_err()
    );
    assert!(
        SettlementEvidence::new(
            policy_id,
            CaptureOffset::from_microseconds(0),
            CaptureOffset::from_microseconds(500_000),
            ActivityCount::new(0),
            EventAccounting::new(
                EventCount::new(0),
                EventCount::new(0),
                MeasuredCount::Unavailable {
                    reason: ReasonCode::new("capture.relevant-loss-unavailable").unwrap(),
                },
            )
            .unwrap(),
        )
        .is_err()
    );
}

#[test]
fn relative_offsets_and_non_zero_bounds_reject_invalid_boundaries() {
    assert!(CaptureDeadline::try_from(0).is_err());
    assert!(EventLimit::try_from(0).is_err());
    assert!(ByteLimit::try_from(0_u64).is_err());
    assert!(QuietPeriod::try_from(0).is_err());
    assert!(
        SettlementEvidence::new(
            SettlementPolicyId::new("com.cascadinglabs.yosoi.quiet").unwrap(),
            CaptureOffset::from_microseconds(2),
            CaptureOffset::from_microseconds(1),
            ActivityCount::new(0),
            quiet_event_accounting(),
        )
        .is_err()
    );
    assert!(InFlightActivity::new(ActivityCount::new(1), ActivityCount::new(2)).is_err());

    let start = timestamp("2026-09-05T00:00:01Z");
    let finish = timestamp("2026-09-05T00:00:00Z");
    assert!(ObservationWindow::new(start, finish, CaptureDuration::default()).is_err());
}
