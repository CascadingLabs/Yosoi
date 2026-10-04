use super::support::*;
use chrono::Duration;
use yosoi_types::ReasonCode;
use yosoi_web_capture_direct_http::{
    ByteCount, CaptureBundleError, CaptureOffset, EventCount, LifecycleError, MeasuredCount,
    StagedPayloadError, StagedPayloads,
};

#[test]
fn known_zero_and_nonzero_drops_finalize_with_exact_accounting() {
    for (events, bytes) in [(0_u64, 0_u64), (7, 19)] {
        let (capture, spec) = spec(None, None, 2_000_000);
        let mut lifecycle = TestLifecycle::start(spec, started_at(&capture));
        for index in 0..events {
            let admitted = if index == 0 {
                bytes.saturating_sub(events - 1)
            } else {
                1
            };
            lifecycle
                .admit(event(index + 1, admitted, 0, false))
                .unwrap();
        }
        lifecycle
            .stop(
                CaptureOffset::from_microseconds(1_000_000),
                yosoi_web_capture_direct_http::LifecycleStop::Completed(
                    yosoi_web_capture_direct_http::ControllerStopReason::GoalSatisfied,
                ),
            )
            .unwrap();
        let bundle = lifecycle
            .finalize(input(
                &capture,
                MeasuredCount::Known(EventCount::new(events)),
                MeasuredCount::Known(ByteCount::new(bytes)),
                valid_payloads(&capture),
            ))
            .unwrap();
        let terminal = bundle.capture().observation().terminal_state();
        assert_eq!(
            terminal.events().dropped(),
            &MeasuredCount::Known(EventCount::new(events))
        );
        assert_eq!(
            terminal.bytes().dropped(),
            &MeasuredCount::Known(ByteCount::new(bytes))
        );
    }
}

#[test]
fn unavailable_event_and_byte_drops_finalize_truthfully() {
    let reason = ReasonCode::new("capture.measurement-unavailable").unwrap();
    let (capture, lifecycle) = stopped();
    let bundle = lifecycle
        .finalize(input(
            &capture,
            MeasuredCount::Unavailable {
                reason: reason.clone(),
            },
            MeasuredCount::Unavailable {
                reason: reason.clone(),
            },
            valid_payloads(&capture),
        ))
        .unwrap();
    assert_eq!(
        bundle
            .capture()
            .observation()
            .terminal_state()
            .events()
            .dropped(),
        &MeasuredCount::Unavailable {
            reason: reason.clone()
        }
    );
    assert_eq!(
        bundle
            .capture()
            .observation()
            .terminal_state()
            .bytes()
            .dropped(),
        &MeasuredCount::Unavailable { reason }
    );
}

#[test]
fn retained_receipt_outputs_are_preserved_in_manifest_order() {
    let (capture, lifecycle) = stopped();
    let bundle = lifecycle
        .finalize(input(
            &capture,
            MeasuredCount::Known(EventCount::new(0)),
            MeasuredCount::Known(ByteCount::new(0)),
            valid_payloads(&capture),
        ))
        .unwrap();
    let outputs = bundle.capture().acquisition().receipt().receipt().outputs();
    assert_eq!(outputs.len(), 2);
    assert_eq!(
        outputs[0].availability(),
        yosoi_types::ArtifactAvailability::Retained
    );
    assert_eq!(
        outputs[1].availability(),
        yosoi_types::ArtifactAvailability::Retained
    );
}

#[test]
fn terminal_offset_below_equal_and_above_stopped_offset_are_distinguished() {
    for (terminal, expected) in [(999_999, "behind"), (1_000_001, "mismatch")] {
        let (capture, lifecycle) = stopped();
        let mut value = input(
            &capture,
            MeasuredCount::Known(EventCount::new(0)),
            MeasuredCount::Known(ByteCount::new(0)),
            valid_payloads(&capture),
        );
        value.terminal_offset = CaptureOffset::from_microseconds(terminal);
        let error = lifecycle.finalize(value).unwrap_err();
        assert!(match (expected, error) {
            ("behind", LifecycleError::TerminalOffsetBehind { .. })
            | ("mismatch", LifecycleError::TerminalOffsetMismatch) => true,
            _ => false,
        });
    }
    let (capture, lifecycle) = stopped();
    assert!(
        lifecycle
            .finalize(input(
                &capture,
                MeasuredCount::Known(EventCount::new(0)),
                MeasuredCount::Known(ByteCount::new(0)),
                valid_payloads(&capture)
            ))
            .is_ok()
    );
}

#[test]
fn invalid_wall_clock_order_returns_error_and_no_bundle() {
    let (capture, lifecycle) = stopped();
    let mut value = input(
        &capture,
        MeasuredCount::Known(EventCount::new(0)),
        MeasuredCount::Known(ByteCount::new(0)),
        valid_payloads(&capture),
    );
    value.finished_at = started_at(&capture) - Duration::seconds(1);
    assert!(matches!(
        lifecycle.finalize(value),
        Err(LifecycleError::ObservationWindow(_))
    ));
}

#[test]
fn missing_wrong_size_and_wrong_digest_are_nested_bundle_errors() {
    let (capture, lifecycle) = stopped();
    let value = input(
        &capture,
        MeasuredCount::Known(EventCount::new(0)),
        MeasuredCount::Known(ByteCount::new(0)),
        StagedPayloads::default(),
    );
    assert!(matches!(
        lifecycle.finalize(value),
        Err(LifecycleError::Bundle(CaptureBundleError::Missing))
    ));

    let (capture, lifecycle) = stopped();
    let mut payloads = StagedPayloads::default();
    let source = capture.artifacts().results().source().artifacts().unwrap();
    payloads
        .insert(source[0].reference().into(), b"tiny!".to_vec())
        .unwrap();
    assert!(matches!(
        lifecycle.finalize(input(
            &capture,
            MeasuredCount::Known(EventCount::new(0)),
            MeasuredCount::Known(ByteCount::new(0)),
            payloads
        )),
        Err(LifecycleError::Bundle(CaptureBundleError::DigestMismatch))
    ));

    let (capture, lifecycle) = stopped();
    let mut payloads = StagedPayloads::default();
    payloads
        .insert(
            capture.artifacts().results().source().artifacts().unwrap()[0]
                .reference()
                .into(),
            b"x".to_vec(),
        )
        .unwrap();
    assert!(matches!(
        lifecycle.finalize(input(
            &capture,
            MeasuredCount::Known(EventCount::new(0)),
            MeasuredCount::Known(ByteCount::new(0)),
            payloads
        )),
        Err(LifecycleError::Bundle(CaptureBundleError::SizeMismatch))
    ));
}

#[test]
fn staged_payload_duplicate_is_rejected_before_finalization() {
    let capture = fixture();
    let reference = capture.artifacts().results().source().artifacts().unwrap()[0]
        .reference()
        .into();
    let mut payloads = StagedPayloads::default();
    payloads.insert(reference, FIRST.to_vec()).unwrap();
    assert_eq!(
        payloads.insert(reference, FIRST.to_vec()),
        Err(StagedPayloadError::Duplicate)
    );
}
