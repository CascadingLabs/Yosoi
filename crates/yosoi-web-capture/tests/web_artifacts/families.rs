#![allow(clippy::unwrap_used, reason = "validated static test fixtures")]

use serde_json::json;
use yosoi_types::{
    ActivityId, ArtifactAvailability, ArtifactId, ArtifactRecord, ArtifactRef, Provenance,
    Sha256Digest,
};
use yosoi_web_capture::{
    AccessibilityTreeArtifact, ArtifactByteExtent, ArtifactSensitivity, ByteCount, CookieArtifact,
    DECODED_SOURCE_UTF8_MEDIA_TYPE, DecodedSourceArtifact, DecodedSourceArtifactError,
    LayoutArtifact, MediaType, NetworkArtifact, RenderedDomArtifact, RuntimeDiagnosticsArtifact,
    SOURCE_REPRESENTATION_EVIDENCE_MEDIA_TYPE, SourceArtifact, SourceRepresentationArtifact,
    SourceRepresentationArtifactError, StorageArtifact, VisualArtifact, WebArtifact,
    WebArtifactMetadata, WebArtifactRef, WebArtifactRelationship,
};

use super::support::{producer, reason, retained_metadata};

#[test]
fn every_initial_family_has_a_distinct_wire_discriminant() {
    let activity = ActivityId::random();
    let source = SourceArtifact::new(retained_metadata(activity, 1, "text/html", b"source"));
    let source_representation = SourceRepresentationArtifact::try_from_source(
        decoded_metadata(
            activity,
            2,
            SOURCE_REPRESENTATION_EVIDENCE_MEDIA_TYPE,
            vec![source.reference().as_untyped()],
            ArtifactAvailability::Retained,
        ),
        source.reference(),
    )
    .unwrap();
    let artifacts = vec![
        WebArtifact::from(source),
        WebArtifact::from(source_representation),
        WebArtifact::from(RenderedDomArtifact::new(retained_metadata(
            activity,
            3,
            "application/json",
            b"dom",
        ))),
        WebArtifact::from(AccessibilityTreeArtifact::new(retained_metadata(
            activity,
            4,
            "application/json",
            b"ax",
        ))),
        WebArtifact::from(NetworkArtifact::new(retained_metadata(
            activity,
            5,
            "application/json",
            b"network",
        ))),
        WebArtifact::from(CookieArtifact::new(retained_metadata(
            activity,
            6,
            "application/json",
            b"cookies",
        ))),
        WebArtifact::from(StorageArtifact::new(retained_metadata(
            activity,
            7,
            "application/json",
            b"storage",
        ))),
        WebArtifact::from(LayoutArtifact::new(retained_metadata(
            activity,
            8,
            "application/json",
            b"layout",
        ))),
        WebArtifact::from(VisualArtifact::new(retained_metadata(
            activity,
            9,
            "image/png",
            b"visual",
        ))),
        WebArtifact::from(RuntimeDiagnosticsArtifact::new(retained_metadata(
            activity,
            10,
            "application/json",
            b"console",
        ))),
    ];
    let expected = [
        "source",
        "source_representation",
        "rendered_dom",
        "accessibility_tree",
        "network",
        "cookies",
        "storage",
        "layout",
        "visual",
        "runtime_diagnostics",
    ];

    for (artifact, expected_family) in artifacts.iter().zip(expected) {
        let encoded = serde_json::to_value(artifact).unwrap();
        assert_eq!(encoded["family"], json!(expected_family));
        assert_eq!(
            serde_json::from_value::<WebArtifact>(encoded).unwrap(),
            *artifact
        );
    }
}

