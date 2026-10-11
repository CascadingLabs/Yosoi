//! Bounded classification and character decoding of retained representation bytes.
use crate::internal::types as yosoi_types;

mod decoded_identity;
pub use decoded_identity::{DecodedOutputIdentity, DecodedOutputIdentityError};
mod declaration;
mod decode;
mod decode_stream;
mod evidence;
mod html_prescan;
mod sniff;
mod xml_declaration;

use std::fmt;

use crate::internal::types::{Producer, ProducerId, ProducerVersion, Sha256Digest};
use serde::{Deserialize, Serialize};
use thiserror::Error;

pub use crate::internal::web_capture::artifact::{DecodingBasis, DecodingConflict};
use crate::internal::web_capture::{
    ArtifactByteExtent, RetainedSource, RetainedSourceExtent, SourceArtifact, SourceArtifactRef,
    SourceMediaType,
};
pub use declaration::parse as parse_media_declaration;
pub use declaration::{CharsetDeclaration, CharsetIssue, MediaDeclaration, MediaDeclarationIssue};
pub use decode::{
    CharacterDecodingOutcome, DECODED_SOURCE_UTF8_MEDIA_TYPE, DecodedSourceView, DecodingErrorCode,
    SelectedEncoding,
};
pub use evidence::{
    DurableCharacterDecoding, DurableDecodedView, SOURCE_REPRESENTATION_EVIDENCE_MEDIA_TYPE,
    SOURCE_REPRESENTATION_EVIDENCE_VERSION, SourceRepresentationEvidence,
    SourceRepresentationEvidenceError,
};

/// Errors while constructing the shared source-decoder producer identity.
#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum SourceDecoderProducerError {
    #[error("source decoder producer identity is invalid")]
    InvalidId(#[source] yosoi_types::NamespacedIdError),
    #[error("source decoder producer version is invalid")]
    InvalidVersion(#[source] yosoi_types::ProducerVersionError),
}

/// Producer identity shared by browser and Direct HTTP source decoding.
pub fn source_decoder_producer() -> Result<Producer, SourceDecoderProducerError> {
    let id = ProducerId::new("com.cascadinglabs.yosoi.source-decoder")
        .map_err(SourceDecoderProducerError::InvalidId)?;
    let version = ProducerVersion::new(env!("CARGO_PKG_VERSION"))
        .map_err(SourceDecoderProducerError::InvalidVersion)?;
    Ok(Producer::new(id, version))
}

/// Closed set of source representations understood by this boundary.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(tag = "format", content = "profile", rename_all = "snake_case")]
pub enum SourceFormat {
    Html,
    Xml(XmlProfile),
    Json,
    PlainText,
}
#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum XmlProfile {
    Generic,
    Xhtml,
}
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ClassificationBasis {
    Declared,
    StructuredSuffix,
    Sniffed,
}
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ClassificationExtent {
    Complete,
    RetainedPrefix,
}
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "status", content = "detected", rename_all = "snake_case")]
pub enum DeclarationDisagreement {
    Supports,
    Conflicts(SourceFormat),
    Inconclusive,
}
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum UnknownReason {
    Empty,
    NoStrongSignature,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ClassifiedSource {
    format: SourceFormat,
    basis: ClassificationBasis,
    disagreement: DeclarationDisagreement,
    extent: ClassificationExtent,
}
impl ClassifiedSource {
    pub const fn format(&self) -> SourceFormat {
        self.format
    }
    pub const fn basis(&self) -> ClassificationBasis {
        self.basis
    }
    pub const fn disagreement(&self) -> DeclarationDisagreement {
        self.disagreement
    }
    pub const fn extent(&self) -> ClassificationExtent {
        self.extent
    }
}
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum SourceClassificationOutcome {
    Classified(ClassifiedSource),
    Unknown {
        reason: UnknownReason,
        candidates: Vec<SourceFormat>,
        extent: ClassificationExtent,
    },
    Unsupported {
        essence: String,
        disagreement: DeclarationDisagreement,
        candidates: Vec<SourceFormat>,
        extent: ClassificationExtent,
    },
    Ambiguous {
        candidates: Vec<SourceFormat>,
        disagreement: DeclarationDisagreement,
        extent: ClassificationExtent,
    },
}
#[derive(Clone, Eq, PartialEq)]
pub struct SourceRepresentationFacts {
    declaration: MediaDeclaration,
    classification: SourceClassificationOutcome,
    decoding: CharacterDecodingOutcome,
}
impl SourceRepresentationFacts {
    pub const fn declaration(&self) -> &MediaDeclaration {
        &self.declaration
    }
    pub const fn classification(&self) -> &SourceClassificationOutcome {
        &self.classification
    }
    pub const fn decoding(&self) -> &CharacterDecodingOutcome {
        &self.decoding
    }

    pub(in crate::internal::web_capture) fn into_decoding(self) -> CharacterDecodingOutcome {
        self.decoding
    }
}
impl fmt::Debug for SourceRepresentationFacts {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("SourceRepresentationFacts")
            .field("declaration", &self.declaration)
            .field("classification", &self.classification)
            .field("decoding", &self.decoding)
            .finish()
    }
}

