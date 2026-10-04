use super::*;
use yosoi_web_capture::{DecodedOutputIdentityError, SourceBindingError};

#[test]
fn valid_binding_and_decoded_identity_preserve_metadata() {
    let bytes = b"hello";
    let activity = ActivityId::random();
    let body = RetainedSource::complete(bytes.to_vec());
    let artifact = source(activity, bytes);
    let binding = ValidatedSourceBinding::new(&body, &artifact).unwrap();
    assert_eq!(binding.body().bytes(), bytes);
    assert_eq!(binding.source(), artifact.reference());
    assert_eq!(
        artifact.metadata().extent().retained_bytes().unwrap().get(),
        5
    );
    assert_eq!(
        artifact.metadata().content_digest(),
        Some(Sha256Digest::digest(bytes))
    );
    assert_eq!(
        artifact.metadata().media_type().as_str(),
        "application/octet-stream"
    );
}

#[test]
fn binding_rejects_size_mismatch() {
    let activity = ActivityId::random();
    let body = RetainedSource::complete(b"abc".to_vec());
    let artifact = source_with(
        activity,
        1,
        b"abc",
        2,
        body.digest(),
        ArtifactByteExtent::Complete {
            retained_bytes: ByteCount::new(2),
        },
    );
    assert_eq!(
        ValidatedSourceBinding::new(&body, &artifact).unwrap_err(),
        SourceBindingError::SizeMismatch
    );
}

#[test]
fn binding_rejects_digest_mismatch() {
    let activity = ActivityId::random();
    let body = RetainedSource::complete(b"abc".to_vec());
    let artifact = source_with(
        activity,
        1,
        b"abc",
        3,
        Sha256Digest::digest(b"abd"),
        ArtifactByteExtent::Complete {
            retained_bytes: ByteCount::new(3),
        },
    );
    assert_eq!(
        ValidatedSourceBinding::new(&body, &artifact).unwrap_err(),
        SourceBindingError::DigestMismatch
    );
}

#[test]
fn binding_rejects_extent_mismatch() {
    let activity = ActivityId::random();
    let body = RetainedSource::complete(b"abc".to_vec());
    let extent = ArtifactByteExtent::truncated(
        ByteCount::new(3),
        yosoi_web_capture::MeasuredCount::Known(ByteCount::new(4)),
    )
    .unwrap();
    let artifact = source_with(activity, 1, b"abc", 3, body.digest(), extent);
    assert_eq!(
        ValidatedSourceBinding::new(&body, &artifact).unwrap_err(),
        SourceBindingError::ExtentMismatch
    );
}

#[test]
fn output_identity_requires_same_activity() {
    let activity = ActivityId::random();
    let src = source(activity, b"").reference();
    let foreign = DecodedSourceArtifactRef::from_untyped(ArtifactRef::new(
        ActivityId::random(),
        ArtifactId::try_from(2).unwrap(),
    ));
    assert_eq!(
        DecodedOutputIdentity::new(
            foreign,
            producer("com.test.decoder"),
            schema("com.test.schema"),
            vec![src.as_untyped()],
            src
        )
        .unwrap_err(),
        DecodedOutputIdentityError::DifferentActivity
    );
}

#[test]
fn output_identity_requires_distinct_artifact_id() {
    let activity = ActivityId::random();
    let src = source(activity, b"").reference();
    let same = DecodedSourceArtifactRef::from_untyped(src.as_untyped());
    assert_eq!(
        DecodedOutputIdentity::new(
            same,
            producer("com.test.decoder"),
            schema("com.test.schema"),
            vec![src.as_untyped()],
            src
        )
        .unwrap_err(),
        DecodedOutputIdentityError::SameArtifact
    );
}

#[test]
fn output_identity_rejects_empty_extra_and_foreign_lineage() {
    let activity = ActivityId::random();
    let src = source(activity, b"").reference();
    let out = DecodedSourceArtifactRef::from_untyped(ArtifactRef::new(
        activity,
        ArtifactId::try_from(2).unwrap(),
    ));
    let foreign = ArtifactRef::new(activity, ArtifactId::try_from(9).unwrap());
    for lineage in [vec![], vec![src.as_untyped(), foreign], vec![foreign]] {
        assert_eq!(
            DecodedOutputIdentity::new(
                out,
                producer("com.test.decoder"),
                schema("com.test.schema"),
                lineage,
                src
            )
            .unwrap_err(),
            DecodedOutputIdentityError::InvalidLineage
        );
    }
}

