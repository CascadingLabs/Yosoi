use chrono::{DateTime, Utc};
use serde_json::{Value, json};

use crate::internal::types::{
    ActivityId, ActivityOutcome, ActivityReceipt, ActivityReceiptError, ActivitySignal,
    ArtifactAvailability, ArtifactId, ArtifactRecord, ArtifactRecordError, ArtifactRef,
    CaptureArtifactRef, CaptureId, CaptureReceipt, NamespacedIdError, OccurrenceIdParseError,
    OperationId, Producer, ProducerId, ProducerVersion, ProducerVersionError, Provenance,
    ReasonCode, RetryDisposition, Schema, SchemaId, SchemaVersion, Sha256Digest,
    Sha256DigestParseError,
};

const ACTIVITY: &str = "123e4567-e89b-42d3-a456-426614174000";
const CAPTURE: &str = "123e4567-e89b-42d3-a456-426614174001";
const SHA256_ABC: &str = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";

#[test]
fn random_occurrence_identities_are_uuid_v4_and_domain_separated() {
    let activity = ActivityId::random();
    let capture = CaptureId::random();

    assert_ne!(activity, capture.activity_id());
    assert_eq!(Uuid::from_bytes(*activity.as_bytes()).get_version_num(), 4);
    assert_eq!(Uuid::from_bytes(*capture.as_bytes()).get_version_num(), 4);
}

#[test]
fn occurrence_identities_have_canonical_display_and_json() {
    let activity: ActivityId = ACTIVITY.parse().unwrap();
    let capture: CaptureId = CAPTURE.parse().unwrap();

    assert_eq!(activity.to_string(), ACTIVITY);
    assert_eq!(capture.to_string(), CAPTURE);
    assert_eq!(
        serde_json::to_string(&activity).unwrap(),
        format!("\"{ACTIVITY}\"")
    );
    assert_eq!(
        serde_json::to_string(&capture).unwrap(),
        format!("\"{CAPTURE}\"")
    );
    assert_eq!(
        serde_json::from_str::<ActivityId>(&format!("\"{ACTIVITY}\"")).unwrap(),
        activity
    );
    assert_eq!(
        serde_json::from_str::<CaptureId>(&format!("\"{CAPTURE}\"")).unwrap(),
        capture
    );
}

#[test]
fn occurrence_identities_reject_noncanonical_or_invalid_input() {
    assert_eq!(
        "123e4567e89b42d3a456426614174000".parse::<ActivityId>(),
        Err(OccurrenceIdParseError::NonCanonical)
    );
    assert_eq!(
        "123E4567-E89B-42D3-A456-426614174000".parse::<ActivityId>(),
        Err(OccurrenceIdParseError::NonCanonical)
    );
    assert_eq!(
        "123e4567-e89b-12d3-a456-426614174000".parse::<ActivityId>(),
        Err(OccurrenceIdParseError::NotRandomV4)
    );
    assert_eq!(
        "not-a-uuid".parse::<ActivityId>(),
        Err(OccurrenceIdParseError::InvalidUuid)
    );
    assert!(serde_json::from_str::<ActivityId>("17").is_err());
}

#[test]
fn local_artifact_identity_requires_activity_context() {
    let activity: ActivityId = ACTIVITY.parse().unwrap();
    let artifact = ArtifactId::try_from(1).unwrap();
    let reference = ArtifactRef::new(activity, artifact);
    let capture: CaptureId = CAPTURE.parse().unwrap();
    let captured = CaptureArtifactRef::new(capture, artifact);

    assert_eq!(artifact.to_string(), "1");
    assert_eq!(reference.activity_id(), activity);
    assert_eq!(reference.artifact_id(), artifact);
    assert_eq!(captured.capture_id(), capture);
    assert_eq!(captured.artifact_id(), artifact);
    assert_eq!(captured.artifact_ref().activity_id(), capture.activity_id());
    assert!(ArtifactId::try_from(0).is_err());
    assert!(serde_json::from_str::<ArtifactId>("0").is_err());
    assert!(serde_json::from_str::<ArtifactId>("-1").is_err());
}

