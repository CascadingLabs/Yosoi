use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use thiserror::Error;

const MAX_TIME_ZONE_BYTES: usize = 128;

/// Error returned when a time-zone identifier is not safe and bounded.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum TimeZoneError {
    /// The identifier was empty.
    #[error("time zone cannot be empty")]
    Empty,
    /// The identifier exceeded its wire-size bound.
    #[error("time zone cannot exceed {MAX_TIME_ZONE_BYTES} bytes")]
    TooLong,
    /// The identifier used characters outside the IANA-style wire alphabet.
    #[error("time zone contains an invalid character")]
    InvalidCharacter,
}

/// Bounded time-zone identifier, such as `UTC` or `America/New_York`.
///
/// This type validates an IANA-style wire alphabet, not database membership.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct TimeZone(String);

impl TimeZone {
    /// Validates and creates a time-zone identifier.
    pub fn new(value: impl Into<String>) -> Result<Self, TimeZoneError> {
        let value = value.into();
        validate_time_zone(&value)?;
        Ok(Self(value))
    }

    /// Returns the exact reported time-zone identifier.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl<'de> Deserialize<'de> for TimeZone {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        Self::new(value).map_err(D::Error::custom)
    }
}

fn validate_time_zone(value: &str) -> Result<(), TimeZoneError> {
    if value.is_empty() {
        return Err(TimeZoneError::Empty);
    }
    if value.len() > MAX_TIME_ZONE_BYTES {
        return Err(TimeZoneError::TooLong);
    }
    if !value.split('/').all(is_valid_time_zone_segment) {
        return Err(TimeZoneError::InvalidCharacter);
    }
    Ok(())
}

fn is_valid_time_zone_segment(segment: &str) -> bool {
    let starts_and_ends_with_alphanumeric = segment
        .bytes()
        .next()
        .is_some_and(|byte| byte.is_ascii_alphanumeric())
        && segment
            .bytes()
            .next_back()
            .is_some_and(|byte| byte.is_ascii_alphanumeric());
    starts_and_ends_with_alphanumeric
        && segment.bytes().all(|character| {
            character.is_ascii_alphanumeric() || matches!(character, b'_' | b'-' | b'+')
        })
}
