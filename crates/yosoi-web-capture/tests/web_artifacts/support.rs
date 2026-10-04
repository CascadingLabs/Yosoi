#![allow(
    clippy::unwrap_used,
    reason = "test fixture values are deliberately valid constants"
)]

use chrono::{DateTime, Utc};
use yosoi_types::{
    ActivityId, ArtifactAvailability, ArtifactId, ArtifactRecord, Producer, ProducerId,
    ProducerVersion, Provenance, ReasonCode, Schema, SchemaId, SchemaVersion, Sha256Digest,
};
use yosoi_web_capture::{
    ArtifactByteExtent, ArtifactSensitivity, ByteCount, MediaType, WebArtifactMetadata,
};

pub fn producer(id: &str) -> Producer {
    Producer::new(
        ProducerId::new(id).unwrap(),
        ProducerVersion::new("1.0.0").unwrap(),
    )
}

pub fn provenance(activity_id: ActivityId) -> Provenance {
    Provenance::new(
        activity_id,
        producer("com.cascadinglabs.test-producer"),
        Schema::new(
            SchemaId::new("com.cascadinglabs.test-artifact").unwrap(),
            SchemaVersion::try_from(1).unwrap(),
        ),
        "2026-09-05T15:00:00Z".parse::<DateTime<Utc>>().unwrap(),
        Vec::new(),
    )
}

pub fn retained_metadata(
    activity_id: ActivityId,
    artifact_id: u32,
    media_type: &str,
    content: &[u8],
) -> WebArtifactMetadata {
    let record = ArtifactRecord::new(
        ArtifactId::try_from(artifact_id).unwrap(),
        Some(Sha256Digest::digest(content)),
        ArtifactAvailability::Retained,
        None,
        provenance(activity_id),
    )
    .unwrap();

    WebArtifactMetadata::new(
        record,
        MediaType::new(media_type).unwrap(),
        ArtifactByteExtent::Complete {
            retained_bytes: ByteCount::new(u64::try_from(content.len()).unwrap()),
        },
        ArtifactSensitivity::NonSensitive,
    )
    .unwrap()
}

pub fn reason(value: &str) -> ReasonCode {
    ReasonCode::new(value).unwrap()
}
