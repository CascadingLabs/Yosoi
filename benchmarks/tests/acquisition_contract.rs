//! Characterization of acquisition contracts shared by HTTP and browser capture.

#![allow(
    clippy::panic,
    reason = "test harness reports invalid committed setup immediately"
)]

use std::sync::Arc;

use proptest::prelude::*;
use yosoi_benchmarks::finalization_support::{FinalizationCase, plan, plan_generated_at};
use yosoi_dev_support::internal::browser::{
    BrowserByteAccounting as ProviderByteAccounting, MeasuredBrowserBytes,
};
use yosoi_dev_support::internal::direct_http::BodyTerminal;
use yosoi_dev_support::internal::types::ActivityOutcome;
use yosoi_dev_support::internal::types::Sha256Digest;
use yosoi_dev_support::internal::web_capture::{
    AcquiredPayloadOutcome, AcquiredPayloadState, AcquisitionActivityResult,
    AcquisitionFinalizationError, AcquisitionObservationError, ArtifactStagingOutcome,
    BoundedAcquisitionLifecycle, BrowserArtifactMapping, BrowserByteLayer, BrowserStagingFamily,
    BrowserStagingParts, ByteAccounting, ByteCount, ByteLimit, LifecycleEvent, LossExtent,
    MeasuredCount, ObservationLimits, ObservationPolicy, RetainedSource, RetainedSourceExtent,
    SettlementPolicy, StagingState, WebArtifactFamily, finalize_acquisition,
};

fn source_mapping() -> BrowserArtifactMapping {
    BrowserArtifactMapping::new(
        BrowserStagingFamily::Artifact(WebArtifactFamily::Source),
        BrowserByteLayer::DecodedResponseBody,
    )
    .unwrap_or_else(|error| panic!("source mapping: {error}"))
}

#[test]
fn complete_source_payload_has_the_same_bytes_digest_and_extent_across_boundaries() {
    let bytes = b"<main>shared acquisition payload</main>".to_vec();
    let digest = Sha256Digest::digest(&bytes);

    let direct = AcquiredPayloadOutcome::complete(bytes.clone())
        .unwrap_or_else(|error| panic!("direct payload: {error}"));
    let common = RetainedSource::complete(bytes.clone());
    let browser = ArtifactStagingOutcome::complete(
        source_mapping(),
        Arc::from(bytes.clone()),
        u64::try_from(bytes.len()).unwrap_or_else(|error| panic!("payload length: {error}")),
    )
    .unwrap_or_else(|error| panic!("browser staging: {error}"));

    let direct_source = direct
        .retained_source()
        .unwrap_or_else(|| panic!("complete payload retains its source"));
    assert_eq!(direct_source.bytes(), bytes);
    assert_eq!(direct_source.digest(), digest);
    assert_eq!(direct_source.extent(), RetainedSourceExtent::Complete);
    assert_eq!(common.bytes(), bytes);
    assert_eq!(common.digest(), digest);
    assert_eq!(common.extent(), RetainedSourceExtent::Complete);
    assert_eq!(browser.state(), StagingState::Complete);
    assert_eq!(browser.bytes(), Some(bytes.as_slice()));
    assert!(matches!(
        browser.parts(),
        BrowserStagingParts::Complete { observed, .. }
            if *observed == u64::try_from(bytes.len()).unwrap_or(u64::MAX)
    ));
}

#[test]
fn accounting_wire_shapes_are_locked_before_unification() {
    let common = ByteAccounting::new(
        ByteCount::new(13),
        ByteCount::new(8),
        MeasuredCount::Known(ByteCount::new(5)),
    )
    .unwrap_or_else(|error| panic!("common accounting: {error}"));
    let provider = ProviderByteAccounting::new(
        ByteCount::new(13),
        ByteCount::new(8),
        MeasuredBrowserBytes::Known {
            value: ByteCount::new(5),
        },
    )
    .unwrap_or_else(|error| panic!("provider accounting: {error}"));

    assert_eq!(
        serde_json::to_string(&common).unwrap_or_else(|error| panic!("common JSON: {error}")),
        r#"{"admitted":13,"retained":8,"dropped":{"status":"known","value":5}}"#
    );
    assert_eq!(
        serde_json::to_string(&provider).unwrap_or_else(|error| panic!("provider JSON: {error}")),
        r#"{"observed":13,"retained":8,"discarded":{"status":"known","value":5}}"#
    );
}

