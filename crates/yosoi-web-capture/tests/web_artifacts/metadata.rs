use serde_json::json;
use yosoi_types::{ActivityId, ArtifactAvailability, ArtifactId, ArtifactRecord, Sha256Digest};
use yosoi_web_capture::{
    ArtifactByteExtent, ArtifactSensitivity, ByteCount, MeasuredCount, MediaType, MediaTypeError,
    WebArtifactMetadata,
};

use super::support::{provenance, reason, retained_metadata};

#[test]
fn media_types_are_canonical_bounded_essences() {
    let media_type = MediaType::new("application/vnd.yosoi.dom+json").unwrap();
    assert_eq!(media_type.as_str(), "application/vnd.yosoi.dom+json");
    assert_eq!(
        serde_json::to_string(&media_type).unwrap(),
        json!(media_type.as_str()).to_string()
    );

    assert_eq!(MediaType::new(""), Err(MediaTypeError::Empty));
    assert_eq!(MediaType::new("text"), Err(MediaTypeError::InvalidFormat));
    assert_eq!(
        MediaType::new("text/html/extra"),
        Err(MediaTypeError::InvalidFormat)
    );
    assert_eq!(
        MediaType::new("Text/HTML"),
        Err(MediaTypeError::InvalidCharacter)
    );
    assert_eq!(
        MediaType::new("text/html; charset=utf-8"),
        Err(MediaTypeError::InvalidCharacter)
    );
}

#[test]
fn retained_metadata_round_trips_with_exact_size_digest_and_provenance() {
    let activity = ActivityId::random();
    let metadata = retained_metadata(activity, 1, "text/html", b"<html></html>");

    assert_eq!(metadata.reference().activity_id(), activity);
    assert_eq!(metadata.extent().retained_bytes(), Some(ByteCount::new(13)));
    assert_eq!(
        metadata.content_digest(),
        Some(Sha256Digest::digest(b"<html></html>"))
    );
    assert_eq!(metadata.sensitivity(), ArtifactSensitivity::NonSensitive);

    let encoded = serde_json::to_value(&metadata).unwrap();
    assert_eq!(
        serde_json::from_value::<WebArtifactMetadata>(encoded).unwrap(),
        metadata
    );
}

#[test]
fn byte_extent_must_agree_with_generic_artifact_availability() {
    let metadata = retained_metadata(ActivityId::random(), 1, "application/json", b"{}");
    let mut encoded = serde_json::to_value(metadata).unwrap();
    encoded["extent"] = json!({ "status": "unavailable" });

    assert!(serde_json::from_value::<WebArtifactMetadata>(encoded).is_err());
}

#[test]
fn truncation_distinguishes_retained_and_unavailable_complete_size() {
    let activity = ActivityId::random();
    let retained_prefix = b"partial";
    let record = ArtifactRecord::new(
        ArtifactId::try_from(1).unwrap(),
        Some(Sha256Digest::digest(retained_prefix)),
        ArtifactAvailability::Truncated,
        Some(reason("capture.byte-limit")),
        provenance(activity),
    )
    .unwrap();
    let metadata = WebArtifactMetadata::new(
        record,
        MediaType::new("application/json").unwrap(),
        ArtifactByteExtent::truncated(
            ByteCount::new(7),
            MeasuredCount::Unavailable {
                reason: reason("provider.size-unavailable"),
            },
        )
        .unwrap(),
        ArtifactSensitivity::Sensitive,
    )
    .unwrap();

    assert_eq!(metadata.extent().retained_bytes(), Some(ByteCount::new(7)));
    assert_eq!(metadata.sensitivity(), ArtifactSensitivity::Sensitive);
    assert_eq!(
        serde_json::from_value::<WebArtifactMetadata>(serde_json::to_value(&metadata).unwrap())
            .unwrap(),
        metadata
    );
}

#[test]
fn truncated_retained_bytes_must_be_smaller_than_a_known_complete_size() {
    assert!(
        ArtifactByteExtent::truncated(ByteCount::new(8), MeasuredCount::Known(ByteCount::new(8)),)
            .is_err()
    );
    assert!(
        ArtifactByteExtent::truncated(ByteCount::new(8), MeasuredCount::Known(ByteCount::new(7)),)
            .is_err()
    );
    assert!(
        serde_json::from_value::<ArtifactByteExtent>(json!({
            "status": "truncated",
            "retained_bytes": 8,
            "complete_bytes": {
                "status": "known",
                "value": 7
            }
        }))
        .is_err()
    );
}
