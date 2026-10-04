//! Dependency-light quantities shared by acquisition implementations.

use std::num::NonZeroU64;

use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use thiserror::Error;

/// An exact number of bytes.
#[derive(
    Clone, Copy, Debug, Default, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize,
)]
#[serde(transparent)]
pub struct ByteCount(u64);

impl ByteCount {
    pub const fn new(value: u64) -> Self {
        Self(value)
    }

    pub const fn get(self) -> u64 {
        self.0
    }

    /// Converts an address-space-sized count without truncating it.
    pub fn try_from_usize(value: usize) -> Result<Self, ByteCountOverflow> {
        u64::try_from(value)
            .map(Self)
            .map_err(|_| ByteCountOverflow)
    }
}

/// A platform-sized count cannot be represented by the canonical wire integer.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
#[error("byte count exceeds the supported integer representation")]
pub struct ByteCountOverflow;

/// Error returned when a byte limit is zero or cannot address a local buffer.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum ByteLimitError {
    #[error("byte limit must be greater than zero")]
    Zero,
    #[error("byte limit exceeds the supported platform size")]
    TooLarge,
}

impl From<ByteCountOverflow> for ByteLimitError {
    fn from(_: ByteCountOverflow) -> Self {
        Self::TooLarge
    }
}

/// A validated positive byte limit.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct ByteLimit(NonZeroU64);

impl ByteLimit {
    pub const fn one() -> Self {
        Self(NonZeroU64::MIN)
    }

    pub const fn get(self) -> u64 {
        self.0.get()
    }

    /// Converts this limit to the platform size used by in-memory buffers.
    pub fn as_usize(self) -> Result<usize, ByteLimitError> {
        usize::try_from(self.get()).map_err(|_| ByteLimitError::TooLarge)
    }
}

impl TryFrom<u64> for ByteLimit {
    type Error = ByteLimitError;

    fn try_from(value: u64) -> Result<Self, Self::Error> {
        NonZeroU64::new(value).map(Self).ok_or(ByteLimitError::Zero)
    }
}

impl TryFrom<usize> for ByteLimit {
    type Error = ByteLimitError;

    fn try_from(value: usize) -> Result<Self, Self::Error> {
        u64::try_from(value)
            .map_err(|_| ByteLimitError::TooLarge)?
            .try_into()
    }
}

impl From<ByteLimit> for u64 {
    fn from(value: ByteLimit) -> Self {
        value.get()
    }
}

impl<'de> Deserialize<'de> for ByteLimit {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        u64::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}

/// An exact number of events.
#[derive(
    Clone, Copy, Debug, Default, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize,
)]
#[serde(transparent)]
pub struct EventCount(u64);

impl EventCount {
    pub const fn new(value: u64) -> Self {
        Self(value)
    }

    pub const fn get(self) -> u64 {
        self.0
    }
}

/// A measured value that may be unavailable at its producer boundary.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(tag = "status", content = "value", rename_all = "snake_case")]
pub enum Measured<T, R> {
    /// The producer reported an exact value, including a known zero.
    Known(T),
    /// The producer could not report the value.
    Unavailable { reason: R },
}

impl<T, R> Measured<T, R> {
    pub const fn known(value: T) -> Self {
        Self::Known(value)
    }

    pub const fn as_known(&self) -> Option<&T> {
        match self {
            Self::Known(value) => Some(value),
            Self::Unavailable { .. } => None,
        }
    }
}

/// A flat measured-value wire form used by provider observation reports.
///
/// This remains distinct from [`Measured`] because unavailable values in the
/// two established wire contracts place `reason` at different nesting levels.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum FlatMeasured<T, R> {
    Known { value: T },
    Unavailable { reason: R },
}

impl<T, R> FlatMeasured<T, R> {
    pub const fn known(value: T) -> Self {
        Self::Known { value }
    }