#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum SourceBindingError {
    #[error("source artifact does not describe retained bytes")]
    BytesUnavailable,
    #[error("source artifact retained size differs from the retained body")]
    SizeMismatch,
    #[error("source artifact digest differs from the retained body")]
    DigestMismatch,
    #[error("source artifact extent differs from the retained body")]
    ExtentMismatch,
}

/// A source artifact proven to describe this exact retained byte sequence.
#[derive(Clone, Copy, Debug)]
pub struct ValidatedSourceBinding<'a> {
    body: &'a RetainedSource,
    source: &'a SourceArtifact,
}
impl<'a> ValidatedSourceBinding<'a> {
    pub fn new(
        body: &'a RetainedSource,
        source: &'a SourceArtifact,
    ) -> Result<Self, SourceBindingError> {
        let metadata = source.metadata();
        let retained = metadata
            .extent()
            .retained_bytes()
            .ok_or(SourceBindingError::BytesUnavailable)?;
        let body_size = u64::try_from(body.bytes().len()).unwrap_or(u64::MAX);
        if retained.get() != body_size {
            return Err(SourceBindingError::SizeMismatch);
        }
        if metadata.content_digest() != Some(body.digest()) {
            return Err(SourceBindingError::DigestMismatch);
        }
        let matching_extent = matches!(
            (metadata.extent(), body.extent()),
            (
                ArtifactByteExtent::Complete { .. },
                RetainedSourceExtent::Complete
            ) | (
                ArtifactByteExtent::Truncated(_),
                RetainedSourceExtent::Truncated
            )
        );
        if !matching_extent {
            return Err(SourceBindingError::ExtentMismatch);
        }
        Ok(Self { body, source })
    }
    pub const fn body(self) -> &'a RetainedSource {
        self.body
    }
    pub const fn source(self) -> SourceArtifactRef {
        self.source.reference()
    }
    pub const fn source_artifact(self) -> &'a SourceArtifact {
        self.source
    }
}

/// Classifies and decodes without modifying the validated retained body.
pub fn classify_and_decode(
    binding: ValidatedSourceBinding<'_>,
    media_type: &SourceMediaType,
    output: &DecodedOutputIdentity,
    unicode_limit: u64,
) -> SourceRepresentationFacts {
    let body = binding.body();
    let declaration = declaration::parse(media_type);
    let extent = match body.extent() {
        RetainedSourceExtent::Complete => ClassificationExtent::Complete,
        RetainedSourceExtent::Truncated => ClassificationExtent::RetainedPrefix,
    };
    let classification = classify(&declaration, body.bytes(), extent);
    let decoding = decode::decode(
        &classification,
        &declaration,
        body,
        binding.source_artifact(),
        output,
        unicode_limit,
    );
    SourceRepresentationFacts {
        declaration,
        classification,
        decoding,
    }
}