#[test]
fn namespaced_identities_validate_and_round_trip() {
    let producer = ProducerId::new("com.cascadinglabs.voidcrawl.cdp").unwrap();
    let schema = SchemaId::new("com.cascadinglabs.yosoi.ax-tree").unwrap();

    assert_eq!(producer.to_string(), "com.cascadinglabs.voidcrawl.cdp");
    assert_eq!(schema.to_string(), "com.cascadinglabs.yosoi.ax-tree");
    assert_eq!(
        serde_json::from_str::<ProducerId>(&serde_json::to_string(&producer).unwrap()).unwrap(),
        producer
    );
    assert_eq!(
        serde_json::from_str::<SchemaId>(&serde_json::to_string(&schema).unwrap()).unwrap(),
        schema
    );
}

#[test]
fn namespaced_identities_reject_ambiguous_input() {
    for value in [
        "",
        "VoidCrawl",
        "voidcrawl",
        ".voidcrawl",
        "voidcrawl.",
        "voidcrawl..cdp",
        "void crawl",
        "voidcrawl/cdp",
    ] {
        assert!(ProducerId::new(value).is_err(), "accepted {value:?}");
    }
    assert_eq!(
        ProducerId::new("x".repeat(129)),
        Err(NamespacedIdError::TooLong)
    );
}

#[test]
fn opaque_producer_versions_are_explicit_and_bounded() {
    for value in ["143.0.1", "6.8.0-arch1-1", "firmware+vendor.7"] {
        let version = ProducerVersion::new(value).unwrap();
        assert_eq!(version.as_str(), value);
        assert_eq!(
            serde_json::from_str::<ProducerVersion>(&serde_json::to_string(&version).unwrap())
                .unwrap(),
            version
        );
    }
    assert_eq!(ProducerVersion::new(""), Err(ProducerVersionError::Empty));
    assert_eq!(
        ProducerVersion::new("version with spaces"),
        Err(ProducerVersionError::InvalidCharacter)
    );
    assert!(serde_json::from_str::<ProducerVersion>("\"line\\nbreak\"").is_err());
}

#[test]
fn schema_versions_are_positive_numeric_values() {
    let version = SchemaVersion::try_from(1).unwrap();

    assert_eq!(version.to_string(), "1");
    assert_eq!(serde_json::to_string(&version).unwrap(), "1");
    assert_eq!(serde_json::from_str::<SchemaVersion>("1").unwrap(), version);
    assert!(SchemaVersion::try_from(0).is_err());
    assert!(serde_json::from_str::<SchemaVersion>("0").is_err());
    assert!(serde_json::from_str::<SchemaVersion>("\"1\"").is_err());
}

#[test]
fn sha256_digest_matches_known_vector_and_round_trips() {
    let digest = Sha256Digest::digest(b"abc");

    assert_eq!(digest.to_string(), SHA256_ABC);
    assert_eq!(SHA256_ABC.parse::<Sha256Digest>().unwrap(), digest);
    assert_eq!(
        serde_json::to_string(&digest).unwrap(),
        format!("\"{SHA256_ABC}\"")
    );
    assert_eq!(
        serde_json::from_str::<Sha256Digest>(&format!("\"{SHA256_ABC}\"")).unwrap(),
        digest
    );
}

#[test]
fn sha256_digest_rejects_wrong_length_and_noncanonical_encoding() {
    assert_eq!(
        "00".parse::<Sha256Digest>(),
        Err(Sha256DigestParseError::InvalidLength)
    );
    assert_eq!(
        "0".repeat(66).parse::<Sha256Digest>(),
        Err(Sha256DigestParseError::InvalidLength)
    );
    assert_eq!(
        SHA256_ABC.to_uppercase().parse::<Sha256Digest>(),
        Err(Sha256DigestParseError::InvalidEncoding)
    );
    assert_eq!(
        format!("{}g", "0".repeat(63)).parse::<Sha256Digest>(),
        Err(Sha256DigestParseError::InvalidEncoding)
    );
    assert!(serde_json::from_str::<Sha256Digest>("42").is_err());
}

