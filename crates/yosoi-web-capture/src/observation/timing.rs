//! Relative time, count, limit, and wall-clock window types.

use std::num::NonZeroU64;

use chrono::{DateTime, Utc};
use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use thiserror::Error;
pub use yosoi_types::{
    ByteCount, ByteLimit, ByteLimitError, CaptureDeadline, CaptureDeadlineError, CaptureDuration,
    CaptureOffset, EventCount,
};

/// Error returned when a configured event limit is zero.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
#[error("event limit must be greater than zero")]
pub struct EventLimitError;

/// Non-zero maximum number of events admitted to the observation log.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct EventLimit(NonZeroU64);

impl EventLimit {
    /// Returns the configured event limit.
    pub const fn get(self) -> u64 {
        self.0.get()
    }
}

impl TryFrom<u64> for EventLimit {
    type Error = EventLimitError;

    fn try_from(value: u64) -> Result<Self, Self::Error> {
        NonZeroU64::new(value).map(Self).ok_or(EventLimitError)
    }
}

impl From<EventLimit> for u64 {
    fn from(value: EventLimit) -> Self {
        value.get()
    }
}

impl<'de> Deserialize<'de> for EventLimit {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        u64::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}

/// Number of activities still in flight.
#[derive(
    Clone, Copy, Debug, Default, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize,
)]
#[serde(transparent)]
pub struct ActivityCount(u64);

impl ActivityCount {
    /// Creates an activity count.
    pub const fn new(value: u64) -> Self {
        Self(value)
    }

    /// Returns the count.
    pub const fn get(self) -> u64 {
        self.0
    }
}

/// Configured hard bounds for one observation window.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ObservationLimits {
    maximum_elapsed: CaptureDeadline,
    event_limit: Option<EventLimit>,
    byte_limit: Option<ByteLimit>,
}

impl ObservationLimits {
    /// Creates limits with a mandatory elapsed-time bound.
    pub const fn new(
        maximum_elapsed: CaptureDeadline,
        event_limit: Option<EventLimit>,
        byte_limit: Option<ByteLimit>,
    ) -> Self {
        Self {
            maximum_elapsed,
            event_limit,
            byte_limit,
        }
    }

    /// Returns the mandatory maximum elapsed duration.
    pub const fn maximum_elapsed(&self) -> CaptureDeadline {
        self.maximum_elapsed
    }

    /// Returns the optional admitted-event bound.
    pub const fn event_limit(&self) -> Option<EventLimit> {
        self.event_limit
    }

    /// Returns the optional admitted-byte bound.
    pub const fn byte_limit(&self) -> Option<ByteLimit> {
        self.byte_limit
    }
}

/// Error returned when an observed wall-clock window is invalid.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
#[error("observation finish time cannot precede start time")]
pub struct ObservationWindowError;

/// Absolute correlation timestamps and monotonic elapsed duration.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct ObservationWindow {
    started_at: DateTime<Utc>,
    finished_at: DateTime<Utc>,
    elapsed: CaptureDuration,
}

impl ObservationWindow {
    /// Creates a window after checking wall-clock ordering.
    pub fn new(
        started_at: DateTime<Utc>,
        finished_at: DateTime<Utc>,
        elapsed: CaptureDuration,
    ) -> Result<Self, ObservationWindowError> {
        if finished_at < started_at {
            return Err(ObservationWindowError);
        }
        Ok(Self {
            started_at,
            finished_at,
            elapsed,
        })
    }

    /// Returns when observation began according to the wall clock.
    pub const fn started_at(&self) -> &DateTime<Utc> {
        &self.started_at
    }

    /// Returns when observation ended according to the wall clock.
    pub const fn finished_at(&self) -> &DateTime<Utc> {
        &self.finished_at
    }

    /// Returns the independently measured monotonic elapsed duration.
    pub const fn elapsed(&self) -> CaptureDuration {
        self.elapsed
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ObservationWindowWire {
    started_at: DateTime<Utc>,
    finished_at: DateTime<Utc>,
    elapsed: CaptureDuration,
}

impl TryFrom<ObservationWindowWire> for ObservationWindow {
    type Error = ObservationWindowError;

    fn try_from(value: ObservationWindowWire) -> Result<Self, Self::Error> {
        Self::new(value.started_at, value.finished_at, value.elapsed)
    }
}

impl<'de> Deserialize<'de> for ObservationWindow {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        ObservationWindowWire::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}
