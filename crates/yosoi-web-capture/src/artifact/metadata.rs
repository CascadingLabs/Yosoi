use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use thiserror::Error;
use yosoi_types::{ArtifactAvailability, ArtifactRecord, ArtifactRef, Provenance, Sha256Digest};

use crate::{BrowserArtifactContext, ByteCount, MeasuredCount};

use super::MediaType;

/// Sensitivity classification applied before artifact retention or disclosure.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ArtifactSensitivity {
    /// The producer did not classify the payload.
    Unassessed,
    /// The producer determined that ordinary non-sensitive handling is allowed.
    NonSensitive,
    /// The payload requires sensitive-data handling.
    Sensitive,
}

/// Error returned when truncated byte accounting is contradictory.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
#[error("truncated retained bytes must be smaller than the known complete byte count")]
pub struct ArtifactByteExtentError;

/// Validated byte accounting for a truncated artifact.
#[derive(Clone, Debug, Eq, Hash, PartialEq, Serialize)]
pub struct TruncatedArtifactExtent {
    retained_bytes: ByteCount,
    complete_bytes: MeasuredCount<ByteCount>,
}

impl TruncatedArtifactExtent {
    /// Creates truncation accounting whose retained prefix is smaller than a known total.
    pub fn new(
        retained_bytes: ByteCount,
        complete_bytes: MeasuredCount<ByteCount>,
    ) -> Result<Self, ArtifactByteExtentError> {
        match &complete_bytes {
            MeasuredCount::Known(complete_bytes)
                if retained_bytes.get() >= complete_bytes.get() =>
            {
                return Err(ArtifactByteExtentError);
            }
            MeasuredCount::Known(_) | MeasuredCount::Unavailable { .. } => {}
        }
        Ok(Self {
            retained_bytes,
            complete_bytes,
        })
    }

    /// Returns the exact retained byte count covered by the artifact digest.
    pub const fn retained_bytes(&self) -> ByteCount {
        self.retained_bytes
    }

    /// Returns the complete serialized size when the producer could measure it.
    pub const fn complete_bytes(&self) -> &MeasuredCount<ByteCount> {
        &self.complete_bytes
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct TruncatedArtifactExtentWire {
    retained_bytes: ByteCount,
    complete_bytes: MeasuredCount<ByteCount>,
}

impl TryFrom<TruncatedArtifactExtentWire> for TruncatedArtifactExtent {
    type Error = ArtifactByteExtentError;

    fn try_from(value: TruncatedArtifactExtentWire) -> Result<Self, Self::Error> {
        Self::new(value.retained_bytes, value.complete_bytes)
    }
}

impl<'de> Deserialize<'de> for TruncatedArtifactExtent {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        TruncatedArtifactExtentWire::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}

/// Exact retained extent and, where applicable, observed complete extent.
#[derive(Clone, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum ArtifactByteExtent {
    /// All serialized artifact bytes were retained.
    Complete {
        /// Exact number of retained bytes, including known zero.
        retained_bytes: ByteCount,
    },
    /// Only part of the serialized representation was retained.
    Truncated(TruncatedArtifactExtent),
    /// Bytes were observed but deliberately not retained.
    Discarded {
        /// Observed serialized size, if the producer could measure it.
        observed_bytes: MeasuredCount<ByteCount>,
    },
    /// No serialized bytes were obtained.
    Unavailable,
}

impl ArtifactByteExtent {
    /// Creates validated truncated byte accounting.
    pub fn truncated(
        retained_bytes: ByteCount,
        complete_bytes: MeasuredCount<ByteCount>,
    ) -> Result<Self, ArtifactByteExtentError> {
        match TruncatedArtifactExtent::new(retained_bytes, complete_bytes) {
            Ok(extent) => Ok(Self::Truncated(extent)),
            Err(error) => Err(error),
        }
    }

