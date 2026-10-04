use super::*;

#[allow(
    clippy::unwrap_used,
    reason = "test fixture values are deliberately valid constants"
)]
pub fn controller_stopped_observation(maximum_elapsed_us: u64) -> CaptureObservation {
    let policy = policy(
        CaptureDeadline::try_from(maximum_elapsed_us).unwrap(),
        None,
        None,
        SettlementPolicy::Disabled,
    );
    CaptureObservation::new(
        policy,
        window(1_000_000),
        terminal_state(5, 512, 0, 0),
        CaptureTermination::ControllerStopped(ControllerStopReason::GoalSatisfied),
    )
    .unwrap()
}

#[allow(
    clippy::unwrap_used,
    reason = "test fixture values are deliberately valid constants"
)]
pub fn quiet_policy(
    id: SettlementPolicyId,
    required_quiet_us: u64,
    maximum_relevant_in_flight: u64,
) -> ObservationPolicy {
    policy(
        CaptureDeadline::try_from(5_000_000).unwrap(),
        None,
        None,
        SettlementPolicy::QuietPeriod(QuietPeriodPolicy::new(
            id,
            QuietPeriod::try_from(required_quiet_us).unwrap(),
            ActivityCount::new(maximum_relevant_in_flight),
        )),
    )
}

pub const fn policy(
    maximum_elapsed: CaptureDeadline,
    event_limit: Option<EventLimit>,
    byte_limit: Option<ByteLimit>,
    settlement: SettlementPolicy,
) -> ObservationPolicy {
    ObservationPolicy::new(
        ObservationLimits::new(maximum_elapsed, event_limit, byte_limit),
        settlement,
    )
}

#[allow(
    clippy::unwrap_used,
    reason = "test fixture values are deliberately valid constants"
)]
pub fn window(elapsed_us: u64) -> ObservationWindow {
    ObservationWindow::new(
        timestamp("2026-09-05T00:00:00Z"),
        timestamp("2026-09-05T00:00:01Z"),
        CaptureDuration::from_microseconds(elapsed_us),
    )
    .unwrap()
}

#[allow(
    clippy::unwrap_used,
    reason = "test fixture values satisfy the in-flight subset invariant"
)]
pub fn terminal_state(
    retained_events: u64,
    retained_bytes: u64,
    total_in_flight: u64,
    relevant_in_flight: u64,
) -> TerminalObservationState {
    terminal_state_at(
        1_000_000,
        retained_events,
        retained_bytes,
        total_in_flight,
        relevant_in_flight,
    )
}

#[allow(
    clippy::unwrap_used,
    reason = "test fixture values use exact known-zero loss accounting"
)]
pub fn terminal_state_at(
    observed_through_us: u64,
    retained_events: u64,
    retained_bytes: u64,
    total_in_flight: u64,
    relevant_in_flight: u64,
) -> TerminalObservationState {
    TerminalObservationState::new(
        CaptureOffset::from_microseconds(observed_through_us),
        EventAccounting::new(
            EventCount::new(retained_events),
            EventCount::new(retained_events),
            MeasuredCount::Known(EventCount::new(0)),
        )
        .unwrap(),
        ByteAccounting::new(
            ByteCount::new(retained_bytes),
            ByteCount::new(retained_bytes),
            MeasuredCount::Known(ByteCount::new(0)),
        )
        .unwrap(),
        InFlightActivity::new(
            ActivityCount::new(total_in_flight),
            ActivityCount::new(relevant_in_flight),
        )
        .unwrap(),
    )
}

#[allow(
    clippy::unwrap_used,
    reason = "test quiet-period coverage is an exact known-zero event interval"
)]
pub fn quiet_event_accounting() -> EventAccounting {
    EventAccounting::new(
        EventCount::new(0),
        EventCount::new(0),
        MeasuredCount::Known(EventCount::new(0)),
    )
    .unwrap()
}

pub fn terminal_state_json() -> Value {
    json!({
        "observed_through": 1_000_000,
        "events": {
            "admitted": 5,
            "retained": 5,
            "dropped": {
                "status": "known",
                "value": 0
            }
        },
        "bytes": {
            "admitted": 512,
            "retained": 512,
            "dropped": {
                "status": "known",
                "value": 0
            }
        },
        "in_flight": {
            "total": 0,
            "settlement_relevant": 0
        }
    })
}

#[allow(
    clippy::unwrap_used,
    reason = "test fixture timestamps are deliberately valid constants"
)]
pub fn timestamp(value: &str) -> DateTime<Utc> {
    value.parse().unwrap()
}