#[test]
fn provenance_has_deterministic_json_and_round_trips() {
    let activity: ActivityId = ACTIVITY.parse().unwrap();
    let source_activity: ActivityId = CAPTURE.parse().unwrap();
    let source = ArtifactRef::new(source_activity, ArtifactId::try_from(1).unwrap());
    let producer = Producer::new(
        ProducerId::new("com.cascadinglabs.yosoi.ax-normalizer").unwrap(),
        ProducerVersion::new("0.1.0").unwrap(),
    );
    let schema = Schema::new(
        SchemaId::new("com.cascadinglabs.yosoi.normalized-ax-tree").unwrap(),
        SchemaVersion::try_from(1).unwrap(),
    );
    let generated_at: DateTime<Utc> = "2026-09-04T03:00:00Z".parse().unwrap();
    let provenance = Provenance::new(activity, producer, schema, generated_at, vec![source]);

    let encoded = serde_json::to_string(&provenance).unwrap();
    assert_eq!(
        encoded,
        format!(
            "{{\"activity_id\":\"{ACTIVITY}\",\"producer\":{{\"id\":\"com.cascadinglabs.yosoi.ax-normalizer\",\"version\":\"0.1.0\"}},\"schema\":{{\"id\":\"com.cascadinglabs.yosoi.normalized-ax-tree\",\"version\":1}},\"generated_at\":\"2026-09-04T03:00:00Z\",\"derived_from\":[{{\"activity_id\":\"{CAPTURE}\",\"artifact_id\":1}}]}}"
        )
    );
    assert_eq!(
        serde_json::from_str::<Provenance>(&encoded).unwrap(),
        provenance
    );
}

#[test]
fn provenance_rejects_invalid_nested_wire_values() {
    let base = json!({
        "activity_id": ACTIVITY,
        "producer": {
            "id": "com.cascadinglabs.yosoi.parser",
            "version": "1.0.0"
        },
        "schema": {
            "id": "com.cascadinglabs.yosoi.document",
            "version": 1
        },
        "generated_at": "2026-09-04T03:00:00Z",
        "derived_from": []
    });

    for invalid in [
        changed(&base, "/activity_id", Value::String("invalid".to_owned())),
        changed(
            &base,
            "/producer/id",
            Value::String("Invalid Producer".to_owned()),
        ),
        changed(&base, "/producer/version", Value::String(String::new())),
        changed(&base, "/schema/version", Value::from(0)),
        changed(
            &base,
            "/generated_at",
            Value::String("yesterday".to_owned()),
        ),
        {
            let mut value = base.clone();
            value
                .as_object_mut()
                .unwrap()
                .insert("implicit_global".to_owned(), Value::Bool(true));
            value
        },
    ] {
        assert!(serde_json::from_value::<Provenance>(invalid).is_err());
    }
}

#[test]
fn artifact_records_enforce_and_round_trip_availability() {
    let activity: ActivityId = ACTIVITY.parse().unwrap();
    let producer = Producer::new(
        ProducerId::new("com.cascadinglabs.voidcrawl.cdp").unwrap(),
        ProducerVersion::new("1.2.3").unwrap(),
    );
    let schema = Schema::new(
        SchemaId::new("com.cascadinglabs.voidcrawl.ax-tree").unwrap(),
        SchemaVersion::try_from(1).unwrap(),
    );
    let generated_at: DateTime<Utc> = "2026-09-04T03:00:01Z".parse().unwrap();
    let provenance = Provenance::new(activity, producer, schema, generated_at, Vec::new());
    let id = ArtifactId::try_from(1).unwrap();
    let digest = Sha256Digest::digest(b"accessibility tree");
    let artifact = ArtifactRecord::new(
        id,
        Some(digest),
        ArtifactAvailability::Retained,
        None,
        provenance,
    )
    .unwrap();

    assert_eq!(artifact.reference(), ArtifactRef::new(activity, id));
    assert_eq!(artifact.content_digest(), Some(digest));
    let encoded = serde_json::to_string(&artifact).unwrap();
    assert_eq!(
        serde_json::from_str::<ArtifactRecord>(&encoded).unwrap(),
        artifact
    );

    let retained_prefix = b"accessibility";
    let prefix_digest = Sha256Digest::digest(retained_prefix);
    let truncated = ArtifactRecord::new(
        ArtifactId::try_from(2).unwrap(),
        Some(prefix_digest),
        ArtifactAvailability::Truncated,
        Some(ReasonCode::new("capture.byte-limit").unwrap()),
        artifact.provenance().clone(),
    )
    .unwrap();
    assert_eq!(truncated.content_digest(), Some(prefix_digest));
    assert_ne!(truncated.content_digest(), Some(digest));
    assert_eq!(
        serde_json::from_str::<ArtifactRecord>(&serde_json::to_string(&truncated).unwrap())
            .unwrap(),
        truncated
    );

    assert_eq!(
        ArtifactRecord::new(
            id,
            None,
            ArtifactAvailability::Retained,
            None,
            artifact.provenance().clone(),
        ),
        Err(ArtifactRecordError::MissingDigest)
    );
    assert_eq!(
        ArtifactRecord::new(
            id,
            Some(digest),
            ArtifactAvailability::Discarded,
            Some(ReasonCode::new("capture.retention-policy").unwrap()),
            artifact.provenance().clone(),
        ),
        Err(ArtifactRecordError::UnexpectedDigest)
    );
}

