use serde::{Deserialize, Serialize};
use thiserror::Error;

use super::{
    CharacterDecodingOutcome, DecodingErrorCode, MediaDeclaration, SourceClassificationOutcome,
    SourceRepresentationFacts,
};
use crate::{DecodedSourceArtifactRef, DecodingBasis, DecodingConflict, SourceArtifactRef};

pub const SOURCE_REPRESENTATION_EVIDENCE_VERSION: u16 = 1;
pub const SOURCE_REPRESENTATION_EVIDENCE_MEDIA_TYPE: &str =
    "application/vnd.yosoi.source-representation-facts+json";

/// Compact durable decoding facts. Decoded text remains in its own artifact payload.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum DurableCharacterDecoding {
    Complete(DurableDecodedView),
    OutputTruncated(DurableDecodedView),
    UnsupportedEncoding { code: DecodingErrorCode },
    Undecodable { code: DecodingErrorCode },
    NotApplicable { code: DecodingErrorCode },
}

/// Durable interpretation of a decoded view without the decoded text itself.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DurableDecodedView {
    decoded_source: Option<DecodedSourceArtifactRef>,
    encoding: String,
    basis: DecodingBasis,
    replacements: u64,
    conflicts: Vec<DecodingConflict>,
    source_truncated: bool,
    output_truncated: bool,
    incomplete_terminal_sequence: bool,
}

impl DurableDecodedView {
    pub const fn decoded_source(&self) -> Option<DecodedSourceArtifactRef> {
        self.decoded_source
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
    pub const fn source_truncated(&self) -> bool {
        self.source_truncated
    }
    pub const fn output_truncated(&self) -> bool {
        self.output_truncated
    }
    pub const fn incomplete_terminal_sequence(&self) -> bool {
        self.incomplete_terminal_sequence
    }
}

/// Versioned durable projection of source declaration, classification, and decoding facts.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SourceRepresentationEvidence {
    schema_version: u16,
    source: SourceArtifactRef,
    declaration: MediaDeclaration,
    classification: SourceClassificationOutcome,
    decoding: DurableCharacterDecoding,
}

