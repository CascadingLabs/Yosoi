use super::support::*;
use crate::internal::direct_http as internal_direct_http;
use crate::internal::direct_http::{
    BoundedAcquisitionError as LifecycleError, ByteCount, CaptureOffset, CaptureTermination,
    ControllerStopReason, EventAdmission, InterruptionEvidence, InterruptionInitiator,
    LifecycleStop,
};
use crate::internal::types::ReasonCode;

#[test]
fn exact_event_boundary_and_simultaneous_precedence_preserve_partial_byte_facts() {
    let (capture, spec) = spec(Some(1), Some(5), 100);
    let mut lifecycle = TestLifecycle::start(spec, started_at(&capture));
    assert!(
        matches!(lifecycle.admit(event(10, 99, 70, true)).unwrap(), EventAdmission::AdmittedAndStopped { admitted, termination: CaptureTermination::EventLimitReached { .. } } if admitted.admitted_bytes().get() == 5 && admitted.retained_bytes().get() == 5 && admitted.is_event_retained())
    );
    assert!(matches!(
        lifecycle.admit(event(11, 1, 1, true)),
        Err(LifecycleError::AlreadyStopped)
    ));
}

#[test]
fn exact_byte_boundary_stops_and_partial_event_facts_are_exact() {
    let (capture, spec) = spec(None, Some(5), 100);
    let mut lifecycle = TestLifecycle::start(spec, started_at(&capture));
    lifecycle.admit(event(1, 3, 2, true)).unwrap();
    assert!(
        matches!(lifecycle.admit(event(2, 9, 8, false)).unwrap(), EventAdmission::AdmittedAndStopped { admitted, termination: CaptureTermination::ByteLimitReached { .. } } if admitted.admitted_bytes().get() == 2 && admitted.retained_bytes().get() == 2 && !admitted.is_event_retained())
    );
}

#[test]
fn offers_before_deadline_admit_while_at_and_after_deadline_do_not() {
    for offset in [100, 101] {
        let (capture, spec) = spec(None, None, 100);
        let mut lifecycle = TestLifecycle::start(spec, started_at(&capture));
        assert!(matches!(
            lifecycle.admit(event(offset, 4, 4, true)).unwrap(),
            EventAdmission::NotAdmittedAndStopped(CaptureTermination::DeadlineReached { .. })
        ));
    }
    let (capture, spec) = spec(None, None, 100);
    let mut lifecycle = TestLifecycle::start(spec, started_at(&capture));
    assert!(matches!(
        lifecycle.admit(event(99, 4, 4, true)).unwrap(),
        EventAdmission::Admitted(_)
    ));
}

#[test]
fn observe_and_stop_at_or_above_deadline_clamp_to_deadline() {
    for requested in [100, 101] {
        let (capture, spec) = spec(None, None, 100);
        let mut lifecycle = TestLifecycle::start(spec, started_at(&capture));
        lifecycle
            .stop(
                CaptureOffset::from_microseconds(requested),
                LifecycleStop::Completed(ControllerStopReason::GoalSatisfied),
            )
            .unwrap();
        assert!(matches!(
            lifecycle.termination(),
            Some(CaptureTermination::DeadlineReached { .. })
        ));
    }
}

#[test]
fn lower_offsets_are_non_monotonic_and_equal_offsets_are_allowed() {
    let (capture, spec) = spec(None, None, 100);
    let mut lifecycle = TestLifecycle::start(spec, started_at(&capture));
    lifecycle
        .observe_through(CaptureOffset::from_microseconds(10))
        .unwrap();
    assert!(
        lifecycle
            .observe_through(CaptureOffset::from_microseconds(10))
            .is_ok()
    );
    assert!(matches!(
        lifecycle.observe_through(CaptureOffset::from_microseconds(9)),
        Err(LifecycleError::NonMonotonic {
            offered: 9,
            previous: 10
        })
    ));
}

#[test]
fn every_terminal_reason_rejects_all_later_operations() {
    let stops = [
        LifecycleStop::Completed(ControllerStopReason::GoalSatisfied),
        LifecycleStop::Interrupted(InterruptionEvidence::new(
            InterruptionInitiator::Caller,
            ReasonCode::new("capture.caller").unwrap(),
        )),
        LifecycleStop::Interrupted(InterruptionEvidence::new(
            InterruptionInitiator::Provider,
            ReasonCode::new("capture.provider").unwrap(),
        )),
        LifecycleStop::Interrupted(InterruptionEvidence::new(
            InterruptionInitiator::System,
            ReasonCode::new("capture.system").unwrap(),
        )),
    ];
    for stop in stops {
        let (capture, spec) = spec(None, None, 100);
        let mut lifecycle = TestLifecycle::start(spec, started_at(&capture));
        lifecycle
            .stop(CaptureOffset::from_microseconds(1), stop)
            .unwrap();
        assert!(matches!(
            lifecycle.admit(event(2, 0, 0, false)),
            Err(LifecycleError::AlreadyStopped)
        ));
        assert!(matches!(
            lifecycle.observe_through(CaptureOffset::from_microseconds(2)),
            Err(LifecycleError::AlreadyStopped)
        ));
        assert!(matches!(
            lifecycle.stop(
                CaptureOffset::from_microseconds(2),
                LifecycleStop::Completed(ControllerStopReason::GoalSatisfied)
            ),
            Err(LifecycleError::AlreadyStopped)
        ));
    }
    for (events, bytes) in [(Some(1), None), (None, Some(1))] {
        let (capture, spec) = spec(events, bytes, 100);
        let mut lifecycle = TestLifecycle::start(spec, started_at(&capture));
        lifecycle.admit(event(1, 1, 1, true)).unwrap();
        assert!(matches!(
            lifecycle.admit(event(2, 0, 0, false)),
            Err(LifecycleError::AlreadyStopped)
        ));
    }
}

#[test]
fn malformed_event_is_rejected_before_mutation() {
    assert!(
        internal_direct_http::LifecycleEvent::new(
            CaptureOffset::from_microseconds(1),
            ByteCount::new(1),
            ByteCount::new(2),
            true
        )
        .is_err()
    );
}
