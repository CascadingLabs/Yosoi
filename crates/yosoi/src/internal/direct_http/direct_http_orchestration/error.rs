use thiserror::Error;

use crate::internal::direct_http::{
    ArtifactByteExtentError, ArtifactCollectionError, CaptureResolution,
    DecodedOutputIdentityError, DirectHttpFailure, DirectHttpResponseFacts, InFlightActivityError,
    LifecycleError, MediaTypeError, ResponseBodyFailure, ResponseBodyOutcome,
    RetainedSourceReplayError, SourceBindingError, SourceDecoderProducerError,
    SourceRepresentationArtifactError, SourceRepresentationEvidenceError,
    SourceRepresentationFacts, StagedPayloadError, WebArtifactManifestError,
    WebArtifactMetadataError,
};
use crate::internal::types::{ArtifactIdError, ArtifactRecordError, NamespacedIdError};

/// Safely publishable evidence retained when bundle-last orchestration fails.
#[derive(Debug)]
pub struct DirectHttpCaptureEvidence {
    pub(super) response: Option<DirectHttpResponseFacts>,
    pub(super) resolution: Option<CaptureResolution>,
    pub(super) body: Option<ResponseBodyOutcome>,
    pub(super) source_facts: Option<SourceRepresentationFacts>,
}
impl DirectHttpCaptureEvidence {
    pub const fn response(&self) -> Option<&DirectHttpResponseFacts> {
        self.response.as_ref()
    }
    pub const fn resolution(&self) -> Option<&CaptureResolution> {
        self.resolution.as_ref()
    }
    pub const fn body(&self) -> Option<&ResponseBodyOutcome> {
        self.body.as_ref()
    }
    pub const fn source_facts(&self) -> Option<&SourceRepresentationFacts> {
        self.source_facts.as_ref()
    }
}

/// Failure of a concrete attempt. No `CaptureBundle` has been published.
#[derive(Debug, Error)]
pub enum DirectHttpReplayError {
    #[error("capture has no retained source artifact")]
    SourceUnavailable,
    #[error("capture does not contain exactly one source artifact")]
    AmbiguousSource,
    #[error("capture bundle has no payload for its source artifact")]
    PayloadUnavailable,
    #[error("source payload does not satisfy artifact metadata")]
    RetainedSource(#[from] RetainedSourceReplayError),
    #[error("source payload binding is invalid")]
    SourceBinding(#[from] SourceBindingError),
    #[error("capture has no retained source representation evidence artifact")]
    SourceRepresentationUnavailable,
    #[error("capture does not contain exactly one source representation evidence artifact")]
    AmbiguousSourceRepresentation,
    #[error("capture bundle has no payload for its source representation evidence artifact")]
    SourceRepresentationPayloadUnavailable,
    #[error("source representation evidence artifact or payload is invalid")]
    SourceRepresentation(#[from] SourceRepresentationArtifactError),
}

/// Failure of a concrete attempt. No `CaptureBundle` has been published.
#[derive(Debug, Error)]
pub enum DirectHttpCaptureError {
    #[error("Direct HTTP transport did not reach a final response")]
    Transport(#[source] DirectHttpFailure),
    #[error("response body processing failed")]
    Body(#[source] Box<ResponseBodyFailure>),
    #[error("capture construction failed")]
    Finalization {
        #[source]
        source: DirectHttpConstructionError,
        evidence: Box<DirectHttpCaptureEvidence>,
    },
}
impl DirectHttpCaptureError {
    pub const fn evidence(&self) -> Option<&DirectHttpCaptureEvidence> {
        match self {
            Self::Finalization { evidence, .. } => Some(evidence),
            _ => None,
        }
    }
}

#[derive(Debug, Error)]
pub enum DirectHttpConstructionError {
    #[error("artifact identity is invalid")]
    ArtifactId(#[source] ArtifactIdError),
    #[error("artifact record is invalid")]
    ArtifactRecord(#[source] ArtifactRecordError),
    #[error("artifact metadata is invalid")]
    Metadata(#[source] WebArtifactMetadataError),
    #[error("artifact extent is invalid")]
    Extent(#[source] ArtifactByteExtentError),
    #[error("media type is invalid")]
    MediaType(#[source] MediaTypeError),
    #[error("reason code is invalid")]
    Reason(#[source] NamespacedIdError),
    #[error("decoded output identity is invalid")]
    DecodedIdentity(#[source] DecodedOutputIdentityError),
    #[error("source binding is invalid")]
    SourceBinding(#[source] SourceBindingError),
    #[error("source representation evidence is invalid")]
    SourceRepresentationEvidence(#[source] SourceRepresentationEvidenceError),
    #[error("source representation artifact is invalid")]
    SourceRepresentationArtifact(#[source] SourceRepresentationArtifactError),
    #[error("artifact collection is invalid")]
    Collection(#[source] ArtifactCollectionError),
    #[error("artifact manifest is invalid")]
    Manifest(#[source] WebArtifactManifestError),
    #[error("payload staging is invalid")]
    Staging(#[source] StagedPayloadError),
    #[error("lifecycle finalization failed")]
    Lifecycle(#[source] LifecycleError),
    #[error("decoder producer identity is invalid")]
    DecoderProducer(#[source] SourceDecoderProducerError),
    #[error("in-flight accounting is invalid")]
    InFlight(#[source] InFlightActivityError),
    #[error("unsupported classified source was configured to fail the attempt")]
    UnsupportedSource {
        facts: Box<SourceRepresentationFacts>,
    },
}
