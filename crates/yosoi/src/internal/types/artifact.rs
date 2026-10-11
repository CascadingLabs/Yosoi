//! Artifact records and explicit byte availability.

use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use thiserror::Error;

use crate::internal::types::{ArtifactId, ArtifactRef, Provenance, ReasonCode, Sha256Digest};

/// Availability of an artifact's exact serialized bytes.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ArtifactAvailability {
    /// Complete bytes were retained.
    Retained,
    /// A bounded prefix or partial representation was retained.
    ///
    /// Its digest covers exactly the retained bytes, not the unavailable
    /// remainder or the hypothetical complete artifact.
    Truncated,
    /// Bytes were observed and intentionally not retained.
    Discarded,
    /// Bytes could not be obtained.
    Unavailable,
}

/// Error returned when artifact availability disagrees with digest or reason.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum ArtifactRecordError {
    /// Retained bytes did not include their exact content digest.
    #[error("retained or truncated artifact bytes require a content digest")]
    MissingDigest,

    /// A digest was supplied even though no bytes were retained.
    #[error("discarded or unavailable artifact bytes cannot carry a content digest")]
    UnexpectedDigest,

    /// Incomplete or absent bytes lacked an explicit explanation.
    #[error("truncated, discarded, or unavailable artifacts require a reason code")]
    MissingReason,

    /// Complete retained bytes carried an inapplicable reason.
    #[error("complete retained artifacts cannot carry an availability reason")]
    UnexpectedReason,
}

/// One activity-local artifact and the immediate provenance of its value.
///
/// The artifact's stable location is mechanically derived from its provenance
/// activity and local ID. Provider-specific metadata remains in the bytes
/// described by `schema`; this envelope stays independent of browser, HTTP,
/// desktop, parser, and device payloads.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct ArtifactRecord {
    id: ArtifactId,
    content_digest: Option<Sha256Digest>,
    availability: ArtifactAvailability,
    availability_reason: Option<ReasonCode>,
    provenance: Provenance,
}

impl ArtifactRecord {
    /// Creates a validated artifact record.
    pub fn new(
        id: ArtifactId,
        content_digest: Option<Sha256Digest>,
        availability: ArtifactAvailability,
        availability_reason: Option<ReasonCode>,
        provenance: Provenance,
    ) -> Result<Self, ArtifactRecordError> {
        validate_artifact_availability(availability, content_digest, availability_reason.as_ref())?;
        Ok(Self {
            id,
            content_digest,
            availability,
            availability_reason,
            provenance,
        })
    }

    /// Returns the artifact's local ID.
    pub const fn id(&self) -> ArtifactId {
        self.id
    }

    /// Returns the artifact's stable location.
    pub const fn reference(&self) -> ArtifactRef {
        ArtifactRef::new(self.provenance.activity_id(), self.id)
    }

    /// Returns the digest of the exact retained byte sequence, when bytes exist.
    ///
    /// For a truncated artifact this identifies only the retained prefix or
    /// partial representation.
    pub const fn content_digest(&self) -> Option<Sha256Digest> {
        self.content_digest
    }

    /// Returns the state of the artifact's serialized bytes.
    pub const fn availability(&self) -> ArtifactAvailability {
        self.availability
    }

    /// Returns the explicit reason for incomplete or absent bytes.
    pub const fn availability_reason(&self) -> Option<&ReasonCode> {
        self.availability_reason.as_ref()
    }

    /// Returns the artifact's immediate provenance.
    pub const fn provenance(&self) -> &Provenance {
        &self.provenance
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ArtifactRecordWire {
    id: ArtifactId,
    content_digest: Option<Sha256Digest>,
    availability: ArtifactAvailability,
    availability_reason: Option<ReasonCode>,
    provenance: Provenance,
}

impl TryFrom<ArtifactRecordWire> for ArtifactRecord {
    type Error = ArtifactRecordError;

    fn try_from(value: ArtifactRecordWire) -> Result<Self, Self::Error> {
        Self::new(
            value.id,
            value.content_digest,
            value.availability,
            value.availability_reason,
            value.provenance,
        )
    }
}

impl<'de> Deserialize<'de> for ArtifactRecord {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        ArtifactRecordWire::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}

const fn validate_artifact_availability(
    availability: ArtifactAvailability,
    digest: Option<Sha256Digest>,
    reason: Option<&ReasonCode>,
) -> Result<(), ArtifactRecordError> {
    match (availability, digest, reason) {
        (ArtifactAvailability::Retained | ArtifactAvailability::Truncated, None, _) => {
            Err(ArtifactRecordError::MissingDigest)
        }
        (ArtifactAvailability::Discarded | ArtifactAvailability::Unavailable, Some(_), _) => {
            Err(ArtifactRecordError::UnexpectedDigest)
        }
        (
            ArtifactAvailability::Truncated
            | ArtifactAvailability::Discarded
            | ArtifactAvailability::Unavailable,
            _,
            None,
        ) => Err(ArtifactRecordError::MissingReason),
        (ArtifactAvailability::Retained, Some(_), Some(_)) => {
            Err(ArtifactRecordError::UnexpectedReason)
        }
        _ => Ok(()),
    }
}
