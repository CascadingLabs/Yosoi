//! Validated provider-neutral browser artifact staging identities and envelopes.
use std::{collections::HashSet, fmt, num::NonZeroU32, sync::Arc};
use thiserror::Error;
use yosoi_types::{ActivityId, ArtifactId, ArtifactRef, Producer, Schema, Sha256Digest};

use crate::{ArtifactByteExtent, ArtifactSensitivity, CaptureOffset, MediaType};

mod source_representation;
pub use source_representation::{
    BrowserDecodedSource, BrowserSourceRepresentation, BrowserSourceRepresentationError,
    canonical_browser_source_representation,
};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BrowserArtifactIdentityPlan {
    activity: ActivityId,
    ids: [ArtifactId; 11],
}

#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum BrowserArtifactIdentityPlanError {
    #[error("browser artifact identities must be unique within the activity")]
    DuplicateIdentity,
}

impl BrowserArtifactIdentityPlan {
    pub fn sequential(activity: ActivityId) -> Self {
        let ids = [
            NonZeroU32::MIN,
            NonZeroU32::MIN.saturating_add(1),
            NonZeroU32::MIN.saturating_add(2),
            NonZeroU32::MIN.saturating_add(3),
            NonZeroU32::MIN.saturating_add(4),
            NonZeroU32::MIN.saturating_add(5),
            NonZeroU32::MIN.saturating_add(6),
            NonZeroU32::MIN.saturating_add(7),
            NonZeroU32::MIN.saturating_add(8),
            NonZeroU32::MIN.saturating_add(9),
            NonZeroU32::MIN.saturating_add(10),
        ]
        .map(ArtifactId::new);
        Self { activity, ids }
    }
    pub fn new(
        activity: ActivityId,
        ids: [ArtifactId; 11],
    ) -> Result<Self, BrowserArtifactIdentityPlanError> {
        let mut seen = HashSet::new();
        if ids.iter().any(|id| !seen.insert(*id)) {
            return Err(BrowserArtifactIdentityPlanError::DuplicateIdentity);
        }
        Ok(Self { activity, ids })
    }
    pub const fn activity(&self) -> ActivityId {
        self.activity
    }
    /// Rebinds the caller-selected artifact IDs to one new capture activity.
    pub const fn with_activity(mut self, activity: ActivityId) -> Self {
        self.activity = activity;
        self
    }
    pub fn reference(&self, family: crate::BrowserStagingFamily) -> Option<ArtifactRef> {
        self.ids
            .get(identity_index(family))
            .copied()
            .map(|id| ArtifactRef::new(self.activity, id))
    }
    pub fn source(&self) -> Option<crate::SourceArtifactRef> {
        self.reference(crate::BrowserStagingFamily::Artifact(
            crate::WebArtifactFamily::Source,
        ))
        .map(crate::SourceArtifactRef::from_untyped)
    }
    pub fn source_representation(&self) -> Option<crate::SourceRepresentationArtifactRef> {
        self.reference(crate::BrowserStagingFamily::SourceRepresentation)
            .map(crate::SourceRepresentationArtifactRef::from_untyped)
    }
    pub fn rendered_dom(&self) -> Option<crate::RenderedDomArtifactRef> {
        self.reference(crate::BrowserStagingFamily::Artifact(
            crate::WebArtifactFamily::RenderedDom,
        ))
        .map(crate::RenderedDomArtifactRef::from_untyped)
    }
    pub fn network(&self) -> Option<crate::NetworkArtifactRef> {
        self.reference(crate::BrowserStagingFamily::Artifact(
            crate::WebArtifactFamily::Network,
        ))
        .map(crate::NetworkArtifactRef::from_untyped)
    }
}

