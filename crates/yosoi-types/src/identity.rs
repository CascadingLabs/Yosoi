//! Random occurrence identities and activity-local artifact locations.

use std::{fmt, num::NonZeroU32, str::FromStr};

use serde::{Deserialize, Deserializer, Serialize, Serializer, de::Error as _};
use thiserror::Error;
use uuid::Uuid;

/// Error returned when a random occurrence identity is not in its canonical
/// lowercase, hyphenated UUID representation.
#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum OccurrenceIdParseError {
    /// The input was not a UUID.
    #[error("invalid UUID occurrence identity")]
    InvalidUuid,

    /// The UUID used a valid but non-canonical textual representation.
    #[error("occurrence identity must be a lowercase hyphenated UUID")]
    NonCanonical,

    /// The UUID was canonical but was not a random RFC 4122 UUID v4.
    #[error("occurrence identity must be an RFC 4122 UUID v4")]
    NotRandomV4,
}

/// Random identity for one actual activity occurrence.
///
/// The JSON and display representation is a lowercase hyphenated UUID.
///
/// ```compile_fail
/// use yosoi_types::{ActivityId, CaptureId};
///
/// fn requires_capture(_: CaptureId) {}
/// requires_capture(ActivityId::random());
/// ```
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct ActivityId([u8; 16]);

impl ActivityId {
    /// Generates a random UUID v4 activity identity.
    pub fn random() -> Self {
        Self(Uuid::new_v4().into_bytes())
    }

    /// Returns the UUID bytes in network byte order.
    pub const fn as_bytes(&self) -> &[u8; 16] {
        &self.0
    }
}

impl fmt::Display for ActivityId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        Uuid::from_bytes(self.0).hyphenated().fmt(formatter)
    }
}

impl FromStr for ActivityId {
    type Err = OccurrenceIdParseError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        parse_canonical_uuid(value).map(Self)
    }
}

impl Serialize for ActivityId {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.collect_str(self)
    }
}

impl<'de> Deserialize<'de> for ActivityId {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        deserialize_from_string(deserializer)
    }
}

/// Random activity identity whose activity is known to be a capture.
///
/// This newtype preserves capture-specific APIs without making capture the root
/// of the general provenance model.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct CaptureId(ActivityId);

impl CaptureId {
    /// Generates a random UUID v4 capture identity.
    pub fn random() -> Self {
        Self(ActivityId::random())
    }

    /// Returns this capture's general activity identity.
    pub const fn activity_id(self) -> ActivityId {
        self.0
    }

    /// Returns the UUID bytes in network byte order.
    pub const fn as_bytes(&self) -> &[u8; 16] {
        self.0.as_bytes()
    }
}

impl fmt::Display for CaptureId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

impl FromStr for CaptureId {
    type Err = OccurrenceIdParseError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        value.parse::<ActivityId>().map(Self)
    }
}

impl From<CaptureId> for ActivityId {
    fn from(value: CaptureId) -> Self {
        value.activity_id()
    }
}

impl Serialize for CaptureId {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.collect_str(self)
    }
}

impl<'de> Deserialize<'de> for CaptureId {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        deserialize_from_string(deserializer)
    }
}

/// Error returned when an artifact-local ordinal is zero.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
#[error("artifact identity must be a non-zero activity-local ordinal")]
pub struct ArtifactIdError;

/// Non-zero output position local to one producing activity.
///
/// Every produced artifact, including one derived from earlier artifacts,
/// receives a fresh local ordinal. Derivation is recorded by provenance and
/// does not deterministically derive this identity from its inputs. Exact byte
/// identity is represented separately by a content digest.
///
/// The JSON and display representation is an unsigned integer. The same value
/// can occur in unrelated activities; use [`ArtifactRef`] outside the producer.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct ArtifactId(NonZeroU32);

impl ArtifactId {
    /// Creates an artifact ID from an already validated non-zero ordinal.
    pub const fn new(value: NonZeroU32) -> Self {
        Self(value)
    }

    /// Returns the activity-local ordinal.
    pub const fn get(self) -> u32 {
        self.0.get()
    }
}

impl fmt::Display for ArtifactId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

impl TryFrom<u32> for ArtifactId {
    type Error = ArtifactIdError;

    fn try_from(value: u32) -> Result<Self, Self::Error> {
        NonZeroU32::new(value).map(Self).ok_or(ArtifactIdError)
    }
}

impl From<ArtifactId> for u32 {
    fn from(value: ArtifactId) -> Self {
        value.get()
    }
}

/// Stable location of an artifact produced by one activity.
///
/// This is a location reference, not content identity. Two references may point
/// to byte-identical artifacts, and one logical artifact may be copied to a new
/// location without retaining this reference.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ArtifactRef {
    activity_id: ActivityId,
    artifact_id: ArtifactId,
}

impl ArtifactRef {
    /// Creates an artifact location from its producing activity and local ID.
    pub const fn new(activity_id: ActivityId, artifact_id: ArtifactId) -> Self {
        Self {
            activity_id,
            artifact_id,
        }
    }

    /// Returns the activity that produced the artifact.
    pub const fn activity_id(self) -> ActivityId {
        self.activity_id
    }

    /// Returns the artifact's activity-local ID.
    pub const fn artifact_id(self) -> ArtifactId {
        self.artifact_id
    }
}

/// Capture-local artifact location that retains capture-specific type safety.
///
/// It can be widened to a general [`ArtifactRef`] because every capture is an
/// activity. A general artifact reference cannot be narrowed without proving
/// that its producing activity was a capture.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CaptureArtifactRef {
    capture_id: CaptureId,
    artifact_id: ArtifactId,
}

impl CaptureArtifactRef {
    /// Creates a capture-local artifact location.
    pub const fn new(capture_id: CaptureId, artifact_id: ArtifactId) -> Self {
        Self {
            capture_id,
            artifact_id,
        }
    }

    /// Returns the capture containing this artifact.
    pub const fn capture_id(self) -> CaptureId {
        self.capture_id
    }

    /// Returns the artifact's capture-local ID.
    pub const fn artifact_id(self) -> ArtifactId {
        self.artifact_id
    }

    /// Widens this capture-local location to a general activity artifact.
    pub const fn artifact_ref(self) -> ArtifactRef {
        ArtifactRef::new(self.capture_id.activity_id(), self.artifact_id)
    }
}

impl From<CaptureArtifactRef> for ArtifactRef {
    fn from(value: CaptureArtifactRef) -> Self {
        value.artifact_ref()
    }
}

fn parse_canonical_uuid(value: &str) -> Result<[u8; 16], OccurrenceIdParseError> {
    let uuid = Uuid::parse_str(value).map_err(|_| OccurrenceIdParseError::InvalidUuid)?;
    if uuid.hyphenated().to_string() != value {
        return Err(OccurrenceIdParseError::NonCanonical);
    }
    if uuid.get_version_num() != 4 || uuid.get_variant() != uuid::Variant::RFC4122 {
        return Err(OccurrenceIdParseError::NotRandomV4);
    }
    Ok(uuid.into_bytes())
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
