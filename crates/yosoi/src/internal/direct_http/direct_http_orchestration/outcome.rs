use std::ops::Deref;

use crate::internal::direct_http::{
    CaptureBundle, DecodedOutputIdentity, DirectHttpExecutionIdentity, DirectHttpResponseFacts,
    RetainedSource, SourceRepresentationEvidence, SourceRepresentationFacts,
    ValidatedSourceBinding, classify_and_decode,
};

use super::DirectHttpReplayError;

/// Owning result of a successful Direct HTTP attempt.
///
/// Source interpretation is retained both as a convenient in-memory view and as
/// a typed, integrity-checked `SourceRepresentation` artifact payload. Persisting
/// the bundle therefore preserves declaration, classification, and decoding facts.
#[derive(Debug)]
pub struct DirectHttpCapture {
    pub(super) bundle: CaptureBundle,
    pub(super) response: DirectHttpResponseFacts,
    pub(super) source_facts: Option<SourceRepresentationFacts>,
    pub(super) identity: DirectHttpExecutionIdentity,
    pub(super) unicode_limit: u64,
}
impl DirectHttpCapture {
    pub const fn bundle(&self) -> &CaptureBundle {
        &self.bundle
    }
    pub const fn response(&self) -> &DirectHttpResponseFacts {
        &self.response
    }
    pub const fn source_facts(&self) -> Option<&SourceRepresentationFacts> {
        self.source_facts.as_ref()
    }
    pub const fn identity(&self) -> &DirectHttpExecutionIdentity {
        &self.identity
    }

    /// Replays deterministic classification and decoding from the bundled exact source payload.
    ///
    /// Response facts are the original bounded observations. This recomputation
    /// remains useful for equivalence checks against the durable evidence artifact.
    /// Parses and validates the durable source representation evidence payload.
    pub fn source_representation_evidence(
        &self,
    ) -> Result<SourceRepresentationEvidence, DirectHttpReplayError> {
        let artifacts = self
            .bundle
            .capture()
            .artifacts()
            .results()
            .source_representation()
            .artifacts()
            .ok_or(DirectHttpReplayError::SourceRepresentationUnavailable)?;
        let [artifact] = artifacts else {
            return Err(DirectHttpReplayError::AmbiguousSourceRepresentation);
        };
        let payload = self
            .bundle
            .payload(artifact.reference().into())
            .ok_or(DirectHttpReplayError::SourceRepresentationPayloadUnavailable)?;
        artifact
            .parse_payload_for_capture(self.bundle.capture(), payload)
            .map_err(Into::into)
    }

    pub fn replay_source_facts(
        &self,
        output: &DecodedOutputIdentity,
    ) -> Result<SourceRepresentationFacts, DirectHttpReplayError> {
        let artifacts = self
            .bundle
            .capture()
            .artifacts()
            .results()
            .source()
            .artifacts()
            .ok_or(DirectHttpReplayError::SourceUnavailable)?;
        let [source] = artifacts else {
            return Err(DirectHttpReplayError::AmbiguousSource);
        };
        let payload = self
            .bundle
            .payload(source.reference().into())
            .ok_or(DirectHttpReplayError::PayloadUnavailable)?;
        let retained = RetainedSource::from_artifact_payload(source, payload.to_vec())?;
        let binding = ValidatedSourceBinding::new(&retained, source)?;
        Ok(classify_and_decode(
            binding,
            &self.response.source_media_type(),
            output,
            self.unicode_limit,
        ))
    }

    pub fn into_parts(
        self,
    ) -> (
        CaptureBundle,
        DirectHttpResponseFacts,
        Option<SourceRepresentationFacts>,
        DirectHttpExecutionIdentity,
    ) {
        (self.bundle, self.response, self.source_facts, self.identity)
    }
}
impl Deref for DirectHttpCapture {
    type Target = CaptureBundle;
    fn deref(&self) -> &Self::Target {
        &self.bundle
    }
}