const fn identity_index(family: crate::BrowserStagingFamily) -> usize {
    match family {
        crate::BrowserStagingFamily::Artifact(crate::WebArtifactFamily::Source) => 0,
        crate::BrowserStagingFamily::SourceRepresentation
        | crate::BrowserStagingFamily::Artifact(crate::WebArtifactFamily::SourceRepresentation) => {
            1
        }
        crate::BrowserStagingFamily::Artifact(crate::WebArtifactFamily::DecodedSource) => 2,
        crate::BrowserStagingFamily::Artifact(crate::WebArtifactFamily::RenderedDom) => 3,
        crate::BrowserStagingFamily::Artifact(crate::WebArtifactFamily::AccessibilityTree) => 4,
        crate::BrowserStagingFamily::Artifact(crate::WebArtifactFamily::Network) => 5,
        crate::BrowserStagingFamily::Artifact(crate::WebArtifactFamily::Cookies) => 6,
        crate::BrowserStagingFamily::Artifact(crate::WebArtifactFamily::Storage) => 7,
        crate::BrowserStagingFamily::Artifact(crate::WebArtifactFamily::Layout) => 8,
        crate::BrowserStagingFamily::Artifact(crate::WebArtifactFamily::Visual) => 9,
        crate::BrowserStagingFamily::Artifact(crate::WebArtifactFamily::RuntimeDiagnostics) => 10,
    }
}

#[derive(Clone, Eq, PartialEq)]
pub struct StagedBrowserArtifactEnvelope {
    reference: ArtifactRef,
    schema: Schema,
    producer: Producer,
    media_type: MediaType,
    digest: Sha256Digest,
    extent: ArtifactByteExtent,
    sensitivity: ArtifactSensitivity,
    generated_at: CaptureOffset,
    bytes: Arc<[u8]>,
    derived_from: Vec<ArtifactRef>,
}

impl fmt::Debug for StagedBrowserArtifactEnvelope {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("StagedBrowserArtifactEnvelope")
            .field("reference", &self.reference)
            .field("schema", &self.schema)
            .field("producer", &self.producer)
            .field("media_type", &self.media_type)
            .field("digest", &self.digest)
            .field("extent", &self.extent)
            .field("sensitivity", &self.sensitivity)
            .field("generated_at", &self.generated_at)
            .field("byte_len", &self.bytes.len())
            .field("bytes", &"<redacted>")
            .field("derived_from", &self.derived_from)
            .finish()
    }
}

#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum StagedBrowserArtifactEnvelopeError {
    #[error("staged artifact extent must retain exactly the supplied bytes")]
    LengthMismatch,
    #[error("staged artifact digest does not cover the supplied bytes")]
    DigestMismatch,
    #[error("staged artifact lineage contains itself or duplicates")]
    InvalidLineage,
}