#[test]
fn activity_and_capture_receipts_validate_terminal_facts() {
    let capture: CaptureId = CAPTURE.parse().unwrap();
    let activity = capture.activity_id();
    let orchestrator = Producer::new(
        ProducerId::new("com.cascadinglabs.voidcrawl.capture").unwrap(),
        ProducerVersion::new("1.2.3").unwrap(),
    );
    let artifact_producer = Producer::new(
        ProducerId::new("org.chromium.accessibility").unwrap(),
        ProducerVersion::new("143.0.0").unwrap(),
    );
    let schema = Schema::new(
        SchemaId::new("com.cascadinglabs.voidcrawl.ax-tree").unwrap(),
        SchemaVersion::try_from(1).unwrap(),
    );
    let started_at: DateTime<Utc> = "2026-09-04T03:00:00Z".parse().unwrap();
    let finished_at: DateTime<Utc> = "2026-09-04T03:00:02Z".parse().unwrap();
    let provenance = Provenance::new(
        activity,
        artifact_producer.clone(),
        schema,
        finished_at,
        Vec::new(),
    );
    let artifact = ArtifactRecord::new(
        ArtifactId::try_from(1).unwrap(),
        Some(Sha256Digest::digest(b"accessibility tree")),
        ArtifactAvailability::Retained,
        None,
        provenance,
    )
    .unwrap();
    let receipt = ActivityReceipt::new(
        activity,
        OperationId::new("com.cascadinglabs.voidcrawl.capture").unwrap(),
        orchestrator,
        Vec::new(),
        vec![artifact],
        ActivityOutcome::Succeeded,
        None,
        started_at,
        finished_at,
    )
    .unwrap();
    assert_eq!(
        receipt.outputs()[0].provenance().producer(),
        &artifact_producer
    );
    assert_ne!(receipt.producer(), &artifact_producer);
    let capture_receipt = CaptureReceipt::new(capture, receipt).unwrap();

    let encoded = serde_json::to_string(&capture_receipt).unwrap();
    assert_eq!(
        serde_json::from_str::<CaptureReceipt>(&encoded).unwrap(),
        capture_receipt
    );
}

