use std::{fmt, str::FromStr};

use serde::{Deserialize, Deserializer, Serialize, Serializer, de::Error as _};
use thiserror::Error;

const MAX_DEVICE_SCALE_FACTOR_BYTES: usize = 32;

/// Error returned when a device scale factor is not a canonical positive decimal.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum DeviceScaleFactorError {
    /// The representation was empty.
    #[error("device scale factor cannot be empty")]
    Empty,
    /// The representation exceeded its wire-size bound.
    #[error("device scale factor cannot exceed {MAX_DEVICE_SCALE_FACTOR_BYTES} bytes")]
    TooLong,
    /// The representation was not an unsigned decimal without exponent notation.
    #[error("device scale factor must be an unsigned decimal without exponent notation")]
    InvalidCharacter,
    /// The scale factor was zero.
    #[error("device scale factor must be greater than zero")]
    Zero,
    /// The decimal used redundant leading or trailing zeroes.
    #[error("device scale factor must use canonical decimal notation")]
    NonCanonical,
}

/// Exact canonical positive decimal device scale factor.
///
/// A decimal string avoids unstable floating-point equality and serialization.
/// Examples include `1`, `1.25`, and `2`.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct DeviceScaleFactor(String);

impl DeviceScaleFactor {
    /// Validates and creates a device scale factor.
    pub fn new(value: impl Into<String>) -> Result<Self, DeviceScaleFactorError> {
        let value = value.into();
        validate_device_scale_factor(&value)?;
        Ok(Self(value))
    }

    /// Returns the canonical decimal representation.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for DeviceScaleFactor {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

impl FromStr for DeviceScaleFactor {
    type Err = DeviceScaleFactorError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Self::new(value)
    }
}

impl Serialize for DeviceScaleFactor {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.collect_str(self)
    }
}

impl<'de> Deserialize<'de> for DeviceScaleFactor {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        deserialize_from_string(deserializer)
    }
}

fn validate_device_scale_factor(value: &str) -> Result<(), DeviceScaleFactorError> {
    if value.is_empty() {
        return Err(DeviceScaleFactorError::Empty);
    }
    if value.len() > MAX_DEVICE_SCALE_FACTOR_BYTES {
        return Err(DeviceScaleFactorError::TooLong);
    }
    if !value
        .bytes()
        .all(|character| character.is_ascii_digit() || character == b'.')
    {
        return Err(DeviceScaleFactorError::InvalidCharacter);
    }

    let mut parts = value.split('.');
    let integer = parts
        .next()
        .ok_or(DeviceScaleFactorError::InvalidCharacter)?;
    let fraction = parts.next();
    if parts.next().is_some() || integer.is_empty() || fraction.is_some_and(str::is_empty) {
        return Err(DeviceScaleFactorError::InvalidCharacter);
    }
    if integer.len() > 1 && integer.starts_with('0') {
        return Err(DeviceScaleFactorError::NonCanonical);
    }
    if fraction.is_some_and(|digits| digits.ends_with('0')) {
        return Err(DeviceScaleFactorError::NonCanonical);
    }
    if integer == "0" && fraction.is_none_or(|digits| digits.bytes().all(|digit| digit == b'0')) {
        return Err(DeviceScaleFactorError::Zero);
    }
    Ok(())
}

fn deserialize_from_string<'de, D, T>(deserializer: D) -> Result<T, D::Error>
where
    D: Deserializer<'de>,
    T: FromStr,
    T::Err: fmt::Display,
{
    String::deserialize(deserializer)?
        .parse()
        .map_err(D::Error::custom)
}