    pub const fn as_known(&self) -> Option<&T> {
        match self {
            Self::Known { value } => Some(value),
            Self::Unavailable { .. } => None,
        }
    }
}

/// Exact or unknown loss in a count domain named by the surrounding field.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub enum LossExtent {
    Known(u64),
    Unknown,
}

/// Where an acquisition limit can actually be enforced.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub enum LimitEnforcement {
    StreamingAdmission,
    RetentionAfterProviderMaterialization,
}

/// Whether a budget applies independently or across a capture scope.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub enum BudgetScope {
    PerPayload,
    CaptureAggregate,
}

/// Microsecond duration measured by a capture's monotonic clock.
#[derive(
    Clone, Copy, Debug, Default, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize,
)]
#[serde(transparent)]
pub struct CaptureDuration(u64);

impl CaptureDuration {
    pub const fn from_microseconds(microseconds: u64) -> Self {
        Self(microseconds)
    }

    pub const fn as_microseconds(self) -> u64 {
        self.0
    }
}

/// Offset from the monotonic start of one capture attempt.
#[derive(
    Clone, Copy, Debug, Default, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize,
)]
#[serde(transparent)]
pub struct CaptureOffset(u64);

impl CaptureOffset {
    pub const fn from_microseconds(microseconds: u64) -> Self {
        Self(microseconds)
    }

    pub const fn as_microseconds(self) -> u64 {
        self.0
    }

    /// Returns the elapsed duration only when `earlier` does not follow this offset.
    pub const fn duration_since(self, earlier: Self) -> Option<CaptureDuration> {
        match self.0.checked_sub(earlier.0) {
            Some(duration) => Some(CaptureDuration::from_microseconds(duration)),
            None => None,
        }
    }
}

/// Error returned when a mandatory capture deadline is zero.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
#[error("maximum elapsed duration must be greater than zero")]
pub struct CaptureDeadlineError;

/// Mandatory positive monotonic deadline for requesting capture termination.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct CaptureDeadline(NonZeroU64);

impl CaptureDeadline {
    pub const fn as_microseconds(self) -> u64 {
        self.0.get()
    }

    pub const fn duration(self) -> CaptureDuration {
        CaptureDuration::from_microseconds(self.as_microseconds())
    }
}

impl TryFrom<u64> for CaptureDeadline {
    type Error = CaptureDeadlineError;

    fn try_from(value: u64) -> Result<Self, Self::Error> {
        NonZeroU64::new(value).map(Self).ok_or(CaptureDeadlineError)
    }
}

impl From<CaptureDeadline> for u64 {
    fn from(value: CaptureDeadline) -> Self {
        value.as_microseconds()
    }
}

impl<'de> Deserialize<'de> for CaptureDeadline {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        u64::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}

#[cfg(test)]
#[allow(clippy::expect_used, clippy::unwrap_used)]
mod tests {
    use super::{ByteCount, ByteLimit, CaptureDeadline, CaptureOffset, EventCount, Measured};

    #[test]
    fn wire_forms_match_the_pre_move_primitives() {
        assert_eq!(serde_json::to_string(&ByteCount::new(7)).unwrap(), "7");
        assert_eq!(serde_json::to_string(&EventCount::new(8)).unwrap(), "8");
        assert_eq!(
            serde_json::to_string(&CaptureOffset::from_microseconds(9)).unwrap(),
            "9"
        );
        assert_eq!(
            serde_json::to_string(&Measured::<ByteCount, &str>::Known(ByteCount::new(5))).unwrap(),
            r#"{"status":"known","value":5}"#
        );
    }

    #[test]
    fn positive_bounds_reject_zero_on_construction_and_deserialization() {
        assert!(ByteLimit::try_from(0_u64).is_err());
        assert!(CaptureDeadline::try_from(0_u64).is_err());
        assert!(serde_json::from_str::<ByteLimit>("0").is_err());
        assert!(serde_json::from_str::<CaptureDeadline>("0").is_err());
    }
}
