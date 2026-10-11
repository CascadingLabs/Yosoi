#![no_main]

use chrono::{DateTime, Utc};
use libfuzzer_sys::fuzz_target;
use yosoi_dev_support::internal::types::{CaptureDeadline, CaptureId};
use yosoi_dev_support::internal::web_capture::{
    BoundedAcquisitionLifecycle, ByteCount, ByteLimit, CaptureOffset, LifecycleEvent,
    ObservationLimits, ObservationPolicy, SettlementPolicy,
};

fuzz_target!(|data: &[u8]| {
    let capture_id: CaptureId = "123e4567-e89b-42d3-a456-426614174001"
        .parse()
        .unwrap_or_else(|error| panic!("fixed capture ID is invalid: {error}"));
    let started_at: DateTime<Utc> = DateTime::from_timestamp(1_700_000_000, 0)
        .unwrap_or_else(|| panic!("fixed timestamp is invalid"));
    let policy = ObservationPolicy::new(
        ObservationLimits::new(
            CaptureDeadline::try_from(1_000).unwrap_or_else(|error| panic!("limit: {error}")),
            None,
            Some(ByteLimit::try_from(4_096_u64).unwrap_or_else(|error| panic!("limit: {error}"))),
        ),
        SettlementPolicy::Disabled,
    );
    let mut lifecycle = BoundedAcquisitionLifecycle::start(capture_id, policy, started_at);
    for operation in data.chunks_exact(5).take(512) {
        let offset = u64::from(u16::from_le_bytes([operation[0], operation[1]]));
        let offered = u64::from(u16::from_le_bytes([operation[2], operation[3]]));
        let retained = operation[4] & 1 == 1;
        let event = LifecycleEvent::new(
            CaptureOffset::from_microseconds(offset),
            ByteCount::new(offered),
            ByteCount::new(if retained { offered } else { 0 }),
            retained,
        )
        .unwrap_or_else(|error| panic!("generated event is invalid: {error}"));
        let _ = lifecycle.admit(event);
        assert!(lifecycle.retained_events() <= lifecycle.admitted_events());
        assert!(lifecycle.retained_bytes() <= lifecycle.admitted_bytes());
        assert!(lifecycle.admitted_bytes() <= 4_096);
        assert!(lifecycle.observed_through().as_microseconds() <= 1_000);
    }
});
