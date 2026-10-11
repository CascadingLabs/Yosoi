use super::{support::*, *};

#[test]
fn configured_five_and_ten_second_windows_remain_distinguishable() {
    let five_seconds = controller_stopped_observation(5_000_000);
    let ten_seconds = controller_stopped_observation(10_000_000);

    assert_ne!(five_seconds.policy(), ten_seconds.policy());
    assert_ne!(
        serde_json::to_value(five_seconds).unwrap(),
        serde_json::to_value(ten_seconds).unwrap()
    );
}

#[test]
fn a_never_settling_site_has_a_valid_deadline_outcome() {
    let deadline = CaptureDeadline::try_from(5_000_000).unwrap();
    let policy = policy(deadline, None, None, SettlementPolicy::Disabled);
    let window = window(5_010_000);
    let terminal_state = terminal_state_at(5_010_000, 120, 48_000, 12, 4);
    let observation = CaptureObservation::new(
        policy,
        window,
        terminal_state,
        CaptureTermination::DeadlineReached {
            maximum_elapsed: deadline,
        },
    )
    .unwrap();

    assert!(matches!(
        observation.termination(),
        CaptureTermination::DeadlineReached { .. }
    ));
    assert_eq!(
        observation.terminal_state().in_flight().total(),
        &MeasuredCount::Known(ActivityCount::new(12))
    );
    assert_eq!(
        observation
            .terminal_state()
            .in_flight()
            .settlement_relevant(),
        &MeasuredCount::Known(ActivityCount::new(4))
    );
}

#[test]
fn controller_completion_is_not_misrepresented_as_settlement_or_interruption() {
    let observation = controller_stopped_observation(5_000_000);

    assert_eq!(
        observation.termination(),
        &CaptureTermination::ControllerStopped(ControllerStopReason::GoalSatisfied)
    );

    let policy = policy(
        CaptureDeadline::try_from(500_000).unwrap(),
        None,
        None,
        SettlementPolicy::Disabled,
    );
    assert_eq!(
        CaptureObservation::new(
            policy,
            window(500_001),
            terminal_state_at(500_001, 5, 512, 0, 0),
            CaptureTermination::ControllerStopped(ControllerStopReason::GoalSatisfied),
        ),
        Err(CaptureObservationError::WindowExceedsMaximum)
    );
}

#[test]
fn interruption_retains_reason_in_flight_activity_and_loss_accounting() {
    let policy = policy(
        CaptureDeadline::try_from(10_000_000).unwrap(),
        None,
        None,
        SettlementPolicy::Disabled,
    );
    let state = TerminalObservationState::new(
        CaptureOffset::from_microseconds(800_000),
        EventAccounting::new(
            EventCount::new(25),
            EventCount::new(25),
            MeasuredCount::Unavailable {
                reason: ReasonCode::new("capture.provider-drop-count-unavailable").unwrap(),
            },
        )
        .unwrap(),
        ByteAccounting::new(
            ByteCount::new(2_176),
            ByteCount::new(2_048),
            MeasuredCount::Known(ByteCount::new(128)),
        )
        .unwrap(),
        InFlightActivity::new(ActivityCount::new(3), ActivityCount::new(1)).unwrap(),
    );
    let termination = CaptureTermination::Interrupted(InterruptionEvidence::new(
        InterruptionInitiator::Provider,
        ReasonCode::new("capture.provider-disconnected").unwrap(),
    ));
    let observation = CaptureObservation::new(policy, window(800_000), state, termination).unwrap();

    assert!(matches!(
        observation.terminal_state().events().dropped(),
        MeasuredCount::Unavailable { .. }
    ));
    assert_eq!(
        observation.terminal_state().bytes().dropped(),
        &MeasuredCount::Known(ByteCount::new(128))
    );
}
