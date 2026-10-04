use super::*;

/// Safely publishable evidence retained when bundle-last orchestration fails.
#[derive(Debug)]
pub struct DirectHttpCaptureEvidence {
    pub(super) response: Option<crate::DirectHttpResponseFacts>,
    pub(super) resolution: Option<crate::CaptureResolution>,
    pub(super) body: Option<ResponseBodyOutcome>,
    pub(super) source_facts: Option<SourceRepresentationFacts>,
}
impl DirectHttpCaptureEvidence {
    pub const fn response(&self) -> Option<&crate::DirectHttpResponseFacts> {
        self.response.as_ref()
    }
    pub const fn resolution(&self) -> Option<&crate::CaptureResolution> {
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
    SourceBinding(#[from] crate::SourceBindingError),
    #[error("capture has no retained source representation evidence artifact")]
    SourceRepresentationUnavailable,
    #[error("capture does not contain exactly one source representation evidence artifact")]
    AmbiguousSourceRepresentation,
    #[error("capture bundle has no payload for its source representation evidence artifact")]
    SourceRepresentationPayloadUnavailable,
    #[error("source representation evidence artifact or payload is invalid")]
    SourceRepresentation(#[from] crate::SourceRepresentationArtifactError),
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
    ArtifactId(#[source] yosoi_types::ArtifactIdError),
    #[error("artifact record is invalid")]
    ArtifactRecord(#[source] yosoi_types::ArtifactRecordError),
    #[error("artifact metadata is invalid")]
    Metadata(#[source] crate::WebArtifactMetadataError),
    #[error("artifact extent is invalid")]
    Extent(#[source] crate::ArtifactByteExtentError),
    #[error("media type is invalid")]
    MediaType(#[source] crate::MediaTypeError),
    #[error("reason code is invalid")]
    Reason(#[source] yosoi_types::NamespacedIdError),
    #[error("decoded output identity is invalid")]
    DecodedIdentity(#[source] DecodedOutputIdentityError),
    #[error("source binding is invalid")]
    SourceBinding(#[source] crate::SourceBindingError),
    #[error("source representation evidence is invalid")]
    SourceRepresentationEvidence(#[source] crate::SourceRepresentationEvidenceError),
    #[error("source representation artifact is invalid")]
    SourceRepresentationArtifact(#[source] crate::SourceRepresentationArtifactError),
    #[error("artifact collection is invalid")]
    Collection(#[source] crate::ArtifactCollectionError),
    #[error("artifact manifest is invalid")]
    Manifest(#[source] crate::WebArtifactManifestError),
    #[error("payload staging is invalid")]
    Staging(#[source] StagedPayloadError),
    #[error("lifecycle finalization failed")]
    Lifecycle(#[source] LifecycleError),
    #[error("decoder producer identity is invalid")]
    DecoderProducer(#[source] crate::SourceDecoderProducerError),
    #[error("in-flight accounting is invalid")]
    InFlight(#[source] crate::InFlightActivityError),
    #[error("unsupported classified source was configured to fail the attempt")]
    UnsupportedSource {
        facts: Box<SourceRepresentationFacts>,
    },
}
