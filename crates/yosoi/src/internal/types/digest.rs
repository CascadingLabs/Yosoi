//! Exact SHA-256 content identity.

use std::{fmt, str::FromStr};

use serde::{Deserialize, Deserializer, Serialize, Serializer, de::Error as _};
use sha2::{Digest as _, Sha256};
use thiserror::Error;

const SHA256_HEX_LENGTH: usize = 64;

/// Error returned when a SHA-256 digest is not canonical hexadecimal.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum Sha256DigestParseError {
    /// The hexadecimal input did not contain exactly 64 bytes.
    #[error("SHA-256 digest must contain exactly 64 lowercase hexadecimal characters")]
    InvalidLength,

    /// The input contained uppercase or non-hexadecimal characters.
    #[error("SHA-256 digest must use lowercase hexadecimal characters")]
    InvalidEncoding,
}

/// Exact SHA-256 identity of one byte sequence.
///
/// Display, parsing, and JSON use exactly 64 lowercase hexadecimal characters.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct Sha256Digest([u8; 32]);

impl Sha256Digest {
    /// Computes the digest of exact input bytes.
    pub fn digest(content: impl AsRef<[u8]>) -> Self {
        Self(Sha256::digest(content.as_ref()).into())
    }

    /// Creates a digest from its exact 32-byte binary representation.
    pub const fn from_bytes(bytes: [u8; 32]) -> Self {
        Self(bytes)
    }

    /// Returns the exact 32-byte binary representation.
    pub const fn as_bytes(&self) -> &[u8; 32] {
        &self.0
    }
}

impl fmt::Display for Sha256Digest {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        for byte in self.0 {
            write!(formatter, "{byte:02x}")?;
        }
        Ok(())
    }
}

impl FromStr for Sha256Digest {
    type Err = Sha256DigestParseError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        if value.len() != SHA256_HEX_LENGTH {
            return Err(Sha256DigestParseError::InvalidLength);
        }

        let mut bytes = [0_u8; 32];
        let (pairs, remainder) = value.as_bytes().as_chunks::<2>();
        if !remainder.is_empty() {
            return Err(Sha256DigestParseError::InvalidLength);
        }
        for (destination, [high, low]) in bytes.iter_mut().zip(pairs) {
            let high = decode_lower_hex(*high)?;
            let low = decode_lower_hex(*low)?;
            *destination = high
                .checked_shl(4)
                .and_then(|value| value.checked_add(low))
                .ok_or(Sha256DigestParseError::InvalidEncoding)?;
        }
        Ok(Self(bytes))
    }
}

impl Serialize for Sha256Digest {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.collect_str(self)
    }
}

impl<'de> Deserialize<'de> for Sha256Digest {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        deserialize_from_string(deserializer)
    }
}

fn decode_lower_hex(character: u8) -> Result<u8, Sha256DigestParseError> {
    match character {
        b'0'..=b'9' => character
            .checked_sub(b'0')
            .ok_or(Sha256DigestParseError::InvalidEncoding),
        b'a'..=b'f' => character
            .checked_sub(b'a')
            .and_then(|value| value.checked_add(10))
            .ok_or(Sha256DigestParseError::InvalidEncoding),
        _ => Err(Sha256DigestParseError::InvalidEncoding),
    }
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
