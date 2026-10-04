#![allow(clippy::unwrap_used, reason = "deterministic boundary fixtures")]

use chrono::{DateTime, TimeDelta, Utc};
use yosoi_types::{CaptureId, ReasonCode};
use yosoi_web_capture::*;

const fn start() -> DateTime<Utc> {
    DateTime::from_timestamp(1_700_000_000, 0).unwrap()
}

fn lifecycle() -> BoundedAcquisitionLifecycle {
    BoundedAcquisitionLifecycle::start(
        CaptureId::random(),
        ObservationPolicy::new(
            ObservationLimits::new(CaptureDeadline::try_from(100).unwrap(), None, None),
            SettlementPolicy::Disabled,
        ),
        start(),
    )
}

fn terminal(at: u64) -> TerminalObservationState {
    let unavailable = || MeasuredCount::Unavailable {
        reason: ReasonCode::new("test.collector-not-measured").unwrap(),
    };
    TerminalObservationState::new(
        CaptureOffset::from_microseconds(at),
        EventAccounting::new(EventCount::new(2), EventCount::new(1), unavailable()).unwrap(),
        ByteAccounting::new(
            ByteCount::new(10),
            ByteCount::new(8),
            MeasuredCount::Unavailable {
                reason: ReasonCode::new("test.collector-not-measured").unwrap(),
            },
        )
        .unwrap(),
        InFlightActivity::new(ActivityCount::new(0), ActivityCount::new(0)).unwrap(),
    )
}

const fn completed() -> CaptureTermination {
    CaptureTermination::ControllerStopped(ControllerStopReason::GoalSatisfied)
}

#[test]
fn aggregate_collector_preserves_unknown_loss_without_synthetic_events() {
    let observation = lifecycle()
        .finish_from_accounting(
            start()
                .checked_add_signed(TimeDelta::microseconds(50))
                .unwrap(),
            terminal(50),
            completed(),
        )
        .unwrap();
    assert_eq!(observation.terminal_state().events().admitted().get(), 2);
    assert!(matches!(
        observation.terminal_state().bytes().dropped(),
        MeasuredCount::Unavailable { .. }
    ));
}

#[test]
fn aggregate_collector_can_feed_the_shared_lifecycle_before_publication() {
    let mut lifecycle = lifecycle();
    let terminal = terminal(50);
    lifecycle.adopt_accounting(&terminal, &completed()).unwrap();
    assert_eq!(lifecycle.observed_through().as_microseconds(), 50);
    assert_eq!(lifecycle.admitted_events(), 2);
    assert_eq!(lifecycle.retained_events(), 1);
    assert_eq!(lifecycle.admitted_bytes(), 10);
    assert_eq!(lifecycle.retained_bytes(), 8);
    assert_eq!(lifecycle.termination(), Some(&completed()));
    assert!(
        lifecycle
            .finish_from_accounting(
                start()
                    .checked_add_signed(TimeDelta::microseconds(50))
                    .unwrap(),
                terminal,
                completed(),
            )
            .is_ok()
    );
}

#[test]
fn aggregate_completion_cannot_rewind_the_live_clock() {
    let mut lifecycle = lifecycle();
    lifecycle
        .observe_through(CaptureOffset::from_microseconds(60))
        .unwrap();
    assert_eq!(
        lifecycle.finish_from_accounting(
            start()
                .checked_add_signed(TimeDelta::microseconds(60))
                .unwrap(),
            terminal(50),
            completed(),
        ),
        Err(AcquisitionObservationError::AccountingRegression)
    );
}

#[test]
fn terminal_reason_cannot_replace_an_already_observed_deadline() {
    let mut lifecycle = lifecycle();
    lifecycle
        .observe_through(CaptureOffset::from_microseconds(100))
        .unwrap();
    assert_eq!(
        lifecycle.finish_from_accounting(
            start()
                .checked_add_signed(TimeDelta::microseconds(100))
                .unwrap(),
            terminal(100),
            completed(),
        ),
        Err(AcquisitionObservationError::TerminationMismatch)
    );
}

#[test]
fn stopped_lifecycle_rejects_later_accounting_even_with_the_same_reason() {
    let mut lifecycle = lifecycle();
    lifecycle
        .stop(
            CaptureOffset::from_microseconds(40),
            LifecycleStop::Completed(ControllerStopReason::GoalSatisfied),
        )
        .unwrap();
    assert_eq!(
        lifecycle.finish_from_accounting(
            start()
                .checked_add_signed(TimeDelta::microseconds(50))
                .unwrap(),
            terminal(50),
            completed(),
        ),
        Err(AcquisitionObservationError::StoppedAccountingMismatch)
    );
}

#[test]
fn fresh_aggregate_and_live_paths_enforce_the_same_deadline_policy() {
    let end = start()
        .checked_add_signed(TimeDelta::microseconds(101))
        .unwrap();
    assert_eq!(
        lifecycle().finish_from_accounting(end, terminal(101), completed()),
        Err(AcquisitionObservationError::Observation(
            CaptureObservationError::WindowExceedsMaximum
        ))
    );
}
