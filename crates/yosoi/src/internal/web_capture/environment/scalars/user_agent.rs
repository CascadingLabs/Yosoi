use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use thiserror::Error;

const MAX_USER_AGENT_BYTES: usize = 1_024;

/// Error returned when a user agent is unsafe or unbounded metadata.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum UserAgentError {
    /// The user agent exceeded its wire-size bound.
    #[error("user agent cannot exceed {MAX_USER_AGENT_BYTES} bytes")]
    TooLong,
    /// The user agent contained control characters.
    #[error("user agent cannot contain control characters")]
    ControlCharacter,
}

/// Exact bounded user agent reported for a capture.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct UserAgent(String);

impl UserAgent {
    /// Validates and creates a user agent.
    pub fn new(value: impl Into<String>) -> Result<Self, UserAgentError> {
        let value = value.into();
        if value.len() > MAX_USER_AGENT_BYTES {
            return Err(UserAgentError::TooLong);
        }
        if value.chars().any(char::is_control) {
            return Err(UserAgentError::ControlCharacter);
        }
        Ok(Self(value))
    }

    /// Returns the exact reported user agent.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl<'de> Deserialize<'de> for UserAgent {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        Self::new(value).map_err(D::Error::custom)
    }
}