proptest! {
    #[test]
    fn exact_byte_accounting_enforces_the_same_invariant(
        observed in any::<u64>(),
        retained in any::<u64>(),
        discarded in any::<u64>(),
    ) {
        let common = ByteAccounting::new(
            ByteCount::new(observed),
            ByteCount::new(retained),
            MeasuredCount::Known(ByteCount::new(discarded)),
        );
        let provider = ProviderByteAccounting::new(
            ByteCount::new(observed),
            ByteCount::new(retained),
            MeasuredBrowserBytes::Known { value: ByteCount::new(discarded) },
        );
        let valid = retained <= observed && retained.checked_add(discarded) == Some(observed);
        prop_assert_eq!(common.is_ok(), valid);
        prop_assert_eq!(provider.is_ok(), valid);
        prop_assert_eq!(common.is_ok(), provider.is_ok());
    }

    #[test]
    fn truncated_browser_payload_accepts_exactly_explained_loss(
        retained in 0_u64..1_000_000,
        lost in 1_u64..1_000_000,
    ) {
        let observed = retained.checked_add(lost)
            .unwrap_or_else(|| panic!("bounded generator cannot overflow"));
        let retained_len = usize::try_from(retained)
            .unwrap_or_else(|error| panic!("bounded retained length: {error}"));
        let outcome = ArtifactStagingOutcome::truncated(
            source_mapping(),
            Arc::from(vec![b'x'; retained_len]),
            observed,
            LossExtent::Known(lost),
            "characterization.byte-limit".parse()
                .unwrap_or_else(|error| panic!("reason: {error}")),
        );
        prop_assert!(outcome.is_ok());
    }
}

#[test]
fn direct_complete_outcome_remains_distinct_from_transport_metadata() {
    let payload = AcquiredPayloadOutcome::complete(b"complete".to_vec())
        .unwrap_or_else(|error| panic!("complete payload: {error}"));
    assert!(matches!(payload.state(), AcquiredPayloadState::Complete(_)));
    let transport_terminal = BodyTerminal::Complete;
    let content_coded_bytes = 0_u64;
    assert_eq!(content_coded_bytes, 0);
    assert_eq!(transport_terminal, BodyTerminal::Complete);
}

#[test]
fn shared_finalizer_publishes_minimal_complete_and_truncated_plans() {
    for case in [
        FinalizationCase::Minimal,
        FinalizationCase::Complete,
        FinalizationCase::Truncated,
    ] {
        let bundle = finalize_acquisition(plan(case))
            .unwrap_or_else(|error| panic!("finalize {case:?}: {error}"));
        assert_eq!(
            bundle
                .capture()
                .artifacts()
                .results()
                .source()
                .is_not_requested(),
            case == FinalizationCase::Minimal
        );
        assert_eq!(
            bundle.payloads().count(),
            usize::from(case != FinalizationCase::Minimal)
        );
    }
}

#[test]
fn shared_finalizer_rejects_missing_payload_without_publishing_a_bundle() {
    let mut invalid = plan(FinalizationCase::Complete);
    invalid.payloads.clear();
    let error = finalize_acquisition(invalid)
        .expect_err("an artifact without its retained payload must not publish");
    assert!(matches!(error, AcquisitionFinalizationError::Bundle(_)));
}

#[test]
fn shared_finalizer_rejects_an_outcome_that_contradicts_termination() {
    let mut invalid = plan(FinalizationCase::Minimal);
    invalid.activity_result = Some(AcquisitionActivityResult::new(
        ActivityOutcome::Failed,
        None,
    ));
    let error =
        finalize_acquisition(invalid).expect_err("settled acquisition must not publish as failed");
    assert!(matches!(
        error,
        AcquisitionFinalizationError::ActivityOutcomeMismatch
    ));
}

#[test]
fn shared_finalizer_rejects_artifacts_outside_the_attempt_window() {
    let started_at = chrono::DateTime::from_timestamp(1_700_000_000, 0)
        .unwrap_or_else(|| panic!("valid fixed timestamp"));
    let generated_at = started_at - chrono::TimeDelta::microseconds(1);
    let error = finalize_acquisition(plan_generated_at(
        FinalizationCase::Complete,
        started_at,
        generated_at,
    ))
    .expect_err("pre-attempt artifact timestamp must fail");
    assert!(matches!(
        error,
        AcquisitionFinalizationError::ArtifactTimestampOutsideWindow
    ));
}

#[test]
fn shared_finalizer_rejects_accounting_that_contradicts_a_stopped_lifecycle() {
    let mut invalid = plan(FinalizationCase::Minimal);
    let limit =
        ByteLimit::try_from(10_u64).unwrap_or_else(|error| panic!("positive byte limit: {error}"));
    let observation_policy = ObservationPolicy::new(
        ObservationLimits::new(
            invalid.lifecycle.observation().limits().maximum_elapsed(),
            None,
            Some(limit),
        ),
        SettlementPolicy::Disabled,
    );
    invalid.lifecycle = BoundedAcquisitionLifecycle::start(
        invalid.lifecycle.capture_id(),
        observation_policy,
        invalid.lifecycle.started_at(),
    );
    invalid
        .lifecycle
        .admit(
            LifecycleEvent::new(
                invalid.terminal_offset,
                ByteCount::new(10),
                ByteCount::new(9),
                true,
            )
            .unwrap_or_else(|error| panic!("terminal event: {error}")),
        )
        .unwrap_or_else(|error| panic!("terminal admission: {error}"));
    invalid.bytes = ByteAccounting::new(
        ByteCount::new(9),
        ByteCount::new(9),
        MeasuredCount::Known(ByteCount::new(0)),
    )
    .unwrap_or_else(|error| panic!("internally valid accounting: {error}"));
    let error =
        finalize_acquisition(invalid).expect_err("stopped lifecycle accounting mismatch must fail");
    assert!(matches!(
        error,
        AcquisitionFinalizationError::Lifecycle(
            AcquisitionObservationError::StoppedAccountingMismatch
        )
    ));
}
