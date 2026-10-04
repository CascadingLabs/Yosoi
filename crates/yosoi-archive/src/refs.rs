use std::fmt::{self, Display, Formatter};
use std::str::FromStr;

use serde::{Deserialize, Deserializer, Serialize, Serializer, de::Error as _};
use thiserror::Error;
use uuid::{Uuid, Variant, Version};
use yosoi_types::{CaptureId, OccurrenceIdParseError};

use crate::ARCHIVE_FORMAT_VERSION;

const CAPTURE_PREFIX: &str = "capture";

/// Invalid textual or logical Archive reference.
#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum ArchiveRefError {
    #[error("an Archive reference must have the form <kind>:v<format>:<key>")]
    InvalidSyntax,
    #[error("an Archive reference format version must be a positive integer")]
    InvalidFormat,
    #[error("expected an Archive {expected} reference, found {found}")]
    WrongKind {
        expected: &'static str,
        found: String,
    },
    #[error("an Archive record key must be 2-128 lowercase path-safe characters without '..'")]
    InvalidKey,
    #[error("an Archive {kind} reference key must be a canonical lowercase UUID v4")]
    InvalidUuidKey { kind: &'static str },
    #[error("a Capture Archive reference key must be a canonical lowercase UUID v4")]
    InvalidCaptureKey(#[source] OccurrenceIdParseError),
}

#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct RecordKey(String);

impl RecordKey {
    pub fn parse(value: impl Into<String>) -> Result<Self, ArchiveRefError> {
        let value = value.into();
        let valid_length = (2..=128).contains(&value.len());
        let valid_bytes = value.bytes().all(|byte| {
            byte.is_ascii_lowercase() || byte.is_ascii_digit() || matches!(byte, b'-' | b'_' | b'.')
        });
        if !valid_length || !valid_bytes || value.contains("..") {
            return Err(ArchiveRefError::InvalidKey);
        }
        Ok(Self(value))
    }

    pub fn new_uuid() -> Self {
        Self(Uuid::new_v4().to_string())
    }

    pub fn from_capture_id(capture_id: CaptureId) -> Self {
        Self(capture_id.to_string())
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }

    pub fn shard(&self) -> String {
        self.0.chars().take(2).collect()
    }
}

impl Display for RecordKey {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

impl Serialize for RecordKey {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.collect_str(self)
    }
}

impl<'de> Deserialize<'de> for RecordKey {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        Self::parse(String::deserialize(deserializer)?).map_err(D::Error::custom)
    }
}

/// Reference to one immutable archived capture occurrence.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct CaptureArchiveRef {
    format_version: u32,
    capture_id: CaptureId,
}

impl CaptureArchiveRef {
    pub(crate) const fn new_current(capture_id: CaptureId) -> Self {
        Self {
            format_version: ARCHIVE_FORMAT_VERSION,
            capture_id,
        }
    }

    /// Returns the physical Archive format named by this reference.
    pub const fn format_version(&self) -> u32 {
        self.format_version
    }

    /// Returns the existing occurrence identity that keys this capture.
    pub const fn capture_id(&self) -> CaptureId {
        self.capture_id
    }

    pub(crate) fn key(&self) -> RecordKey {
        RecordKey::from_capture_id(self.capture_id)
    }
}

impl Display for CaptureArchiveRef {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "{CAPTURE_PREFIX}:v{}:{}",
            self.format_version, self.capture_id
        )
    }
}

impl FromStr for CaptureArchiveRef {
    type Err = ArchiveRefError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        let (kind, format, key) = parse_reference_parts(value)?;
        if kind != CAPTURE_PREFIX {
            return Err(ArchiveRefError::WrongKind {
                expected: CAPTURE_PREFIX,
                found: kind.to_owned(),
            });
        }
        Ok(Self {
            format_version: parse_format_version(format)?,
            capture_id: key.parse().map_err(ArchiveRefError::InvalidCaptureKey)?,
        })
    }
}

impl Serialize for CaptureArchiveRef {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.collect_str(self)
    }
}

impl<'de> Deserialize<'de> for CaptureArchiveRef {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        String::deserialize(deserializer)?
            .parse()
            .map_err(D::Error::custom)
    }
}

