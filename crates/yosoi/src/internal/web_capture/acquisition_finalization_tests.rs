#![allow(
    clippy::unwrap_used,
    reason = "validated constants keep the timestamp-policy test focused"
)]

use crate::internal::types::{
    ActivityId, ArtifactAvailability, ArtifactId, ArtifactRecord, Producer, ProducerId,
    ProducerVersion, Provenance, Schema, SchemaId, SchemaVersion, Sha256Digest,
};
use chrono::{DateTime, Utc};

use super::{AcquisitionFinalizationError, ArtifactTimestampOrder, validate_artifact_timestamps};
use crate::internal::web_capture::{
    ArtifactByteExtent, ArtifactCollection, ArtifactFamilyResult, ArtifactRequest,
    ArtifactSensitivity, ByteCount, MediaType, RenderedDomArtifact, SourceArtifact,
    WebArtifactManifest, WebArtifactMetadata, WebArtifactRequestSet, WebArtifactResults,
};

fn metadata(
    activity: ActivityId,
    id: u32,
    content: &[u8],
    generated_at: DateTime<Utc>,
) -> WebArtifactMetadata {
    let producer = Producer::new(
        ProducerId::new("com.cascadinglabs.timestamp-test").unwrap(),
        ProducerVersion::new("1.0.0").unwrap(),
    );
    let provenance = Provenance::new(
        activity,
        producer,
        Schema::new(
            SchemaId::new("com.cascadinglabs.timestamp-test-artifact").unwrap(),
            SchemaVersion::try_from(1).unwrap(),
        ),
        generated_at,
        Vec::new(),
    );
    let record = ArtifactRecord::new(
        ArtifactId::try_from(id).unwrap(),
        Some(Sha256Digest::digest(content)),
        ArtifactAvailability::Retained,
        None,
        provenance,
    )
    .unwrap();
    WebArtifactMetadata::new(
        record,
        MediaType::new("application/octet-stream").unwrap(),
        ArtifactByteExtent::Complete {
            retained_bytes: ByteCount::new(u64::try_from(content.len()).unwrap()),
        },
        ArtifactSensitivity::NonSensitive,
    )
    .unwrap()
}

fn cross_family_reordered_manifest() -> WebArtifactManifest {
    let activity = ActivityId::random();
    let source_at = "2026-09-15T00:00:02Z".parse().unwrap();
    let dom_at = "2026-09-15T00:00:01Z".parse().unwrap();
    let source = ArtifactCollection::new(vec![SourceArtifact::new(metadata(
        activity, 1, b"source", source_at,
    ))])
    .unwrap();
    let dom = ArtifactCollection::new(vec![RenderedDomArtifact::new(metadata(
        activity, 2, b"dom", dom_at,
    ))])
    .unwrap();
    let not_requested = ArtifactRequest::NotRequested;
    WebArtifactManifest::new(
        WebArtifactRequestSet::new(
            ArtifactRequest::Required,
            ArtifactRequest::Required,
            not_requested,
            not_requested,
            not_requested,
            not_requested,
            not_requested,
            not_requested,
            not_requested,
        ),
        WebArtifactResults::new(
            ArtifactFamilyResult::Complete { artifacts: source },
            ArtifactFamilyResult::Complete { artifacts: dom },
            ArtifactFamilyResult::NotRequested,
            ArtifactFamilyResult::NotRequested,
            ArtifactFamilyResult::NotRequested,
            ArtifactFamilyResult::NotRequested,
            ArtifactFamilyResult::NotRequested,
            ArtifactFamilyResult::NotRequested,
            ArtifactFamilyResult::NotRequested,
        ),
    )
    .unwrap()
}

#[test]
fn independent_families_allow_cross_family_timestamp_reordering() {
    let started_at = "2026-09-15T00:00:00Z".parse().unwrap();
    let finished_at = "2026-09-15T00:00:03Z".parse().unwrap();
    let manifest = cross_family_reordered_manifest();

    assert!(matches!(
        validate_artifact_timestamps(
            started_at,
            finished_at,
            &manifest,
            ArtifactTimestampOrder::ManifestOrder,
        ),
        Err(AcquisitionFinalizationError::ArtifactTimestampsUnordered)
    ));
    validate_artifact_timestamps(
        started_at,
        finished_at,
        &manifest,
        ArtifactTimestampOrder::IndependentFamilies,
    )
    .unwrap();
}