#[test]
fn source_representation_constructor_enforces_media_lineage_and_identity() {
    let activity = ActivityId::random();
    let source = SourceArtifact::new(retained_metadata(activity, 1, "text/html", b"source"));
    let wrong_media = decoded_metadata(
        activity,
        2,
        "application/json",
        vec![source.reference().as_untyped()],
        ArtifactAvailability::Retained,
    );
    assert!(matches!(
        SourceRepresentationArtifact::try_from_source(wrong_media, source.reference()),
        Err(SourceRepresentationArtifactError::WrongMediaType)
    ));
    let missing_lineage = decoded_metadata(
        activity,
        2,
        SOURCE_REPRESENTATION_EVIDENCE_MEDIA_TYPE,
        Vec::new(),
        ArtifactAvailability::Retained,
    );
    assert!(matches!(
        SourceRepresentationArtifact::try_from_source(missing_lineage, source.reference()),
        Err(SourceRepresentationArtifactError::InvalidLineage)
    ));
    let reused_identity = decoded_metadata(
        activity,
        1,
        SOURCE_REPRESENTATION_EVIDENCE_MEDIA_TYPE,
        vec![source.reference().as_untyped()],
        ArtifactAvailability::Retained,
    );
    assert!(matches!(
        SourceRepresentationArtifact::try_from_source(reused_identity, source.reference()),
        Err(SourceRepresentationArtifactError::SameArtifact)
    ));
}

#[test]
fn unknown_family_and_unknown_fields_fail_closed() {
    let artifact = WebArtifact::from(SourceArtifact::new(retained_metadata(
        ActivityId::random(),
        1,
        "text/html",
        b"source",
    )));
    let mut unknown_field = serde_json::to_value(&artifact).unwrap();
    unknown_field["future"] = json!(true);

    assert!(serde_json::from_value::<WebArtifact>(unknown_field).is_err());
    assert!(
        serde_json::from_value::<WebArtifact>(json!({
            "family": "future_family",
            "artifact": serde_json::to_value(artifact.metadata()).unwrap()
        }))
        .is_err()
    );
}

fn decoded_metadata(
    activity: ActivityId,
    output_id: u32,
    media_type: &str,
    lineage: Vec<ArtifactRef>,
    availability: ArtifactAvailability,
) -> WebArtifactMetadata {
    let bytes = b"decoded";
    let (digest, availability_reason, extent) = if availability == ArtifactAvailability::Retained {
        (
            Some(Sha256Digest::digest(bytes)),
            None,
            ArtifactByteExtent::Complete {
                retained_bytes: ByteCount::new(7),
            },
        )
    } else {
        (
            None,
            Some(reason("test.discarded")),
            ArtifactByteExtent::Discarded {
                observed_bytes: yosoi_web_capture::MeasuredCount::Known(ByteCount::new(7)),
            },
        )
    };
    let fixture_provenance = super::support::provenance(activity);
    let provenance = Provenance::new(
        activity,
        producer("com.cascadinglabs.test-decoder"),
        fixture_provenance.schema().clone(),
        fixture_provenance.generated_at().to_owned(),
        lineage,
    );
    let record = ArtifactRecord::new(
        ArtifactId::try_from(output_id).unwrap(),
        digest,
        availability,
        availability_reason,
        provenance,
    )
    .unwrap();
    WebArtifactMetadata::new(
        record,
        MediaType::new(media_type).unwrap(),
        extent,
        ArtifactSensitivity::NonSensitive,
    )
    .unwrap()
}

