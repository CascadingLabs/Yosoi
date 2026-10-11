use super::{support::*, *};

#[test]
fn every_limit_outcome_must_match_and_reach_its_declared_bound() {
    let deadline = CaptureDeadline::try_from(5_000_000).unwrap();
    let event_limit = EventLimit::try_from(100).unwrap();
    let byte_limit = ByteLimit::try_from(10_000_u64).unwrap();
    let policy = policy(
        deadline,
        Some(event_limit),
        Some(byte_limit),
        SettlementPolicy::Disabled,
    );

    assert!(
        CaptureObservation::new(
            policy.clone(),
            window(5_000_000),
            terminal_state_at(5_000_000, 50, 5_000, 0, 0),
            CaptureTermination::DeadlineReached {
                maximum_elapsed: deadline,
            },
        )
        .is_ok()
    );
    assert!(
        CaptureObservation::new(
            policy.clone(),
            window(1_000_000),
            terminal_state(100, 5_000, 0, 0),
            CaptureTermination::EventLimitReached { event_limit },
        )
        .is_ok()
    );
    assert!(
        CaptureObservation::new(
            policy.clone(),
            window(1_000_000),
            terminal_state(50, 10_000, 0, 0),
            CaptureTermination::ByteLimitReached { byte_limit },
        )
        .is_ok()
    );

    assert_eq!(
        CaptureObservation::new(
            policy.clone(),
            window(4_999_999),
            terminal_state_at(4_999_999, 50, 5_000, 0, 0),
            CaptureTermination::DeadlineReached {
                maximum_elapsed: deadline,
            },
        ),
        Err(CaptureObservationError::DeadlineNotReached)
    );
    assert_eq!(
        CaptureObservation::new(
            policy.clone(),
            window(1_000_000),
            terminal_state(99, 5_000, 0, 0),
            CaptureTermination::EventLimitReached { event_limit },
        ),
        Err(CaptureObservationError::EventLimitNotReached)
    );
    assert_eq!(
        CaptureObservation::new(
            policy,
            window(1_000_000),
            terminal_state(50, 9_999, 0, 0),
            CaptureTermination::ByteLimitReached { byte_limit },
        ),
        Err(CaptureObservationError::ByteLimitNotReached)
    );
}

#[test]
fn limit_outcomes_preserve_admitted_retained_and_dropped_counts() {
    let deadline = CaptureDeadline::try_from(5_000_000).unwrap();
    let event_limit = EventLimit::try_from(100).unwrap();
    let byte_limit = ByteLimit::try_from(10_000_u64).unwrap();
    let in_flight = InFlightActivity::new(ActivityCount::new(2), ActivityCount::new(1)).unwrap();

    let event_limited_state = TerminalObservationState::new(
        CaptureOffset::from_microseconds(1_000_000),
        EventAccounting::new(
            EventCount::new(100),
            EventCount::new(80),
            MeasuredCount::Known(EventCount::new(20)),
        )
        .unwrap(),
        ByteAccounting::new(
            ByteCount::new(1_000),
            ByteCount::new(1_000),
            MeasuredCount::Known(ByteCount::new(0)),
        )
        .unwrap(),
        in_flight.clone(),
    );
    assert!(
        CaptureObservation::new(
            policy(
                deadline,
                Some(event_limit),
                None,
                SettlementPolicy::Disabled,
            ),
            window(1_000_000),
            event_limited_state,
            CaptureTermination::EventLimitReached { event_limit },
        )
        .is_ok()
    );

    let byte_limited_state = TerminalObservationState::new(
        CaptureOffset::from_microseconds(1_000_000),
        EventAccounting::new(
            EventCount::new(5),
            EventCount::new(5),
            MeasuredCount::Known(EventCount::new(0)),
        )
        .unwrap(),
        ByteAccounting::new(
            ByteCount::new(10_000),
            ByteCount::new(9_000),
            MeasuredCount::Known(ByteCount::new(1_000)),
        )
        .unwrap(),
        in_flight,
    );
    assert!(
        CaptureObservation::new(
            policy(deadline, None, Some(byte_limit), SettlementPolicy::Disabled,),
            window(1_000_000),
            byte_limited_state,
            CaptureTermination::ByteLimitReached { byte_limit },
        )
        .is_ok()
    );
}
