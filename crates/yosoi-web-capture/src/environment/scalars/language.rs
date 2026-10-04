use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use thiserror::Error;

const MAX_PREFERRED_LANGUAGES: usize = 32;
const MAX_LOCALE_BYTES: usize = 128;

/// Error returned when an ordered language list exceeds its stable bound.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
#[error("preferred languages cannot contain more than {MAX_PREFERRED_LANGUAGES} entries")]
pub struct PreferredLanguagesError;

/// Ordered effective language preferences for native HTTP representation.
///
/// This is a semantic projection, not a raw `Accept-Language` header. An empty
/// list means the client expressed no language preference.
#[derive(Clone, Debug, Eq, Hash, PartialEq, Serialize)]
#[serde(transparent)]
pub struct PreferredLanguages(Vec<Locale>);

impl PreferredLanguages {
    /// Creates a bounded ordered list of locale preferences.
    pub fn new(locales: Vec<Locale>) -> Result<Self, PreferredLanguagesError> {
        if locales.len() > MAX_PREFERRED_LANGUAGES {
            return Err(PreferredLanguagesError);
        }
        Ok(Self(locales))
    }

    /// Returns preferences in effective priority order.
    pub fn as_slice(&self) -> &[Locale] {
        &self.0
    }
}

impl<'de> Deserialize<'de> for PreferredLanguages {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let locales = Vec::<Locale>::deserialize(deserializer)?;
        Self::new(locales).map_err(D::Error::custom)
    }
}

/// Error returned when a locale identifier is not safe and bounded.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum LocaleError {
    /// The locale was empty.
    #[error("locale cannot be empty")]
    Empty,
    /// The locale exceeded its wire-size bound.
    #[error("locale cannot exceed {MAX_LOCALE_BYTES} bytes")]
    TooLong,
    /// The locale used characters outside a conservative BCP-47 alphabet.
    #[error("locale allows only ASCII letters, digits, and '-'")]
    InvalidCharacter,
}

/// Bounded locale identifier, such as `en-US`.
///
/// This type validates a conservative wire alphabet, not registry membership.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct Locale(String);

impl Locale {
    /// Validates and creates a locale identifier.
    pub fn new(value: impl Into<String>) -> Result<Self, LocaleError> {
        let value = value.into();
        validate_locale(&value)?;
        Ok(Self(value))
    }

    /// Returns the exact reported locale identifier.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl<'de> Deserialize<'de> for Locale {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        Self::new(value).map_err(D::Error::custom)
    }
}

fn validate_locale(value: &str) -> Result<(), LocaleError> {
    if value.is_empty() {
        return Err(LocaleError::Empty);
    }
    if value.len() > MAX_LOCALE_BYTES {
        return Err(LocaleError::TooLong);
    }
    if !value.split('-').all(|segment| {
        !segment.is_empty() && segment.bytes().all(|byte| byte.is_ascii_alphanumeric())
    }) {
        return Err(LocaleError::InvalidCharacter);
    }
    Ok(())
}