fn parse_reference_parts(value: &str) -> Result<(&str, &str, &str), ArchiveRefError> {
    let mut parts = value.split(':');
    let kind = parts.next().ok_or(ArchiveRefError::InvalidSyntax)?;
    let format = parts.next().ok_or(ArchiveRefError::InvalidSyntax)?;
    let key = parts.next().ok_or(ArchiveRefError::InvalidSyntax)?;
    if parts.next().is_some() {
        return Err(ArchiveRefError::InvalidSyntax);
    }
    Ok((kind, format, key))
}

fn parse_format_version(value: &str) -> Result<u32, ArchiveRefError> {
    let version = value
        .strip_prefix('v')
        .ok_or(ArchiveRefError::InvalidFormat)?
        .parse::<u32>()
        .map_err(|_| ArchiveRefError::InvalidFormat)?;
    if version == 0 || value != format!("v{version}") {
        return Err(ArchiveRefError::InvalidFormat);
    }
    Ok(version)
}

fn parse_uuid_reference(
    value: &str,
    expected_kind: &'static str,
) -> Result<(u32, RecordKey), ArchiveRefError> {
    let (kind, format, key) = parse_reference_parts(value)?;
    if kind != expected_kind {
        return Err(ArchiveRefError::WrongKind {
            expected: expected_kind,
            found: kind.to_owned(),
        });
    }
    let invalid_key = || ArchiveRefError::InvalidUuidKey {
        kind: expected_kind,
    };
    let uuid = Uuid::parse_str(key).map_err(|_| invalid_key())?;
    if uuid.get_version() != Some(Version::Random)
        || uuid.get_variant() != Variant::RFC4122
        || uuid.hyphenated().to_string() != key
    {
        return Err(invalid_key());
    }
    Ok((parse_format_version(format)?, RecordKey::parse(key)?))
}

macro_rules! uuid_archive_ref {
    ($name:ident, $prefix:literal, $description:literal) => {
        #[doc = $description]
        #[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
        pub struct $name {
            format_version: u32,
            key: RecordKey,
        }

        impl $name {
            pub(crate) fn new_current() -> Self {
                Self {
                    format_version: ARCHIVE_FORMAT_VERSION,
                    key: RecordKey::new_uuid(),
                }
            }

            /// Returns the physical Archive format named by this reference.
            pub const fn format_version(&self) -> u32 {
                self.format_version
            }

            /// Returns the opaque logical key, never a filesystem path.
            pub fn logical_key(&self) -> &str {
                self.key.as_str()
            }

            pub(crate) const fn key(&self) -> &RecordKey {
                &self.key
            }
        }

        impl Display for $name {
            fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
                write!(
                    formatter,
                    "{}:v{}:{}",
                    $prefix, self.format_version, self.key
                )
            }
        }

        impl FromStr for $name {
            type Err = ArchiveRefError;

            fn from_str(value: &str) -> Result<Self, Self::Err> {
                let (format_version, key) = parse_uuid_reference(value, $prefix)?;
                Ok(Self {
                    format_version,
                    key,
                })
            }
        }

        impl Serialize for $name {
            fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
            where
                S: Serializer,
            {
                serializer.collect_str(self)
            }
        }

        impl<'de> Deserialize<'de> for $name {
            fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
            where
                D: Deserializer<'de>,
            {
                String::deserialize(deserializer)?
                    .parse()
                    .map_err(D::Error::custom)
            }
        }
    };
}

uuid_archive_ref!(
    PolicyArchiveRef,
    "policy",
    "Reference to one immutable archived authored Policy snapshot."
);
uuid_archive_ref!(
    PlanArchiveRef,
    "plan",
    "Reference to one immutable archived compiled locator Plan snapshot."
);
uuid_archive_ref!(
    ContractSchemaArchiveRef,
    "contract-schema",
    "Reference to one immutable archived ContractSchema snapshot."
);
uuid_archive_ref!(
    RequestRunArchiveRef,
    "request-run",
    "Reference to one immutable archived request run."
);
uuid_archive_ref!(
    DocumentArchiveRef,
    "document",
    "Reference to one immutable archived validated Document."
);
uuid_archive_ref!(
    EvaluationRunArchiveRef,
    "evaluation-run",
    "Reference to one immutable offline EvaluationRunRecord."
);
uuid_archive_ref!(
    LocatorRunArchiveRef,
    "locator-run",
    "Reference to one immutable archived locator evaluation result."
);
uuid_archive_ref!(
    ContractRunArchiveRef,
    "contract-run",
    "Reference to one immutable archived Contract result."
);

#[cfg(test)]
#[path = "refs/tests.rs"]
mod tests;
