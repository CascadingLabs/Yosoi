use std::{fmt, str::FromStr};

use serde::{Deserialize, Deserializer, Serialize, Serializer, de::Error as _};
use thiserror::Error;

const MAX_MEDIA_TYPE_BYTES: usize = 127;

/// Error returned when an artifact media type is not a canonical essence.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum MediaTypeError {
    /// The media type was empty.
    #[error("artifact media type cannot be empty")]
    Empty,
    /// The media type exceeded its stable wire bound.
    #[error("artifact media type cannot exceed {MAX_MEDIA_TYPE_BYTES} bytes")]
    TooLong,
    /// The value was not one non-empty type and subtype separated by `/`.
    #[error("artifact media type must contain one non-empty type and subtype")]
    InvalidFormat,
    /// The value was not a lowercase canonical media-type essence.
    #[error("artifact media type must be a lowercase ASCII essence without parameters")]
    InvalidCharacter,
}

/// Canonical media-type essence used for retained artifact bytes.
///
/// Values contain only the lowercase `type/subtype` essence, such as
/// `text/html` or `application/json`. Parameters such as a character set belong
/// to the payload schema rather than this identity.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct MediaType(String);

impl MediaType {
    /// Validates and creates a canonical media type.
    pub fn new(value: impl Into<String>) -> Result<Self, MediaTypeError> {
        let value = value.into();
        validate_media_type(&value)?;
        Ok(Self(value))
    }

    /// Returns the canonical `type/subtype` value.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for MediaType {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

impl FromStr for MediaType {
    type Err = MediaTypeError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Self::new(value)
    }
}

impl Serialize for MediaType {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.collect_str(self)
    }
}

impl<'de> Deserialize<'de> for MediaType {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        String::deserialize(deserializer)?
            .parse()
            .map_err(D::Error::custom)
    }
}

fn validate_media_type(value: &str) -> Result<(), MediaTypeError> {
    if value.is_empty() {
        return Err(MediaTypeError::Empty);
    }
    if value.len() > MAX_MEDIA_TYPE_BYTES {
        return Err(MediaTypeError::TooLong);
    }

    let Some((top_level, subtype)) = value.split_once('/') else {
        return Err(MediaTypeError::InvalidFormat);
    };
    if top_level.is_empty() || subtype.is_empty() || subtype.contains('/') {
        return Err(MediaTypeError::InvalidFormat);
    }
    if !top_level.bytes().all(is_media_type_character)
        || !subtype.bytes().all(is_media_type_character)
    {
        return Err(MediaTypeError::InvalidCharacter);
    }
    Ok(())
}

const fn is_media_type_character(character: u8) -> bool {
    character.is_ascii_lowercase()
        || character.is_ascii_digit()
        || matches!(
            character,
            b'!' | b'#'
                | b'$'
                | b'&'
                | b'\''
                | b'+'
                | b'-'
                | b'.'
                | b'^'
                | b'_'
                | b'`'
                | b'|'
                | b'~'
        )
}