impl StagedBrowserArtifactEnvelope {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        reference: ArtifactRef,
        schema: Schema,
        producer: Producer,
        media_type: MediaType,
        digest: Sha256Digest,
        extent: ArtifactByteExtent,
        sensitivity: ArtifactSensitivity,
        generated_at: CaptureOffset,
        bytes: Arc<[u8]>,
        derived_from: Vec<ArtifactRef>,
    ) -> Result<Self, StagedBrowserArtifactEnvelopeError> {
        let retained = extent
            .retained_bytes()
            .ok_or(StagedBrowserArtifactEnvelopeError::LengthMismatch)?;
        if usize::try_from(retained.get()).ok() != Some(bytes.len()) {
            return Err(StagedBrowserArtifactEnvelopeError::LengthMismatch);
        }
        if Sha256Digest::digest(&bytes) != digest {
            return Err(StagedBrowserArtifactEnvelopeError::DigestMismatch);
        }
        let mut seen = HashSet::new();
        if derived_from
            .iter()
            .any(|item| *item == reference || !seen.insert(*item))
        {
            return Err(StagedBrowserArtifactEnvelopeError::InvalidLineage);
        }
        Ok(Self {
            reference,
            schema,
            producer,
            media_type,
            digest,
            extent,
            sensitivity,
            generated_at,
            bytes,
            derived_from,
        })
    }
    pub const fn reference(&self) -> ArtifactRef {
        self.reference
    }
    pub const fn schema(&self) -> &Schema {
        &self.schema
    }
    pub const fn producer(&self) -> &Producer {
        &self.producer
    }
    pub const fn media_type(&self) -> &MediaType {
        &self.media_type
    }
    pub const fn digest(&self) -> Sha256Digest {
        self.digest
    }
    pub const fn extent(&self) -> &ArtifactByteExtent {
        &self.extent
    }
    pub const fn sensitivity(&self) -> ArtifactSensitivity {
        self.sensitivity
    }
    pub const fn generated_at(&self) -> CaptureOffset {
        self.generated_at
    }
    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }
    pub fn shared_bytes(&self) -> Arc<[u8]> {
        Arc::clone(&self.bytes)
    }
    pub fn derived_from(&self) -> &[ArtifactRef] {
        &self.derived_from
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sequential_plan_assigns_distinct_source_interpretation_identities() {
        let activity = ActivityId::random();
        let plan = BrowserArtifactIdentityPlan::sequential(activity);
        let source = plan
            .reference(crate::BrowserStagingFamily::Artifact(
                crate::WebArtifactFamily::Source,
            ))
            .expect("source identity");
        let representation = plan
            .reference(crate::BrowserStagingFamily::SourceRepresentation)
            .expect("representation identity");
        let decoded = plan
            .reference(crate::BrowserStagingFamily::Artifact(
                crate::WebArtifactFamily::DecodedSource,
            ))
            .expect("decoded identity");
        assert_eq!(source.activity_id(), activity);
        assert_ne!(source, representation);
        assert_ne!(source, decoded);
        assert_ne!(representation, decoded);
    }

    #[test]
    fn custom_plan_rejects_duplicate_artifact_ids() {
        let activity = ActivityId::random();
        let duplicate = ArtifactId::new(NonZeroU32::MIN);
        assert_eq!(
            BrowserArtifactIdentityPlan::new(activity, [duplicate; 11]),
            Err(BrowserArtifactIdentityPlanError::DuplicateIdentity)
        );
    }

    #[test]
    fn rebinding_activity_preserves_every_caller_selected_artifact_id() {
        let original_activity = ActivityId::random();
        let rebound_activity = ActivityId::random();
        let original = BrowserArtifactIdentityPlan::sequential(original_activity);
        let rebound = original.clone().with_activity(rebound_activity);

        assert_eq!(rebound.activity(), rebound_activity);
        for family in [
            crate::BrowserStagingFamily::Artifact(crate::WebArtifactFamily::Source),
            crate::BrowserStagingFamily::SourceRepresentation,
            crate::BrowserStagingFamily::Artifact(crate::WebArtifactFamily::DecodedSource),
            crate::BrowserStagingFamily::Artifact(crate::WebArtifactFamily::RenderedDom),
            crate::BrowserStagingFamily::Artifact(crate::WebArtifactFamily::AccessibilityTree),
            crate::BrowserStagingFamily::Artifact(crate::WebArtifactFamily::Network),
            crate::BrowserStagingFamily::Artifact(crate::WebArtifactFamily::Cookies),
            crate::BrowserStagingFamily::Artifact(crate::WebArtifactFamily::Storage),
            crate::BrowserStagingFamily::Artifact(crate::WebArtifactFamily::Layout),
            crate::BrowserStagingFamily::Artifact(crate::WebArtifactFamily::Visual),
            crate::BrowserStagingFamily::Artifact(crate::WebArtifactFamily::RuntimeDiagnostics),
        ] {
            assert_eq!(
                original
                    .reference(family)
                    .map(yosoi_types::ArtifactRef::artifact_id),
                rebound
                    .reference(family)
                    .map(yosoi_types::ArtifactRef::artifact_id)
            );
        }
    }
}
