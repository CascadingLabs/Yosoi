#![allow(
    clippy::arithmetic_side_effects,
    clippy::unwrap_used,
    reason = "bounded property generators and test assertions"
)]

use chrono::{DateTime, Utc};
use proptest::{
    collection::vec,
    prelude::*,
    test_runner::{Config, FileFailurePersistence},
};
use yosoi_types::CaptureId;
use yosoi_web_capture::{
    BoundedAcquisitionLifecycle, ByteCount, ByteLimit, CaptureDeadline, CaptureOffset,
    EventAdmission, LifecycleEvent, ObservationLimits, ObservationPolicy, RequestedWebTarget,
    SettlementPolicy, SourceRepresentationEvidence, WebCaptureWire,
};

const REGRESSIONS: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/tests/property-regressions/property_hardening.txt"
);

fn cases() -> Config {
    Config {
        cases: 128,
        max_shrink_iters: 2_048,
        failure_persistence: Some(Box::new(FileFailurePersistence::Direct(REGRESSIONS))),
        ..Config::default()
    }
}

proptest! {
    #![proptest_config(cases())]

    #[test]
    fn arbitrary_wire_input_is_fail_closed_and_successes_are_canonical(
        bytes in vec(any::<u8>(), 0..16_384)
    ) {
        if let Ok(capture) = WebCaptureWire::from_json(&bytes) {
            let canonical = WebCaptureWire::to_canonical_json(&capture).unwrap();
            let reparsed = WebCaptureWire::from_json(&canonical).unwrap();
            prop_assert_eq!(WebCaptureWire::to_canonical_json(&reparsed).unwrap(), canonical);
        }
    }

    #[test]
    fn arbitrary_source_evidence_is_fail_closed_and_successes_round_trip(
        bytes in vec(any::<u8>(), 0..8_192)
    ) {
        if let Ok(evidence) = SourceRepresentationEvidence::from_json(&bytes) {
            let canonical = evidence.to_canonical_json().unwrap();
            prop_assert_eq!(SourceRepresentationEvidence::from_json(&canonical).unwrap(), evidence);
        }
    }

    #[test]
    fn provider_neutral_urls_have_canonical_round_trips(value in ".{0,2048}") {
        if let Ok(target) = RequestedWebTarget::parse(&value) {
            prop_assert!(target.as_str().starts_with("http://") || target.as_str().starts_with("https://"));
            prop_assert_eq!(RequestedWebTarget::parse(target.as_str()), Ok(target));
        }
    }

    #[test]
    fn lifecycle_operations_preserve_monotonic_bounded_accounting(
        operations in vec((0_u16..250, 0_u16..80, any::<bool>()), 0..128)
    ) {
        let policy = ObservationPolicy::new(
            ObservationLimits::new(
                CaptureDeadline::try_from(200).unwrap(),
                None,
                Some(ByteLimit::try_from(100_u64).unwrap()),
            ),
            SettlementPolicy::Disabled,
        );
        let started_at: DateTime<Utc> = DateTime::from_timestamp(1_700_000_000, 0).unwrap();
        let mut lifecycle = BoundedAcquisitionLifecycle::start(CaptureId::random(), policy, started_at);
        let mut previous = 0_u64;
        for (offered_offset, offered_bytes, retain) in operations {
            let offset = u64::from(offered_offset);
            let bytes = u64::from(offered_bytes);
            let event = LifecycleEvent::new(
                CaptureOffset::from_microseconds(offset),
                ByteCount::new(bytes),
                ByteCount::new(if retain { bytes } else { 0 }),
                retain,
            ).unwrap();
            let was_stopped = lifecycle.termination().is_some();
            let result = lifecycle.admit(event);
            if was_stopped || offset < previous {
                prop_assert!(result.is_err());
            }
            previous = previous.max(offset.min(200));
            prop_assert!(lifecycle.retained_events() <= lifecycle.admitted_events());
            prop_assert!(lifecycle.retained_bytes() <= lifecycle.admitted_bytes());
            prop_assert!(lifecycle.admitted_bytes() <= 100);
            prop_assert!(lifecycle.observed_through().as_microseconds() <= 200);
            if matches!(result, Ok(EventAdmission::AdmittedAndStopped { .. } | EventAdmission::NotAdmittedAndStopped(_))) {
                prop_assert!(lifecycle.termination().is_some());
            }
        }
    }
}