#[test]
fn decoded_view_uses_caller_identity_and_exact_lineage() {
    let activity = ActivityId::random();
    let bytes = b"\x80";
    let body = RetainedSource::complete(bytes.to_vec());
    let artifact = source(activity, bytes);
    let identity = output(activity, artifact.reference());
    let result = classify_and_decode(
        ValidatedSourceBinding::new(&body, &artifact).unwrap(),
        &facts(
            SourceMediaType::from_text("text/plain; charset=windows-1252"),
            418,
        ),
        &identity,
        99,
    );
    let decoded = view(&result);
    assert_eq!(decoded.artifact().reference(), identity.reference());
    assert_eq!(decoded.source(), artifact.reference());
    assert_eq!(decoded.producer(), identity.producer());
    assert_eq!(decoded.schema(), identity.schema());
    assert_eq!(decoded.derived_from(), [artifact.reference().as_untyped()]);
    assert_eq!(decoded.digest(), Sha256Digest::digest(decoded.bytes()));
    assert_eq!(decoded.size(), 3);
    let metadata = decoded.artifact().metadata();
    assert_eq!(
        metadata.media_type().as_str(),
        yosoi_web_capture::DECODED_SOURCE_UTF8_MEDIA_TYPE
    );
    assert_eq!(
        metadata.record().availability(),
        ArtifactAvailability::Retained
    );
    assert_eq!(metadata.record().availability_reason(), None);
    assert_eq!(
        metadata.extent(),
        &ArtifactByteExtent::Complete {
            retained_bytes: ByteCount::new(3)
        }
    );
    assert_ne!(
        metadata.content_digest(),
        artifact.metadata().content_digest()
    );
}

#[test]
fn zero_and_truncated_views_have_exact_artifact_accounting() {
    let zero = run("text/plain", b"");
    let zero = view(&zero).artifact().metadata();
    assert_eq!(zero.extent().retained_bytes(), Some(ByteCount::new(0)));
    assert_eq!(zero.content_digest(), Some(Sha256Digest::digest(b"")));
    assert_eq!(zero.record().availability(), ArtifactAvailability::Retained);
    assert!(zero.record().availability_reason().is_none());

    let truncated = run_limit(SourceMediaType::from_text("text/plain"), b"abcdef", 3);
    assert!(matches!(
        truncated.decoding(),
        CharacterDecodingOutcome::OutputTruncated(_)
    ));
    let metadata = view(&truncated).artifact().metadata();
    assert_eq!(metadata.extent().retained_bytes(), Some(ByteCount::new(3)));
    assert_eq!(
        metadata.content_digest(),
        Some(Sha256Digest::digest(b"abc"))
    );
    assert_eq!(
        metadata.record().availability(),
        ArtifactAvailability::Truncated
    );
    assert_eq!(
        metadata
            .record()
            .availability_reason()
            .map(yosoi_types::ReasonCode::as_str),
        Some("source.decoded_output_truncated")
    );
}

#[test]
fn replay_is_deterministic_and_does_not_mutate_source() {
    let bytes = b"unchanged";
    let first = run("text/plain", bytes);
    let second = run("text/plain", bytes);
    assert_eq!(first.declaration(), second.declaration());
    assert_eq!(first.classification(), second.classification());
    assert_eq!(view(&first).text(), view(&second).text());
    assert_eq!(bytes, b"unchanged");
}

#[test]
fn debug_redacts_payload_and_header() {
    let result = run("text/plain; secret=HEADER_CANARY", b"PAYLOAD_CANARY");
    let debug = format!("{result:?}");
    assert!(!debug.contains("HEADER_CANARY"));
    assert!(!debug.contains("PAYLOAD_CANARY"));
}

#[test]
fn errors_have_stable_nonempty_display() {
    for text in [
        SourceBindingError::SizeMismatch.to_string(),
        DecodedOutputIdentityError::SameArtifact.to_string(),
    ] {
        assert_ne!(text, "");
        assert!(!text.contains("CANARY"));
    }
}

#[test]
fn status_does_not_change_classification_or_decoding() {
    let a = run("application/json", b"{broken");
    let activity = ActivityId::random();
    let body = RetainedSource::complete(b"{broken".to_vec());
    let artifact = source(activity, body.bytes());
    let identity = output(activity, artifact.reference());
    let b = classify_and_decode(
        ValidatedSourceBinding::new(&body, &artifact).unwrap(),
        &facts(SourceMediaType::from_text("application/json"), 599),
        &identity,
        100,
    );
    assert_eq!(a.classification(), b.classification());
    assert_eq!(view(&a).text(), view(&b).text());
}
