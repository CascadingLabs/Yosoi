use serde::{Deserialize, Deserializer, Serialize, Serializer, de::Error as _};
use thiserror::Error;
use yosoi_types::{ArtifactAvailability, ArtifactRef};

use super::{
    ArtifactByteExtent, SourceArtifactRef, WebArtifact, WebArtifactMetadata, WebArtifactRef,
};

#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct DecodedSourceArtifactRef(ArtifactRef);
impl DecodedSourceArtifactRef {
    pub const fn from_untyped(reference: ArtifactRef) -> Self {
        Self(reference)
    }
    pub const fn as_untyped(self) -> ArtifactRef {
        self.0
    }
}

/// Stable vocabulary describing how retained source bytes became the UTF-8 payload.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DecodingBasis {
    Bom,
    HttpCharset,
    HtmlMeta,
    HtmlFallback,
    XmlDeclaration,
    XmlAutodetection,
    XmlDefaultUtf8,
    JsonUtf8,
    PlainUtf8Validation,
}
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DecodingConflict {
    HttpCharset,
    InBandDeclaration,
    JsonCharsetIgnored,
    JsonBomAccepted,
    EncodingSignature,
}
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DecodedExtent {
    Complete,
    Truncated,
}

pub const DECODED_SOURCE_POLICY_VERSION: u16 = 1;
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DecodedSourceInterpretation {
    encoding: String,
    basis: DecodingBasis,
    replacements: u64,
    conflicts: Vec<DecodingConflict>,
    source_extent: DecodedExtent,
    unicode_extent: DecodedExtent,
    policy_version: u16,
}
impl DecodedSourceInterpretation {
    pub fn new(
        encoding: &str,
        basis: DecodingBasis,
        replacements: u64,
        conflicts: Vec<DecodingConflict>,
        source_extent: DecodedExtent,
        unicode_extent: DecodedExtent,
    ) -> Result<Self, DecodedSourceArtifactError> {
        let canonical = encoding_rs::Encoding::for_label(encoding.as_bytes())
            .ok_or(DecodedSourceArtifactError::InvalidEncoding)?;
        if canonical.name() != encoding {
            return Err(DecodedSourceArtifactError::NonCanonicalEncoding);
        }
        Ok(Self {
            encoding: encoding.to_owned(),
            basis,
            replacements,
            conflicts,
            source_extent,
            unicode_extent,
            policy_version: DECODED_SOURCE_POLICY_VERSION,
        })
    }
    pub fn encoding(&self) -> &str {
        &self.encoding
    }
    pub const fn basis(&self) -> DecodingBasis {
        self.basis
    }
    pub const fn replacements(&self) -> u64 {
        self.replacements
    }
    pub fn conflicts(&self) -> &[DecodingConflict] {
        &self.conflicts
    }
    pub const fn source_extent(&self) -> DecodedExtent {
        self.source_extent
    }
    pub const fn unicode_extent(&self) -> DecodedExtent {
        self.unicode_extent
    }
    pub const fn policy_version(&self) -> u16 {
        self.policy_version
    }
    fn validate(&self) -> Result<(), DecodedSourceArtifactError> {
        let rebuilt = Self::new(
            &self.encoding,
            self.basis,
            self.replacements,
            self.conflicts.clone(),
            self.source_extent,
            self.unicode_extent,
        )?;
        if rebuilt.policy_version != self.policy_version {
            return Err(DecodedSourceArtifactError::UnsupportedPolicyVersion);
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum DecodedSourceArtifactError {
    #[error("decoded source must use the canonical decoded-source UTF-8 media type")]
    WrongMediaType,
    #[error("decoded source must be a retained complete or truncated view")]
    InvalidAvailability,
    #[error("decoded source must derive directly and only from one source artifact")]
    InvalidLineage,
    #[error("decoded source and source input must belong to the same activity")]
    DifferentActivity,
    #[error("decoded source must have an artifact ID distinct from its source")]
    SameArtifact,
    #[error("decoded source interpretation encoding is invalid")]
    InvalidEncoding,
    #[error("decoded source interpretation encoding is not canonical")]
    NonCanonicalEncoding,
    #[error("decoded source interpretation policy version is unsupported")]
    UnsupportedPolicyVersion,
    #[error("decoded source interpretation extent disagrees with artifact extent")]
    ExtentMismatch,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DecodedSourceArtifact {
    metadata: WebArtifactMetadata,
    source: SourceArtifactRef,
    interpretation: DecodedSourceInterpretation,
}
impl DecodedSourceArtifact {
    pub fn try_from_source(
        metadata: WebArtifactMetadata,
        source: SourceArtifactRef,
    ) -> Result<Self, DecodedSourceArtifactError> {
        let extent = extent_from_metadata(&metadata)?;
        let interpretation = DecodedSourceInterpretation::new(
            "UTF-8",
            DecodingBasis::PlainUtf8Validation,
            0,
            Vec::new(),
            extent,
            extent,
        )?;
        Self::try_from_source_with_interpretation(metadata, source, interpretation)
    }
    pub fn try_from_source_with_interpretation(
        metadata: WebArtifactMetadata,
        source: SourceArtifactRef,
        interpretation: DecodedSourceInterpretation,
    ) -> Result<Self, DecodedSourceArtifactError> {
        let artifact = Self::validate(metadata, interpretation)?;
        if artifact.source != source {
            return Err(DecodedSourceArtifactError::InvalidLineage);
        }
        Ok(artifact)
    }
    fn validate(
        metadata: WebArtifactMetadata,
        interpretation: DecodedSourceInterpretation,
    ) -> Result<Self, DecodedSourceArtifactError> {
        interpretation.validate()?;
        if metadata.media_type().as_str() != crate::DECODED_SOURCE_UTF8_MEDIA_TYPE {
            return Err(DecodedSourceArtifactError::WrongMediaType);
        }
        let extent = match (metadata.record().availability(), metadata.extent()) {
            (ArtifactAvailability::Retained, ArtifactByteExtent::Complete { .. }) => {
                DecodedExtent::Complete
            }
            (ArtifactAvailability::Truncated, ArtifactByteExtent::Truncated(_)) => {
                DecodedExtent::Truncated
            }
            _ => return Err(DecodedSourceArtifactError::InvalidAvailability),
        };
        if extent != interpretation.unicode_extent {
            return Err(DecodedSourceArtifactError::ExtentMismatch);
        }
        let source = match metadata.provenance().derived_from() {
            [source] => *source,
            _ => return Err(DecodedSourceArtifactError::InvalidLineage),
        };
        let output = metadata.reference();
        if output.activity_id() != source.activity_id() {
            return Err(DecodedSourceArtifactError::DifferentActivity);
        }
        if output.artifact_id() == source.artifact_id() {
            return Err(DecodedSourceArtifactError::SameArtifact);
        }
        Ok(Self {
            metadata,
            source: SourceArtifactRef::from_untyped(source),
            interpretation,
        })
    }
    pub const fn metadata(&self) -> &WebArtifactMetadata {
        &self.metadata
    }
    pub const fn source(&self) -> SourceArtifactRef {
        self.source
    }
    pub const fn interpretation(&self) -> &DecodedSourceInterpretation {
        &self.interpretation
    }
    pub const fn reference(&self) -> DecodedSourceArtifactRef {
        DecodedSourceArtifactRef(self.metadata.reference())
    }
    pub fn into_parts(self) -> (WebArtifactMetadata, DecodedSourceInterpretation) {
        (self.metadata, self.interpretation)
    }
}
const fn extent_from_metadata(
    metadata: &WebArtifactMetadata,
) -> Result<DecodedExtent, DecodedSourceArtifactError> {
    match (metadata.record().availability(), metadata.extent()) {
        (ArtifactAvailability::Retained, ArtifactByteExtent::Complete { .. }) => {
            Ok(DecodedExtent::Complete)
        }
        (ArtifactAvailability::Truncated, ArtifactByteExtent::Truncated(_)) => {
            Ok(DecodedExtent::Truncated)
        }
        _ => Err(DecodedSourceArtifactError::InvalidAvailability),
    }
}
impl TryFrom<WebArtifactMetadata> for DecodedSourceArtifact {
    type Error = DecodedSourceArtifactError;
    fn try_from(metadata: WebArtifactMetadata) -> Result<Self, Self::Error> {
        let extent = extent_from_metadata(&metadata)?;
        let interpretation = DecodedSourceInterpretation::new(
            "UTF-8",
            DecodingBasis::PlainUtf8Validation,
            0,
            Vec::new(),
            extent,
            extent,
        )?;
        Self::validate(metadata, interpretation)
    }
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Wire {
    metadata: WebArtifactMetadata,
    interpretation: DecodedSourceInterpretation,
}
impl Serialize for DecodedSourceArtifact {
    fn serialize<S: Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
        Wire {
            metadata: self.metadata.clone(),
            interpretation: self.interpretation.clone(),
        }
        .serialize(s)
    }
}
impl<'de> Deserialize<'de> for DecodedSourceArtifact {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        let w = Wire::deserialize(d)?;
        Self::validate(w.metadata, w.interpretation).map_err(D::Error::custom)
    }
}
impl From<DecodedSourceArtifact> for WebArtifact {
    fn from(value: DecodedSourceArtifact) -> Self {
        Self::DecodedSource(value)
    }
}
impl From<DecodedSourceArtifactRef> for WebArtifactRef {
    fn from(value: DecodedSourceArtifactRef) -> Self {
        Self::DecodedSource(value)
    }
}
