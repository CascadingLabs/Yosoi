//! CAS-300 finalized capture bundle contract tests.
#![allow(
    clippy::indexing_slicing,
    clippy::unwrap_used,
    reason = "valid test fixtures use direct fixture access"
)]

#[path = "capture_bundle/support.rs"]
mod support;

use yosoi_web_capture::{CaptureBundle, CaptureBundleError};

use support::{
    FIRST_BYTES, FirstPayloadState, SECOND_BYTES, TRUNCATED_BYTES, capture, empty_capture,
    family_mismatch_reference, foreign_source_reference, orphan_reference, source_references,
    wire_round_trip,
};

#[test]
fn complete_retained_payloads_are_verified_and_borrowed() {
    let capture = capture(FirstPayloadState::Retained);
    let references = source_references(&capture);
    let mut builder = CaptureBundle::builder(capture);
    builder.insert(references[0], FIRST_BYTES.to_vec()).unwrap();
    builder
        .insert(references[1], SECOND_BYTES.to_vec())
        .unwrap();
    let builder_debug = format!("{builder:?}");
    assert!(!builder_debug.contains("first"));
    assert!(!builder_debug.contains("[102, 105, 114, 115, 116]"));
    assert!(builder_debug.contains("<redacted>"));
    let bundle = builder.finalize().unwrap();

    assert_eq!(bundle.payload(references[0]), Some(FIRST_BYTES));
    assert_eq!(bundle.payload(references[1]), Some(SECOND_BYTES));
    assert_eq!(
        bundle.capture().id().activity_id(),
        references[0].as_untyped().activity_id()
    );
    let debug = format!("{bundle:?}");
    assert!(!debug.contains("first"));
    assert!(!debug.contains("[102, 105, 114, 115, 116]"));
    assert!(debug.contains("<redacted>"));
}

#[test]
fn exact_zero_byte_payload_is_retained() {
    let capture = capture(FirstPayloadState::Zero);
    let references = source_references(&capture);
    let mut builder = CaptureBundle::builder(capture);
    builder.insert(references[0], Vec::new()).unwrap();
    builder
        .insert(references[1], SECOND_BYTES.to_vec())
        .unwrap();
    let bundle = builder.finalize().unwrap();

    assert_eq!(bundle.payload(references[0]), Some(&[][..]));
}

#[test]
fn truncated_payload_verifies_only_its_retained_prefix() {
    let capture = capture(FirstPayloadState::Truncated);
    let references = source_references(&capture);
    let mut builder = CaptureBundle::builder(capture);
    builder
        .insert(references[0], TRUNCATED_BYTES.to_vec())
        .unwrap();
    builder
        .insert(references[1], SECOND_BYTES.to_vec())
        .unwrap();
    let bundle = builder.finalize().unwrap();

    assert_eq!(bundle.payload(references[0]), Some(TRUNCATED_BYTES));
}

#[test]
fn missing_complete_payload_prevents_publication() {
    let capture = capture(FirstPayloadState::Retained);
    let references = source_references(&capture);
    let mut builder = CaptureBundle::builder(capture);
    builder
        .insert(references[1], SECOND_BYTES.to_vec())
        .unwrap();

    assert_eq!(builder.finalize(), Err(CaptureBundleError::Missing));
}

#[test]
fn missing_truncated_payload_prevents_publication() {
    let capture = capture(FirstPayloadState::Truncated);
    let references = source_references(&capture);
    let mut builder = CaptureBundle::builder(capture);
    builder
        .insert(references[1], SECOND_BYTES.to_vec())
        .unwrap();

    assert_eq!(builder.finalize(), Err(CaptureBundleError::Missing));
}

#[test]
fn wrong_payload_size_is_rejected_before_admission() {
    let capture = capture(FirstPayloadState::Retained);
    let reference = source_references(&capture)[0];
    let mut builder = CaptureBundle::builder(capture);

    assert_eq!(
        builder.insert(reference, b"four".to_vec()),
        Err(CaptureBundleError::SizeMismatch)
    );
}

#[test]
fn wrong_payload_digest_is_rejected_before_admission() {
    let capture = capture(FirstPayloadState::Retained);
    let reference = source_references(&capture)[0];
    let mut builder = CaptureBundle::builder(capture);

    assert_eq!(
        builder.insert(reference, b"other".to_vec()),
        Err(CaptureBundleError::DigestMismatch)
    );
}

#[test]
fn discarded_artifact_cannot_expose_bytes_but_bundle_can_finalize() {
    let capture = capture(FirstPayloadState::Discarded);
    let references = source_references(&capture);
    let mut builder = CaptureBundle::builder(capture);
    assert_eq!(
        builder.insert(references[0], FIRST_BYTES.to_vec()),
        Err(CaptureBundleError::Discarded)
    );
    builder
        .insert(references[1], SECOND_BYTES.to_vec())
        .unwrap();
    let bundle = builder.finalize().unwrap();

    assert_eq!(bundle.payload(references[0]), None);
}

