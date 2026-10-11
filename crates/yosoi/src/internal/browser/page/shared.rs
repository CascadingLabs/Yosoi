use crate::internal::browser::vendor::chromiumoxide::listeners::EventListenerConfig;
use crate::internal::browser::vendor::chromiumoxide::listeners::EventOverflowPolicy;
use std::num::NonZeroUsize;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

pub(super) fn event_listener_config(
    capacity: usize,
    overflow: EventOverflowPolicy,
) -> EventListenerConfig {
    EventListenerConfig::new(
        NonZeroUsize::new(capacity).unwrap_or(NonZeroUsize::MIN),
        overflow,
    )
}

pub(super) fn unix_millis_now() -> Option<u64> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .ok()
        .and_then(|duration| u64::try_from(duration.as_millis()).ok())
}
