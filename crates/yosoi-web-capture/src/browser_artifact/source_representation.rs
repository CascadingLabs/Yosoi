use std::sync::Arc;

use thiserror::Error;
use yosoi_types::{ArtifactAvailability, ArtifactRecord, Producer, Provenance, ReasonCode, Schema};

use crate::{
    ArtifactByteExtent, DecodedOutputIdentity, DecodedSourceArtifactRef, DecodedSourceView,
    RetainedSource, RetainedSourceExtent, SourceArtifact, SourceArtifactRef,
    SourceRepresentationEvidence, SourceRepresentationFacts, StagedBrowserArtifactEnvelope,
    ValidatedSourceBinding,
};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BrowserDecodedSource {
    reference: DecodedSourceArtifactRef,
    producer: Producer,
    bytes: Arc<[u8]>,
    output_truncated: bool,
}

impl BrowserDecodedSource {
    pub const fn reference(&self) -> DecodedSourceArtifactRef {
        self.reference
    }

    pub const fn producer(&self) -> &Producer {
        &self.producer
    }

    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }

    pub const fn output_truncated(&self) -> bool {
        self.output_truncated
    }

    pub fn into_parts(self) -> (DecodedSourceArtifactRef, Producer, Arc<[u8]>, bool) {
        (
            self.reference,
            self.producer,
            self.bytes,
            self.output_truncated,
        )
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BrowserSourceRepresentation {
    evidence_json: Vec<u8>,
    decoded_source: Option<BrowserDecodedSource>,
}

impl BrowserSourceRepresentation {
    pub fn evidence_json(&self) -> &[u8] {
        &self.evidence_json
    }

    pub const fn decoded_source(&self) -> Option<&BrowserDecodedSource> {
        self.decoded_source.as_ref()
    }

    pub fn into_parts(self) -> (Vec<u8>, Option<BrowserDecodedSource>) {
        (self.evidence_json, self.decoded_source)
    }
}

#[derive(Debug, Error)]
pub enum BrowserSourceRepresentationError {
    #[error("source envelope is not a valid retained source artifact")]
    InvalidSource,
    #[error("decoded source identity does not match the classified view")]
    DecodedReferenceMismatch,
    #[error("source decoder producer identity is invalid")]
    DecoderProducer(#[source] crate::SourceDecoderProducerError),
    #[error("source representation evidence could not be produced")]
    Evidence,
}

/// Classifies the exact staged source bytes once and retains the matching decoded view.
pub fn canonical_browser_source_representation(
    source: &StagedBrowserArtifactEnvelope,
    declaration: &crate::SourceMediaType,
    decoded_identity: DecodedSourceArtifactRef,
    decoded_schema: Schema,
    unicode_limit: u64,
) -> Result<BrowserSourceRepresentation, BrowserSourceRepresentationError> {
    let source_ref = SourceArtifactRef::from_untyped(source.reference());
    let complete = matches!(source.extent(), ArtifactByteExtent::Complete { .. });
    let availability = if complete {
        ArtifactAvailability::Retained
    } else {
        ArtifactAvailability::Truncated
    };
    let availability_reason = if complete {
        None
    } else {
        Some(
            ReasonCode::new("browser.source.provider-truncated")
                .map_err(|_| BrowserSourceRepresentationError::InvalidSource)?,
        )
    };
    let provenance = Provenance::new(
        source.reference().activity_id(),
        source.producer().clone(),
        source.schema().clone(),
        chrono::DateTime::UNIX_EPOCH,
        Vec::new(),
    );
    let record = ArtifactRecord::new(
        source.reference().artifact_id(),
        Some(source.digest()),
        availability,
        availability_reason,
        provenance,
    )
    .map_err(|_| BrowserSourceRepresentationError::InvalidSource)?;
    let metadata = crate::WebArtifactMetadata::new(
        record,
        source.media_type().clone(),
        source.extent().clone(),
        source.sensitivity(),
    )
    .map_err(|_| BrowserSourceRepresentationError::InvalidSource)?;
    let artifact = SourceArtifact::new(metadata);
    let extent = if complete {
        RetainedSourceExtent::Complete
    } else {
        RetainedSourceExtent::Truncated
    };
    let retained = RetainedSource::from_shared(source.shared_bytes(), extent);
    let decoder_producer = crate::source_decoder_producer()
        .map_err(BrowserSourceRepresentationError::DecoderProducer)?;
    let decoded = DecodedOutputIdentity::new(
        decoded_identity,
        decoder_producer.clone(),
        decoded_schema,
        vec![source.reference()],
        source_ref,
    )
    .map_err(|_| BrowserSourceRepresentationError::InvalidSource)?;
    let binding = ValidatedSourceBinding::new(&retained, &artifact)
        .map_err(|_| BrowserSourceRepresentationError::InvalidSource)?;
    let facts = crate::classify_and_decode(binding, declaration, &decoded, unicode_limit);
    let decoded_reference = decoded_reference(&facts);
    let evidence = SourceRepresentationEvidence::from_facts(source_ref, decoded_reference, &facts)
        .and_then(|evidence| evidence.to_canonical_json())
        .map_err(|_| BrowserSourceRepresentationError::Evidence)?;
    let decoded_source = into_decoded_source(facts, decoded_reference, decoder_producer)?;
    Ok(BrowserSourceRepresentation {
        evidence_json: evidence,
        decoded_source,
    })
}

const fn decoded_reference(facts: &SourceRepresentationFacts) -> Option<DecodedSourceArtifactRef> {
    match facts.decoding() {
        crate::CharacterDecodingOutcome::Complete(view)
        | crate::CharacterDecodingOutcome::OutputTruncated(view) => {
            Some(view.artifact().reference())
        }
        crate::CharacterDecodingOutcome::UnsupportedEncoding(_)
        | crate::CharacterDecodingOutcome::Undecodable(_)
        | crate::CharacterDecodingOutcome::NotApplicable(_) => None,
    }
}

fn into_decoded_source(
    facts: SourceRepresentationFacts,
    expected_reference: Option<DecodedSourceArtifactRef>,
    producer: Producer,
) -> Result<Option<BrowserDecodedSource>, BrowserSourceRepresentationError> {
    match facts.into_decoding() {
        crate::CharacterDecodingOutcome::Complete(view) => {
            into_decoded_view(view, expected_reference, false, producer).map(Some)
        }
        crate::CharacterDecodingOutcome::OutputTruncated(view) => {
            into_decoded_view(view, expected_reference, true, producer).map(Some)
        }
        crate::CharacterDecodingOutcome::UnsupportedEncoding(_)
        | crate::CharacterDecodingOutcome::Undecodable(_)
        | crate::CharacterDecodingOutcome::NotApplicable(_) => Ok(None),
    }
}

fn into_decoded_view(
    view: DecodedSourceView,
    expected_reference: Option<DecodedSourceArtifactRef>,
    output_truncated: bool,
    producer: Producer,
) -> Result<BrowserDecodedSource, BrowserSourceRepresentationError> {
    let reference = view.artifact().reference();
    if expected_reference != Some(reference) {
        return Err(BrowserSourceRepresentationError::DecodedReferenceMismatch);
    }
    Ok(BrowserDecodedSource {
        reference,
        producer,
        bytes: Arc::from(view.into_bytes()),
        output_truncated,
    })
}
