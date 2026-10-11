use crate::internal::web_capture as yosoi_web_capture;

use crate::internal::types::{ArtifactAvailability, ArtifactRef, Sha256Digest};
use serde::{Deserialize, Deserializer, Serialize, Serializer, de::Error as _};
use thiserror::Error;

use super::{ArtifactByteExtent, SourceArtifactRef, WebArtifactMetadata};
use crate::internal::web_capture::{
    DurableCharacterDecoding, SOURCE_REPRESENTATION_EVIDENCE_MEDIA_TYPE,
    SourceRepresentationEvidence, SourceRepresentationEvidenceError,
};

#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct SourceRepresentationArtifactRef(ArtifactRef);
impl SourceRepresentationArtifactRef {
    pub const fn from_untyped(reference: ArtifactRef) -> Self {
        Self(reference)
    }
    pub const fn as_untyped(self) -> ArtifactRef {
        self.0
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SourceRepresentationArtifact {
    metadata: WebArtifactMetadata,
    source: SourceArtifactRef,
}

#[derive(Debug, Error)]
pub enum SourceRepresentationArtifactError {
    #[error("source representation evidence must use its canonical JSON media type")]
    WrongMediaType,
    #[error("source representation evidence artifact must be retained and complete")]
    InvalidAvailability,
    #[error("source representation evidence must derive directly and only from source")]
    InvalidLineage,
    #[error("source representation evidence and source must belong to the same activity")]
    DifferentActivity,
    #[error("source representation evidence requires its own artifact identity")]
    SameArtifact,
    #[error("source representation evidence payload size does not match metadata")]
    SizeMismatch,
    #[error("source representation evidence payload digest does not match metadata")]
    DigestMismatch,
    #[error("source representation evidence payload is invalid")]
    Evidence(#[source] SourceRepresentationEvidenceError),
    #[error("decoded source evidence belongs to another activity")]
    ForeignDecodedSource,
    #[error("decoded source evidence does not have a distinct decoded artifact identity")]
    InvalidDecodedSource,
    #[error("source representation artifact is absent from the capture")]
    ArtifactUnavailable,
    #[error("source representation evidence names a source absent from the capture")]
    SourceUnavailable,
    #[error("source representation evidence names a decoded source absent from the capture")]
    DecodedSourceUnavailable,
}

impl SourceRepresentationArtifact {
    pub fn try_from_source(
        metadata: WebArtifactMetadata,
        source: SourceArtifactRef,
    ) -> Result<Self, SourceRepresentationArtifactError> {
        let artifact = Self::validate(metadata)?;
        if artifact.source != source {
            return Err(SourceRepresentationArtifactError::InvalidLineage);
        }
        Ok(artifact)
    }

    fn validate(metadata: WebArtifactMetadata) -> Result<Self, SourceRepresentationArtifactError> {
        if metadata.media_type().as_str() != SOURCE_REPRESENTATION_EVIDENCE_MEDIA_TYPE {
            return Err(SourceRepresentationArtifactError::WrongMediaType);
        }
        if !matches!(
            (metadata.record().availability(), metadata.extent()),
            (
                ArtifactAvailability::Retained,
                ArtifactByteExtent::Complete { .. }
            )
        ) {
            return Err(SourceRepresentationArtifactError::InvalidAvailability);
        }
        let source = match metadata.provenance().derived_from() {
            [source] => *source,
            _ => return Err(SourceRepresentationArtifactError::InvalidLineage),
        };
        let output = metadata.reference();
        if output.activity_id() != source.activity_id() {
            return Err(SourceRepresentationArtifactError::DifferentActivity);
        }
        if output.artifact_id() == source.artifact_id() {
            return Err(SourceRepresentationArtifactError::SameArtifact);
        }
        Ok(Self {
            metadata,
            source: SourceArtifactRef::from_untyped(source),
        })
    }

    pub fn parse_payload(
        &self,
        bytes: &[u8],
    ) -> Result<SourceRepresentationEvidence, SourceRepresentationArtifactError> {
        let retained = self
            .metadata
            .extent()
            .retained_bytes()
            .ok_or(SourceRepresentationArtifactError::SizeMismatch)?;
        let size = u64::try_from(bytes.len())
            .map_err(|_| SourceRepresentationArtifactError::SizeMismatch)?;
        if retained.get() != size {
            return Err(SourceRepresentationArtifactError::SizeMismatch);
        }
        if self.metadata.content_digest() != Some(Sha256Digest::digest(bytes)) {
            return Err(SourceRepresentationArtifactError::DigestMismatch);
        }
        let evidence = SourceRepresentationEvidence::from_json(bytes)
            .map_err(SourceRepresentationArtifactError::Evidence)?;
        if evidence.source() != self.source {
            return Err(SourceRepresentationArtifactError::InvalidLineage);
        }
        let decoded = match evidence.decoding() {
            DurableCharacterDecoding::Complete(view)
            | DurableCharacterDecoding::OutputTruncated(view) => view.decoded_source(),
            DurableCharacterDecoding::UnsupportedEncoding { .. }
            | DurableCharacterDecoding::Undecodable { .. }
            | DurableCharacterDecoding::NotApplicable { .. } => None,
        };
        if let Some(reference) = decoded {
            let decoded = reference.as_untyped();
            let source = self.source.as_untyped();
            if decoded.activity_id() != source.activity_id() {
                return Err(SourceRepresentationArtifactError::ForeignDecodedSource);
            }
            if decoded.artifact_id() == source.artifact_id()
                || decoded.artifact_id() == self.metadata.reference().artifact_id()
            {
                return Err(SourceRepresentationArtifactError::InvalidDecodedSource);
            }
        }
        Ok(evidence)
    }

    /// Parses the payload and verifies every typed reference against a finalized capture.
    pub fn parse_payload_for_capture(
        &self,
        capture: &yosoi_web_capture::WebCapture,
        bytes: &[u8],
    ) -> Result<SourceRepresentationEvidence, SourceRepresentationArtifactError> {
        let evidence = self.parse_payload(bytes)?;
        let artifact_present = capture
            .artifacts()
            .results()
            .source_representation()
            .artifacts()
            .is_some_and(|artifacts| {
                artifacts
                    .iter()
                    .any(|artifact| artifact.reference() == self.reference())
            });
        if !artifact_present {
            return Err(SourceRepresentationArtifactError::ArtifactUnavailable);
        }
        let source_present = capture
            .artifacts()
            .results()
            .source()
            .artifacts()
            .is_some_and(|artifacts| {
                artifacts
                    .iter()
                    .any(|artifact| artifact.reference() == evidence.source())
            });
        if !source_present {
            return Err(SourceRepresentationArtifactError::SourceUnavailable);
        }
        let decoded = match evidence.decoding() {
            DurableCharacterDecoding::Complete(view)
            | DurableCharacterDecoding::OutputTruncated(view) => view.decoded_source(),
            DurableCharacterDecoding::UnsupportedEncoding { .. }
            | DurableCharacterDecoding::Undecodable { .. }
            | DurableCharacterDecoding::NotApplicable { .. } => None,
        };
        if decoded.is_some_and(|reference| {
            !capture
                .artifacts()
                .results()
                .decoded_source()
                .artifacts()
                .is_some_and(|artifacts| {
                    artifacts
                        .iter()
                        .any(|artifact| artifact.reference() == reference)
                })
        }) {
            return Err(SourceRepresentationArtifactError::DecodedSourceUnavailable);
        }
        Ok(evidence)
    }

    pub const fn metadata(&self) -> &WebArtifactMetadata {
        &self.metadata
    }
    pub const fn source(&self) -> SourceArtifactRef {
        self.source
    }
    pub const fn reference(&self) -> SourceRepresentationArtifactRef {
        SourceRepresentationArtifactRef(self.metadata.reference())
    }
    pub fn into_metadata(self) -> WebArtifactMetadata {
        self.metadata
    }
}

impl TryFrom<WebArtifactMetadata> for SourceRepresentationArtifact {
    type Error = SourceRepresentationArtifactError;
    fn try_from(metadata: WebArtifactMetadata) -> Result<Self, Self::Error> {
        Self::validate(metadata)
    }
}

impl Serialize for SourceRepresentationArtifact {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        self.metadata.serialize(serializer)
    }
}
impl<'de> Deserialize<'de> for SourceRepresentationArtifact {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let metadata = WebArtifactMetadata::deserialize(deserializer)?;
        Self::validate(metadata).map_err(D::Error::custom)
    }
}
