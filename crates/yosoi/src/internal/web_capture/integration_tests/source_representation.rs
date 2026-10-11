#![allow(clippy::panic, clippy::unwrap_used, reason = "black-box test fixtures")]

use crate::internal::types as internal_types;
use crate::internal::types::{
    ActivityId, ArtifactAvailability, ArtifactId, ArtifactRecord, ArtifactRef, Producer,
    ProducerId, ProducerVersion, Provenance, Schema, SchemaId, SchemaVersion, Sha256Digest,
};
use crate::internal::web_capture as internal_web_capture;
use crate::internal::web_capture::{
    ArtifactByteExtent, ArtifactSensitivity, BoundedSourceMediaType, ByteCount,
    CharacterDecodingOutcome, DecodedOutputIdentity, DecodedSourceArtifactRef, MediaType,
    RetainedSource, SourceArtifact, SourceArtifactRef, SourceMediaType, SourceMediaTypeTooLong,
    SourceRepresentationFacts, ValidatedSourceBinding, WebArtifactMetadata, classify_and_decode,
};
use chrono::{DateTime, Utc};

fn producer(name: &str) -> Producer {
    Producer::new(
        ProducerId::new(name).unwrap(),
        ProducerVersion::new("1.2.3").unwrap(),
    )
}
fn schema(name: &str) -> Schema {
    Schema::new(
        SchemaId::new(name).unwrap(),
        SchemaVersion::try_from(1).unwrap(),
    )
}
fn provenance(activity: ActivityId) -> Provenance {
    Provenance::new(
        activity,
        producer("com.cascadinglabs.tests.source"),
        schema("com.cascadinglabs.tests.source-schema"),
        "2026-01-01T00:00:00Z".parse::<DateTime<Utc>>().unwrap(),
        Vec::new(),
    )
}
fn source_with(
    activity: ActivityId,
    id: u32,
    bytes: &[u8],
    size: u64,
    digest: Sha256Digest,
    extent: ArtifactByteExtent,
) -> SourceArtifact {
    let record = ArtifactRecord::new(
        ArtifactId::try_from(id).unwrap(),
        Some(digest),
        match extent {
            ArtifactByteExtent::Complete { .. } => ArtifactAvailability::Retained,
            ArtifactByteExtent::Truncated(_) => ArtifactAvailability::Truncated,
            _ => panic!("fixture requires retained bytes"),
        },
        match extent {
            ArtifactByteExtent::Complete { .. } => None,
            _ => Some(internal_types::ReasonCode::new("test.truncated").unwrap()),
        },
        provenance(activity),
    )
    .unwrap();
    let metadata = WebArtifactMetadata::new(
        record,
        MediaType::new("application/octet-stream").unwrap(),
        match extent {
            ArtifactByteExtent::Complete { .. } => ArtifactByteExtent::Complete {
                retained_bytes: ByteCount::new(size),
            },
            other => other,
        },
        ArtifactSensitivity::NonSensitive,
    )
    .unwrap();
    let _ = bytes;
    SourceArtifact::new(metadata)
}
fn source(activity: ActivityId, bytes: &[u8]) -> SourceArtifact {
    source_with(
        activity,
        1,
        bytes,
        u64::try_from(bytes.len()).unwrap(),
        Sha256Digest::digest(bytes),
        ArtifactByteExtent::Complete {
            retained_bytes: ByteCount::new(u64::try_from(bytes.len()).unwrap()),
        },
    )
}
fn output(activity: ActivityId, source: SourceArtifactRef) -> DecodedOutputIdentity {
    let reference = DecodedSourceArtifactRef::from_untyped(ArtifactRef::new(
        activity,
        ArtifactId::try_from(2).unwrap(),
    ));
    DecodedOutputIdentity::new(
        reference,
        producer("com.cascadinglabs.tests.decoder"),
        schema("com.cascadinglabs.tests.decoded-source"),
        vec![source.as_untyped()],
        source,
    )
    .unwrap()
}
const fn facts(content_type: SourceMediaType, _status: u16) -> SourceMediaType {
    content_type
}
#[allow(
    clippy::needless_pass_by_value,
    reason = "test callers construct one-use media observations"
)]
fn run_limit(header: SourceMediaType, bytes: &[u8], limit: u64) -> SourceRepresentationFacts {
    let activity = ActivityId::random();
    let body = RetainedSource::complete(bytes.to_vec());
    let artifact = source(activity, bytes);
    let identity = output(activity, artifact.reference());
    classify_and_decode(
        ValidatedSourceBinding::new(&body, &artifact).unwrap(),
        &header,
        &identity,
        limit,
    )
}
fn run(header: &str, bytes: &[u8]) -> SourceRepresentationFacts {
    run_limit(SourceMediaType::from_text(header), bytes, 1_000_000)
}
fn missing(bytes: &[u8]) -> SourceRepresentationFacts {
    run_limit(SourceMediaType::Absent, bytes, 1_000_000)
}
fn view(facts: &SourceRepresentationFacts) -> &internal_web_capture::DecodedSourceView {
    match facts.decoding() {
        CharacterDecodingOutcome::Complete(v) | CharacterDecodingOutcome::OutputTruncated(v) => v,
        other => panic!("expected decoded view, got {other:?}"),
    }
}

#[path = "source_representation/declaration.rs"]
mod declaration;
#[path = "source_representation/decoding.rs"]
mod decoding;
#[path = "source_representation/identity.rs"]
mod identity;
#[path = "source_representation/limits.rs"]
mod limits;
#[path = "source_representation/sniff.rs"]
mod sniff;
