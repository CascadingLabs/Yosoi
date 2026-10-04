#![allow(clippy::unwrap_used, reason = "fixed nonzero test fixtures")]

use super::*;
use crate::{CaptureDeadline, SettlementPolicy};

fn observation(event_limit: Option<u64>) -> ObservationPolicy {
    ObservationPolicy::new(
        ObservationLimits::new(
            CaptureDeadline::try_from(100).unwrap(),
            event_limit.map(|limit| EventLimit::try_from(limit).unwrap()),
            None,
        ),
        SettlementPolicy::Disabled,
    )
}

#[test]
fn provider_event_bound_is_the_effective_observation_limit() {
    let effective =
        bind_provider_event_limit(&observation(None), NonZeroU64::new(7).unwrap()).unwrap();
    assert_eq!(
        effective.limits().event_limit().map(EventLimit::get),
        Some(7)
    );
}

#[test]
fn contradictory_event_limits_are_rejected() {
    assert_eq!(
        bind_provider_event_limit(&observation(Some(6)), NonZeroU64::new(7).unwrap()),
        Err(BrowserCaptureSpecError::EventLimitMismatch)
    );
}