    /// Returns the exact retained size when bytes were retained.
    pub const fn retained_bytes(&self) -> Option<ByteCount> {
        match self {
            Self::Complete { retained_bytes } => Some(*retained_bytes),
            Self::Truncated(extent) => Some(extent.retained_bytes()),
            Self::Discarded { .. } | Self::Unavailable => None,
        }
    }
}

/// Error returned when web metadata contradicts its generic artifact record.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
#[error("artifact byte extent must agree with artifact availability")]
pub struct WebArtifactMetadataError;

/// Common metadata for one typed web artifact.
///
/// The nested generic record remains the authority for identity, digest,
/// availability reason, schema, and immediate producer provenance. The web
/// envelope adds media type, explicit byte extent, and sensitivity without
/// embedding any family payload.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct WebArtifactMetadata {
    record: ArtifactRecord,
    media_type: MediaType,
    extent: ArtifactByteExtent,
    sensitivity: ArtifactSensitivity,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    browser_context: Option<BrowserArtifactContext>,
}

impl WebArtifactMetadata {
    /// Creates metadata after checking retained-byte accounting.
    pub fn new(
        record: ArtifactRecord,
        media_type: MediaType,
        extent: ArtifactByteExtent,
        sensitivity: ArtifactSensitivity,
    ) -> Result<Self, WebArtifactMetadataError> {
        Self::new_with_browser_context(record, media_type, extent, sensitivity, None)
    }

    /// Creates metadata with explicit browser-only payload interpretation context.
    pub fn new_with_browser_context(
        record: ArtifactRecord,
        media_type: MediaType,
        extent: ArtifactByteExtent,
        sensitivity: ArtifactSensitivity,
        browser_context: Option<BrowserArtifactContext>,
    ) -> Result<Self, WebArtifactMetadataError> {
        if !availability_matches_extent(record.availability(), &extent) {
            return Err(WebArtifactMetadataError);
        }
        Ok(Self {
            record,
            media_type,
            extent,
            sensitivity,
            browser_context,
        })
    }

    /// Returns the stable activity-local artifact reference.
    pub const fn reference(&self) -> ArtifactRef {
        self.record.reference()
    }

    /// Returns the generic artifact record.
    pub const fn record(&self) -> &ArtifactRecord {
        &self.record
    }

    /// Returns the media-type essence of the serialized bytes.
    pub const fn media_type(&self) -> &MediaType {
        &self.media_type
    }

    /// Returns retained and observed size accounting.
    pub const fn extent(&self) -> &ArtifactByteExtent {
        &self.extent
    }

    /// Returns the payload sensitivity classification.
    pub const fn sensitivity(&self) -> ArtifactSensitivity {
        self.sensitivity
    }

    /// Returns browser-only context needed to interpret raw payload bytes offline.
    pub const fn browser_context(&self) -> Option<&BrowserArtifactContext> {
        self.browser_context.as_ref()
    }

    /// Returns the digest of the exact retained bytes, when bytes exist.
    pub const fn content_digest(&self) -> Option<Sha256Digest> {
        self.record.content_digest()
    }

    /// Returns immediate production provenance.
    pub const fn provenance(&self) -> &Provenance {
        self.record.provenance()
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct WebArtifactMetadataWire {
    record: ArtifactRecord,
    media_type: MediaType,
    extent: ArtifactByteExtent,
    sensitivity: ArtifactSensitivity,
    #[serde(default)]
    browser_context: Option<BrowserArtifactContext>,
}

impl TryFrom<WebArtifactMetadataWire> for WebArtifactMetadata {
    type Error = WebArtifactMetadataError;

    fn try_from(value: WebArtifactMetadataWire) -> Result<Self, Self::Error> {
        Self::new_with_browser_context(
            value.record,
            value.media_type,
            value.extent,
            value.sensitivity,
            value.browser_context,
        )
    }
}

impl<'de> Deserialize<'de> for WebArtifactMetadata {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        WebArtifactMetadataWire::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}

const fn availability_matches_extent(
    availability: ArtifactAvailability,
    extent: &ArtifactByteExtent,
) -> bool {
    matches!(
        (availability, extent),
        (
            ArtifactAvailability::Retained,
            ArtifactByteExtent::Complete { .. }
        ) | (
            ArtifactAvailability::Truncated,
            ArtifactByteExtent::Truncated(_)
        ) | (
            ArtifactAvailability::Discarded,
            ArtifactByteExtent::Discarded { .. }
        ) | (
            ArtifactAvailability::Unavailable,
            ArtifactByteExtent::Unavailable
        )
    )
}