#[test]
fn decoded_source_constructor_enforces_family_invariants() {
    let activity = ActivityId::random();
    let source = ArtifactRef::new(activity, ArtifactId::try_from(1).unwrap());
    let valid = || {
        decoded_metadata(
            activity,
            2,
            DECODED_SOURCE_UTF8_MEDIA_TYPE,
            vec![source],
            ArtifactAvailability::Retained,
        )
    };

    assert!(DecodedSourceArtifact::try_from(valid()).is_ok());
    assert_eq!(
        DecodedSourceArtifact::try_from(decoded_metadata(
            activity,
            2,
            "text/plain",
            vec![source],
            ArtifactAvailability::Retained,
        )),
        Err(DecodedSourceArtifactError::WrongMediaType)
    );
    for lineage in [Vec::new(), vec![source, source]] {
        assert_eq!(
            DecodedSourceArtifact::try_from_source(
                decoded_metadata(
                    activity,
                    2,
                    DECODED_SOURCE_UTF8_MEDIA_TYPE,
                    lineage,
                    ArtifactAvailability::Retained,
                ),
                yosoi_web_capture::SourceArtifactRef::from_untyped(source),
            ),
            Err(DecodedSourceArtifactError::InvalidLineage)
        );
    }
    let wrong_source = ArtifactRef::new(activity, ArtifactId::try_from(3).unwrap());
    assert_eq!(
        DecodedSourceArtifact::try_from_source(
            decoded_metadata(
                activity,
                2,
                DECODED_SOURCE_UTF8_MEDIA_TYPE,
                vec![wrong_source],
                ArtifactAvailability::Retained,
            ),
            yosoi_web_capture::SourceArtifactRef::from_untyped(source),
        ),
        Err(DecodedSourceArtifactError::InvalidLineage)
    );
    let foreign = ArtifactRef::new(ActivityId::random(), ArtifactId::try_from(1).unwrap());
    assert_eq!(
        DecodedSourceArtifact::try_from(decoded_metadata(
            activity,
            2,
            DECODED_SOURCE_UTF8_MEDIA_TYPE,
            vec![foreign],
            ArtifactAvailability::Retained,
        )),
        Err(DecodedSourceArtifactError::DifferentActivity)
    );
    assert_eq!(
        DecodedSourceArtifact::try_from(decoded_metadata(
            activity,
            1,
            DECODED_SOURCE_UTF8_MEDIA_TYPE,
            vec![source],
            ArtifactAvailability::Retained,
        )),
        Err(DecodedSourceArtifactError::SameArtifact)
    );
    assert_eq!(
        DecodedSourceArtifact::try_from(decoded_metadata(
            activity,
            2,
            DECODED_SOURCE_UTF8_MEDIA_TYPE,
            vec![source],
            ArtifactAvailability::Discarded,
        )),
        Err(DecodedSourceArtifactError::InvalidAvailability)
    );
}

#[test]
fn decoded_source_wire_round_trip_revalidates_media_and_lineage() {
    let activity = ActivityId::random();
    let source = ArtifactRef::new(activity, ArtifactId::try_from(1).unwrap());
    let artifact = WebArtifact::from(
        DecodedSourceArtifact::try_from(decoded_metadata(
            activity,
            2,
            DECODED_SOURCE_UTF8_MEDIA_TYPE,
            vec![source],
            ArtifactAvailability::Retained,
        ))
        .unwrap(),
    );
    let encoded = serde_json::to_value(&artifact).unwrap();
    assert_eq!(
        serde_json::from_value::<WebArtifact>(encoded.clone()).unwrap(),
        artifact
    );

    let mut wrong_media = encoded.clone();
    wrong_media["artifact"]["metadata"]["media_type"] = json!("text/plain");
    assert!(serde_json::from_value::<WebArtifact>(wrong_media).is_err());
    let mut wrong_lineage = encoded.clone();
    wrong_lineage["artifact"]["metadata"]["record"]["provenance"]["derived_from"] = json!([]);
    assert!(serde_json::from_value::<WebArtifact>(wrong_lineage).is_err());

    for (field, mutation) in [
        ("encoding", json!("utf8")),
        ("policy_version", json!(999)),
        ("unicode_extent", json!("truncated")),
    ] {
        let mut invalid = encoded.clone();
        invalid["artifact"]["interpretation"][field] = mutation;
        assert!(
            serde_json::from_value::<WebArtifact>(invalid).is_err(),
            "accepted mutated {field}"
        );
    }
}

#[test]
fn family_typed_references_and_relationships_round_trip() {
    let activity = ActivityId::random();
    let source = SourceArtifact::new(retained_metadata(activity, 1, "text/html", b"source"));
    let dom = RenderedDomArtifact::new(retained_metadata(activity, 2, "application/json", b"dom"));
    let relationship = WebArtifactRelationship::RenderedRepresentationOfSource {
        rendered_dom: dom.reference(),
        source: source.reference(),
    };

    assert_eq!(source.reference().as_untyped().activity_id(), activity);
    assert!(matches!(
        WebArtifactRef::from(dom.reference()),
        WebArtifactRef::RenderedDom(_)
    ));
    assert_eq!(
        serde_json::from_value::<WebArtifactRelationship>(
            serde_json::to_value(relationship).unwrap()
        )
        .unwrap(),
        relationship
    );
}
