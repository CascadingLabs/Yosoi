use serde::{Deserialize, Deserializer, Serialize, Serializer, de::Error as _};
use std::{fmt, str::FromStr};
use thiserror::Error;
const MAX_PROFILE_NAME_BYTES: usize = 128;

/// Error returned for an unsafe or unbounded network-profile name.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum HttpBrowserImpersonationProfileError {
    /// Profile names cannot be empty.
    #[error("HTTP browser impersonation profile cannot be empty")]
    Empty,
    /// Profile names have a stable wire-size bound.
    #[error("HTTP browser impersonation profile cannot exceed {MAX_PROFILE_NAME_BYTES} bytes")]
    TooLong,
    /// Profile names use a deliberately path- and whitespace-free alphabet.
    #[error(
        "HTTP browser impersonation profile allows only ASCII letters, digits, '.', '-', and '_'"
    )]
    InvalidCharacter,
}

/// Provider-defined HTTP browser-impersonation profile, such as `safari26`.
///
/// The profile is an opaque transport configuration token, not a persistent
/// browser profile or context. CAS-293 producer identity and version state
/// which component interpreted it.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct HttpBrowserImpersonationProfile(String);

impl HttpBrowserImpersonationProfile {
    /// Validates and creates an HTTP browser-impersonation profile token.
    pub fn new(value: impl Into<String>) -> Result<Self, HttpBrowserImpersonationProfileError> {
        let value = value.into();
        validate_profile_name(&value)?;
        Ok(Self(value))
    }

    /// Returns the opaque provider-defined token.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for HttpBrowserImpersonationProfile {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

impl FromStr for HttpBrowserImpersonationProfile {
    type Err = HttpBrowserImpersonationProfileError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Self::new(value)
    }
}

impl Serialize for HttpBrowserImpersonationProfile {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.collect_str(self)
    }
}

impl<'de> Deserialize<'de> for HttpBrowserImpersonationProfile {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        String::deserialize(deserializer)?
            .parse()
            .map_err(D::Error::custom)
    }
}

fn validate_profile_name(value: &str) -> Result<(), HttpBrowserImpersonationProfileError> {
    if value.is_empty() {
        return Err(HttpBrowserImpersonationProfileError::Empty);
    }
    if value.len() > MAX_PROFILE_NAME_BYTES {
        return Err(HttpBrowserImpersonationProfileError::TooLong);
    }
    if !value.bytes().all(|character| {
        character.is_ascii_alphanumeric() || matches!(character, b'.' | b'-' | b'_')
    }) {
        return Err(HttpBrowserImpersonationProfileError::InvalidCharacter);
    }
    Ok(())
}
