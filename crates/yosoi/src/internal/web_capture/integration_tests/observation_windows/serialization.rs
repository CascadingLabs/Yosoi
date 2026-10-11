use super::{support::*, *};

#[test]
fn every_terminal_outcome_round_trips_through_json() {
    let deadline = CaptureDeadline::try_from(5_000_000).unwrap();
    let event_limit = EventLimit::try_from(100).unwrap();
    let byte_limit = ByteLimit::try_from(10_000_u64).unwrap();
    let settlement_id = SettlementPolicyId::new("com.cascadinglabs.yosoi.quiet").unwrap();
    let cases = [
        CaptureObservation::new(
            quiet_policy(settlement_id.clone(), 500_000, 0),
            window(500_000),
            terminal_state_at(500_000, 5, 512, 2, 0),
            CaptureTermination::Settled(
                SettlementEvidence::new(
                    settlement_id,
                    CaptureOffset::from_microseconds(0),
                    CaptureOffset::from_microseconds(500_000),
                    ActivityCount::new(0),
                    quiet_event_accounting(),
                )
                .unwrap(),
            ),
        )
        .unwrap(),
        controller_stopped_observation(5_000_000),
        CaptureObservation::new(
            policy(deadline, None, None, SettlementPolicy::Disabled),
            window(5_000_000),
            terminal_state_at(5_000_000, 5, 512, 2, 1),
            CaptureTermination::DeadlineReached {
                maximum_elapsed: deadline,
            },
        )
        .unwrap(),
        CaptureObservation::new(
            policy(
                deadline,
                Some(event_limit),
                None,
                SettlementPolicy::Disabled,
            ),
            window(1_000_000),
            terminal_state(100, 512, 2, 1),
            CaptureTermination::EventLimitReached { event_limit },
        )
        .unwrap(),
        CaptureObservation::new(
            policy(deadline, None, Some(byte_limit), SettlementPolicy::Disabled),
            window(1_000_000),
            terminal_state(5, 10_000, 2, 1),
            CaptureTermination::ByteLimitReached { byte_limit },
        )
        .unwrap(),
        CaptureObservation::new(
            policy(deadline, None, None, SettlementPolicy::Disabled),
            window(1_000_000),
            terminal_state(5, 512, 2, 1),
            CaptureTermination::Interrupted(InterruptionEvidence::new(
                InterruptionInitiator::Caller,
                ReasonCode::new("capture.cancelled-by-caller").unwrap(),
            )),
        )
        .unwrap(),
    ];

    for case in cases {
        let encoded = serde_json::to_value(&case).unwrap();
        assert_eq!(
            serde_json::from_value::<CaptureObservation>(encoded).unwrap(),
            case
        );
    }
}

#[test]
fn unavailable_in_flight_measurements_round_trip_without_inventing_zero() {
    let reason = ReasonCode::new("browser.in-flight.not-observed").unwrap();
    let in_flight = InFlightActivity::measured(
        MeasuredCount::Known(ActivityCount::new(2)),
        MeasuredCount::Unavailable { reason },
    )
    .unwrap();
    let encoded = serde_json::to_value(&in_flight).unwrap();
    assert_eq!(
        encoded,
        json!({
            "total": { "status": "known", "value": 2 },
            "settlement_relevant": {
                "status": "unavailable",
                "value": { "reason": "browser.in-flight.not-observed" }
            }
        })
    );
    assert_eq!(
        serde_json::from_value::<InFlightActivity>(encoded).unwrap(),
        in_flight
    );
}

#[test]
fn invalid_wire_states_do_not_bypass_domain_validation() {
    let valid = serde_json::to_value(controller_stopped_observation(5_000_000)).unwrap();

    let mut zero_deadline = valid.clone();
    zero_deadline["policy"]["limits"]["maximum_elapsed"] = json!(0);
    assert!(serde_json::from_value::<CaptureObservation>(zero_deadline).is_err());

    let mut reversed_window = valid.clone();
    reversed_window["window"]["started_at"] = json!("2026-09-05T00:00:02Z");
    assert!(serde_json::from_value::<CaptureObservation>(reversed_window).is_err());

    let mut unknown_field = valid;
    unknown_field["terminal_state"]["secret_provider_state"] = json!(true);
    assert!(serde_json::from_value::<CaptureObservation>(unknown_field).is_err());

    let invalid_settled = json!({
        "policy": {
            "limits": {
                "maximum_elapsed": 5_000_000,
                "event_limit": null,
                "byte_limit": null
            },
            "settlement": { "kind": "disabled" }
        },
        "window": {
            "started_at": "2026-09-05T00:00:00Z",
            "finished_at": "2026-09-05T00:00:01Z",
            "elapsed": 1_000_000
        },
        "terminal_state": terminal_state_json(),
        "termination": {
            "outcome": "settled",
            "evidence": {
                "policy": "com.cascadinglabs.yosoi.quiet",
                "quiet_since": 0,
                "satisfied_at": 500_000,
                "relevant_in_flight": 0,
                "quiet_period_events": {
                    "admitted": 0,
                    "retained": 0,
                    "dropped": {
                        "status": "known",
                        "value": 0
                    }
                }
            }
        }
    });
    assert!(serde_json::from_value::<CaptureObservation>(invalid_settled).is_err());
}

#[test]
fn terminal_observation_has_an_inspectable_stable_json_shape() {
    let observation = controller_stopped_observation(5_000_000);
    let encoded = serde_json::to_value(&observation).unwrap();

    assert_eq!(
        encoded,
        json!({
            "policy": {
                "limits": {
                    "maximum_elapsed": 5_000_000,
                    "event_limit": null,
                    "byte_limit": null
                },
                "settlement": { "kind": "disabled" }
            },
            "window": {
                "started_at": "2026-09-05T00:00:00Z",
                "finished_at": "2026-09-05T00:00:01Z",
                "elapsed": 1_000_000
            },
            "terminal_state": terminal_state_json(),
            "termination": {
                "outcome": "controller_stopped",
                "evidence": "goal_satisfied"
            }
        })
    );
    assert_eq!(
        serde_json::from_value::<CaptureObservation>(encoded).unwrap(),
        observation
    );
}