fn classify(
    declaration: &MediaDeclaration,
    bytes: &[u8],
    extent: ClassificationExtent,
) -> SourceClassificationOutcome {
    classify_detected(declaration, bytes.is_empty(), sniff::detect(bytes), extent)
}

fn classify_detected(
    declaration: &MediaDeclaration,
    bytes_empty: bool,
    mut detected: Vec<SourceFormat>,
    extent: ClassificationExtent,
) -> SourceClassificationOutcome {
    // Detector order is not classification policy. Canonicalize at the
    // decision boundary, including invariant-level callers used by tests.
    detected.sort_unstable();
    detected.dedup();
    if let MediaDeclaration::Parsed { essence, .. } = declaration {
        if let Some((format, basis)) = declared_format(essence) {
            return SourceClassificationOutcome::Classified(ClassifiedSource {
                format,
                basis,
                disagreement: disagreement(format, &detected),
                extent,
            });
        }
        if !is_generic(essence) {
            return SourceClassificationOutcome::Unsupported {
                essence: essence.clone(),
                disagreement: detected.first().copied().map_or(
                    DeclarationDisagreement::Inconclusive,
                    DeclarationDisagreement::Conflicts,
                ),
                candidates: detected,
                extent,
            };
        }
    }
    match detected.as_slice() {
        [format] => SourceClassificationOutcome::Classified(ClassifiedSource {
            format: *format,
            basis: ClassificationBasis::Sniffed,
            disagreement: DeclarationDisagreement::Inconclusive,
            extent,
        }),
        [] => SourceClassificationOutcome::Unknown {
            reason: if bytes_empty {
                UnknownReason::Empty
            } else {
                UnknownReason::NoStrongSignature
            },
            candidates: detected,
            extent,
        },
        _ => SourceClassificationOutcome::Ambiguous {
            candidates: detected,
            disagreement: DeclarationDisagreement::Inconclusive,
            extent,
        },
    }
}
fn declared_format(value: &str) -> Option<(SourceFormat, ClassificationBasis)> {
    let exact = match value {
        "text/html" => Some(SourceFormat::Html),
        "application/xhtml+xml" => Some(SourceFormat::Xml(XmlProfile::Xhtml)),
        "application/json" => Some(SourceFormat::Json),
        "application/xml" | "text/xml" => Some(SourceFormat::Xml(XmlProfile::Generic)),
        "text/plain" => Some(SourceFormat::PlainText),
        _ => None,
    };
    exact
        .map(|f| (f, ClassificationBasis::Declared))
        .or_else(|| {
            let suffix_prefix = value
                .strip_prefix("application/")
                .and_then(|subtype| subtype.rsplit_once('+'));
            if matches!(suffix_prefix, Some((prefix, "json")) if !prefix.is_empty()) {
                Some((SourceFormat::Json, ClassificationBasis::StructuredSuffix))
            } else if matches!(suffix_prefix, Some((prefix, "xml")) if !prefix.is_empty()) {
                Some((
                    SourceFormat::Xml(XmlProfile::Generic),
                    ClassificationBasis::StructuredSuffix,
                ))
            } else {
                None
            }
        })
}
fn is_generic(value: &str) -> bool {
    matches!(
        value,
        "application/octet-stream" | "application/unknown" | "unknown/unknown" | "*/*"
    )
}
fn disagreement(format: SourceFormat, detected: &[SourceFormat]) -> DeclarationDisagreement {
    if detected.contains(&format) {
        DeclarationDisagreement::Supports
    } else {
        detected.first().copied().map_or(
            DeclarationDisagreement::Inconclusive,
            DeclarationDisagreement::Conflicts,
        )
    }
}
#[cfg(test)]
#[path = "source_decision_tests.rs"]
mod decision_tests;

fn digest(bytes: &[u8]) -> Sha256Digest {
    Sha256Digest::digest(bytes)
}