#[test]
fn unavailable_artifact_cannot_expose_bytes_but_bundle_can_finalize() {
    let capture = capture(FirstPayloadState::Unavailable);
    let references = source_references(&capture);
    let mut builder = CaptureBundle::builder(capture);
    assert_eq!(
        builder.insert(references[0], FIRST_BYTES.to_vec()),
        Err(CaptureBundleError::Unavailable)
    );
    builder
        .insert(references[1], SECOND_BYTES.to_vec())
        .unwrap();
    let bundle = builder.finalize().unwrap();

    assert_eq!(bundle.payload(references[0]), None);
}

#[test]
fn foreign_and_same_capture_orphan_references_remain_distinct() {
    let capture = capture(FirstPayloadState::Retained);
    let foreign = foreign_source_reference();
    let orphan = orphan_reference(&capture);
    let family_mismatch = family_mismatch_reference(&capture);
    let mut builder = CaptureBundle::builder(capture);

    for _ in 0..2 {
        assert_eq!(
            builder.insert(foreign, FIRST_BYTES.to_vec()),
            Err(CaptureBundleError::ForeignReference)
        );
        assert_eq!(
            builder.insert(orphan, FIRST_BYTES.to_vec()),
            Err(CaptureBundleError::Orphaned)
        );
    }
    assert_eq!(
        builder.insert(family_mismatch, FIRST_BYTES.to_vec()),
        Err(CaptureBundleError::Orphaned)
    );
}

#[test]
fn successfully_admitted_reference_cannot_be_inserted_twice() {
    let capture = capture(FirstPayloadState::Retained);
    let reference = source_references(&capture)[0];
    let mut builder = CaptureBundle::builder(capture);
    builder.insert(reference, FIRST_BYTES.to_vec()).unwrap();

    assert_eq!(
        builder.insert(reference, FIRST_BYTES.to_vec()),
        Err(CaptureBundleError::Duplicate)
    );
}

#[test]
fn failed_insert_does_not_reserve_the_reference() {
    let capture = capture(FirstPayloadState::Retained);
    let references = source_references(&capture);
    let mut builder = CaptureBundle::builder(capture);
    assert_eq!(
        builder.insert(references[0], b"other".to_vec()),
        Err(CaptureBundleError::DigestMismatch)
    );
    builder.insert(references[0], FIRST_BYTES.to_vec()).unwrap();
    builder
        .insert(references[1], SECOND_BYTES.to_vec())
        .unwrap();

    assert!(builder.finalize().is_ok());
}

#[test]
fn insertion_order_does_not_change_bundle_equality_or_lookup() {
    let first_capture = capture(FirstPayloadState::Retained);
    let references = source_references(&first_capture);
    let second_capture = wire_round_trip(&first_capture);
    let mut first = CaptureBundle::builder(first_capture);
    first.insert(references[0], FIRST_BYTES.to_vec()).unwrap();
    first.insert(references[1], SECOND_BYTES.to_vec()).unwrap();
    let mut second = CaptureBundle::builder(second_capture);
    second.insert(references[1], SECOND_BYTES.to_vec()).unwrap();
    second.insert(references[0], FIRST_BYTES.to_vec()).unwrap();

    let first = first.finalize().unwrap();
    let second = second.finalize().unwrap();
    assert_eq!(first, second);
    let borrowed = second
        .payloads()
        .map(|(reference, _)| reference)
        .collect::<Vec<_>>();
    assert_eq!(borrowed, references);
    let (_, owned) = second.into_parts();
    assert_eq!(
        owned
            .into_iter()
            .map(|(reference, _)| reference)
            .collect::<Vec<_>>(),
        references
    );
}

#[test]
fn web_capture_wire_round_trip_can_be_bound_to_payloads_offline() {
    let original = capture(FirstPayloadState::Retained);
    let decoded = wire_round_trip(&original);
    let references = source_references(&decoded);
    let mut builder = CaptureBundle::builder(decoded);
    builder.insert(references[0], FIRST_BYTES.to_vec()).unwrap();
    builder
        .insert(references[1], SECOND_BYTES.to_vec())
        .unwrap();

    let bundle = builder.finalize().unwrap();
    assert_eq!(bundle.payload(references[0]), Some(FIRST_BYTES));
}

#[test]
fn finalized_capture_without_retained_artifacts_needs_no_payloads() {
    let capture = empty_capture();
    let capture_id = capture.id();
    let bundle = CaptureBundle::builder(capture).finalize().unwrap();

    assert_eq!(bundle.capture().id(), capture_id);
}