#[derive(Debug, Error)]
pub enum SourceRepresentationEvidenceError {
    #[error("source representation evidence JSON is invalid")]
    InvalidJson(#[source] serde_json::Error),
    #[error("source representation evidence version {found} is unsupported")]
    UnsupportedVersion { found: u16 },
    #[error("source representation evidence refers to another source artifact")]
    SourceMismatch,
    #[error("source representation evidence names an unexpected decoded artifact")]
    DecodedSourceMismatch,
    #[error("source representation evidence could not be serialized")]
    Serialization(#[source] serde_json::Error),
    #[error("source representation evidence encoding is not canonical or supported")]
    InvalidEncoding,
    #[error("source representation evidence contains contradictory extent facts")]
    ContradictoryExtent,
    #[error("source representation evidence contains a contradictory decoding outcome")]
    ContradictoryDecoding,
    #[error("source representation evidence decoded reference is invalid")]
    InvalidDecodedSource,
}

impl SourceRepresentationEvidence {
    pub fn from_facts(
        source: SourceArtifactRef,
        decoded_source: Option<DecodedSourceArtifactRef>,
        facts: &SourceRepresentationFacts,
    ) -> Result<Self, SourceRepresentationEvidenceError> {
        let decoding = match facts.decoding() {
            CharacterDecodingOutcome::Complete(view) => {
                validate_view_references(source, decoded_source, view)?;
                DurableCharacterDecoding::Complete(durable_view(view, decoded_source, false))
            }
            CharacterDecodingOutcome::OutputTruncated(view) => {
                validate_view_references(source, decoded_source, view)?;
                DurableCharacterDecoding::OutputTruncated(durable_view(view, decoded_source, true))
            }
            CharacterDecodingOutcome::UnsupportedEncoding(code) => {
                DurableCharacterDecoding::UnsupportedEncoding { code: *code }
            }
            CharacterDecodingOutcome::Undecodable(code) => {
                DurableCharacterDecoding::Undecodable { code: *code }
            }
            CharacterDecodingOutcome::NotApplicable(code) => {
                DurableCharacterDecoding::NotApplicable { code: *code }
            }
        };
        let evidence = Self {
            schema_version: SOURCE_REPRESENTATION_EVIDENCE_VERSION,
            source,
            declaration: facts.declaration().clone(),
            classification: facts.classification().clone(),
            decoding,
        };
        evidence.validate()?;
        Ok(evidence)
    }

    pub fn from_json(bytes: &[u8]) -> Result<Self, SourceRepresentationEvidenceError> {
        let evidence: Self = serde_json::from_slice(bytes)
            .map_err(SourceRepresentationEvidenceError::InvalidJson)?;
        if evidence.schema_version != SOURCE_REPRESENTATION_EVIDENCE_VERSION {
            return Err(SourceRepresentationEvidenceError::UnsupportedVersion {
                found: evidence.schema_version,
            });
        }
        evidence.validate()?;
        Ok(evidence)
    }

    pub fn to_canonical_json(&self) -> Result<Vec<u8>, SourceRepresentationEvidenceError> {
        serde_json::to_vec(self).map_err(SourceRepresentationEvidenceError::Serialization)
    }

    pub const fn schema_version(&self) -> u16 {
        self.schema_version
    }
    pub const fn source(&self) -> SourceArtifactRef {
        self.source
    }
    pub const fn declaration(&self) -> &MediaDeclaration {
        &self.declaration
    }
    pub const fn classification(&self) -> &SourceClassificationOutcome {
        &self.classification
    }
    pub const fn decoding(&self) -> &DurableCharacterDecoding {
        &self.decoding
    }

    fn validate(&self) -> Result<(), SourceRepresentationEvidenceError> {
        let classified = matches!(
            self.classification,
            SourceClassificationOutcome::Classified(_)
        );
        let classification_truncated = classification_extent(&self.classification)
            == super::ClassificationExtent::RetainedPrefix;
        match &self.decoding {
            DurableCharacterDecoding::Complete(view) => validate_view(
                self.source,
                view,
                false,
                classified,
                classification_truncated,
            ),
            DurableCharacterDecoding::OutputTruncated(view) => validate_view(
                self.source,
                view,
                true,
                classified,
                classification_truncated,
            ),
            DurableCharacterDecoding::UnsupportedEncoding { .. }
            | DurableCharacterDecoding::Undecodable { .. }
                if classified =>
            {
                Ok(())
            }
            DurableCharacterDecoding::NotApplicable {
                code: DecodingErrorCode::NotClassified,
            } if !classified => Ok(()),
            DurableCharacterDecoding::UnsupportedEncoding { .. }
            | DurableCharacterDecoding::Undecodable { .. }
            | DurableCharacterDecoding::NotApplicable { .. } => {
                Err(SourceRepresentationEvidenceError::ContradictoryDecoding)
            }
        }
    }
}

const fn classification_extent(
    classification: &SourceClassificationOutcome,
) -> super::ClassificationExtent {
    match classification {
        SourceClassificationOutcome::Classified(value) => value.extent(),
        SourceClassificationOutcome::Unknown { extent, .. }
        | SourceClassificationOutcome::Unsupported { extent, .. }
        | SourceClassificationOutcome::Ambiguous { extent, .. } => *extent,
    }
}

fn validate_view(
    source: SourceArtifactRef,
    view: &DurableDecodedView,
    output_truncated: bool,
    classified: bool,
    classification_truncated: bool,
) -> Result<(), SourceRepresentationEvidenceError> {
    if !classified {
        return Err(SourceRepresentationEvidenceError::ContradictoryDecoding);
    }
    if view.output_truncated != output_truncated
        || view.source_truncated != classification_truncated
    {
        return Err(SourceRepresentationEvidenceError::ContradictoryExtent);
    }
    let encoding = encoding_rs::Encoding::for_label(view.encoding.as_bytes())
        .ok_or(SourceRepresentationEvidenceError::InvalidEncoding)?;
    if encoding.name() != view.encoding {
        return Err(SourceRepresentationEvidenceError::InvalidEncoding);
    }
    if let Some(decoded) = view.decoded_source {
        let decoded = decoded.as_untyped();
        let source = source.as_untyped();
        if decoded.activity_id() != source.activity_id()
            || decoded.artifact_id() == source.artifact_id()
        {
            return Err(SourceRepresentationEvidenceError::InvalidDecodedSource);
        }
    }
    Ok(())
}

fn validate_view_references(
    source: SourceArtifactRef,
    decoded_source: Option<DecodedSourceArtifactRef>,
    view: &super::DecodedSourceView,
) -> Result<(), SourceRepresentationEvidenceError> {
    if view.source() != source {
        return Err(SourceRepresentationEvidenceError::SourceMismatch);
    }
    if decoded_source.is_some_and(|reference| reference != view.artifact().reference()) {
        return Err(SourceRepresentationEvidenceError::DecodedSourceMismatch);
    }
    Ok(())
}

fn durable_view(
    view: &super::DecodedSourceView,
    decoded_source: Option<DecodedSourceArtifactRef>,
    output_truncated: bool,
) -> DurableDecodedView {
    DurableDecodedView {
        decoded_source,
        encoding: view.encoding().canonical_name().to_owned(),
        basis: view.basis(),
        replacements: view.replacements(),
        conflicts: view.conflicts().to_vec(),
        source_truncated: view.source_truncated(),
        output_truncated,
        incomplete_terminal_sequence: view.incomplete_terminal_sequence(),
    }
}