#[test]
fn activity_receipts_reject_incoherent_json() {
    let base = json!({
        "id": ACTIVITY,
        "operation": "com.cascadinglabs.yosoi.parse",
        "producer": {
            "id": "com.cascadinglabs.yosoi.parser",
            "version": "1.0.0"
        },
        "inputs": [],
        "outputs": [],
        "outcome": "succeeded",
        "signal": null,
        "started_at": "2026-09-04T03:00:02Z",
        "finished_at": "2026-09-04T03:00:00Z"
    });

    assert!(serde_json::from_value::<ActivityReceipt>(base).is_err());
    assert_eq!(
        ActivityReceipt::new(
            ACTIVITY.parse().unwrap(),
            OperationId::new("com.cascadinglabs.yosoi.parse").unwrap(),
            Producer::new(
                ProducerId::new("com.cascadinglabs.yosoi.parser").unwrap(),
                ProducerVersion::new("1.0.0").unwrap(),
            ),
            Vec::new(),
            Vec::new(),
            ActivityOutcome::Failed,
            None,
            "2026-09-04T03:00:00Z".parse().unwrap(),
            "2026-09-04T03:00:02Z".parse().unwrap(),
        ),
        Err(ActivityReceiptError::MissingSignal)
    );

    let signal = ActivitySignal::new(
        ReasonCode::new("http.not-found").unwrap(),
        RetryDisposition::NotRetryable,
    );
    let signalled = ActivityReceipt::new(
        ACTIVITY.parse().unwrap(),
        OperationId::new("com.cascadinglabs.yosoi.fetch").unwrap(),
        Producer::new(
            ProducerId::new("com.cascadinglabs.yosoi.http").unwrap(),
            ProducerVersion::new("1.0.0").unwrap(),
        ),
        Vec::new(),
        Vec::new(),
        ActivityOutcome::Failed,
        Some(signal),
        "2026-09-04T03:00:00Z".parse().unwrap(),
        "2026-09-04T03:00:02Z".parse().unwrap(),
    )
    .unwrap();
    assert_eq!(
        serde_json::from_str::<ActivityReceipt>(&serde_json::to_string(&signalled).unwrap())
            .unwrap(),
        signalled
    );
}

#[test]
fn receipt_json_validates_output_ownership_and_structure() {
    let output = json!({
        "id": 1,
        "content_digest": SHA256_ABC,
        "availability": "retained",
        "availability_reason": null,
        "provenance": {
            "activity_id": ACTIVITY,
            "producer": {
                "id": "com.cascadinglabs.yosoi.parser",
                "version": "1.0.0"
            },
            "schema": {
                "id": "com.cascadinglabs.yosoi.document",
                "version": 1
            },
            "generated_at": "2026-09-04T03:00:01Z",
            "derived_from": []
        }
    });
    let receipt = json!({
        "id": ACTIVITY,
        "operation": "com.cascadinglabs.yosoi.parse",
        "producer": {
            "id": "com.cascadinglabs.yosoi.parser",
            "version": "1.0.0"
        },
        "inputs": [],
        "outputs": [output],
        "outcome": "succeeded",
        "signal": null,
        "started_at": "2026-09-04T03:00:00Z",
        "finished_at": "2026-09-04T03:00:02Z"
    });

    let duplicate = changed(&receipt, "/outputs", json!([output.clone(), output]));
    let foreign_activity = changed(
        &receipt,
        "/outputs/0/provenance/activity_id",
        Value::String(CAPTURE.to_owned()),
    );
    let distinct_output_producer = changed(
        &receipt,
        "/outputs/0/provenance/producer/id",
        Value::String("com.cascadinglabs.voidcrawl.cdp".to_owned()),
    );
    let late_output = changed(
        &receipt,
        "/outputs/0/provenance/generated_at",
        Value::String("2026-09-04T03:00:03Z".to_owned()),
    );
    let mut unknown = receipt.clone();
    unknown
        .as_object_mut()
        .unwrap()
        .insert("process_global".to_owned(), Value::Bool(true));

    let parsed = serde_json::from_value::<ActivityReceipt>(distinct_output_producer).unwrap();
    assert_ne!(
        parsed.producer(),
        parsed.outputs()[0].provenance().producer()
    );

    for invalid in [duplicate, foreign_activity, late_output, unknown] {
        assert!(serde_json::from_value::<ActivityReceipt>(invalid).is_err());
    }

    let mismatched_capture = json!({
        "id": CAPTURE,
        "receipt": receipt
    });
    assert!(serde_json::from_value::<CaptureReceipt>(mismatched_capture).is_err());
}

fn changed(value: &Value, pointer: &str, replacement: Value) -> Value {
    let mut changed = value.clone();
    assert!(changed.pointer_mut(pointer).is_some());
    if let Some(target) = changed.pointer_mut(pointer) {
        *target = replacement;
    }
    changed
}

use uuid::Uuid;
