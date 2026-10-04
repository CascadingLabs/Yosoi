#![allow(clippy::unwrap_used, reason = "black-box fixtures")]
use std::{
    fs,
    num::{NonZeroU32, NonZeroU64},
    path::Path,
    sync::Arc,
};
use yosoi_types::{Producer, ProducerId, ProducerVersion, ReasonCode};
use yosoi_web_capture::*;

#[test]
fn terminal_uses_earliest_offset_and_precedence_only_for_ties() {
    let max = CaptureDeadline::try_from(100).unwrap();
    let candidates = [
        BrowserTerminalCandidate::new(
            CaptureOffset::from_microseconds(20),
            BrowserTerminalSignal::QuietSettled,
        ),
        BrowserTerminalCandidate::new(
            CaptureOffset::from_microseconds(30),
            BrowserTerminalSignal::SystemInterrupted {
                reason: reason("system"),
            },
        ),
    ];
    assert_eq!(
        resolve_browser_terminal(&candidates, max)
            .map(|terminal| (terminal.at(), terminal.kind().clone())),
        Some((
            CaptureOffset::from_microseconds(20),
            BrowserTerminalKind::QuietSettled
        ))
    );
    let tied = [
        BrowserTerminalCandidate::new(
            CaptureOffset::from_microseconds(20),
            BrowserTerminalSignal::QuietSettled,
        ),
        BrowserTerminalCandidate::new(
            CaptureOffset::from_microseconds(20),
            BrowserTerminalSignal::EventLimitReached,
        ),
    ];
    assert_eq!(
        resolve_browser_terminal(&tied, max)
            .map(|terminal| (terminal.at(), terminal.kind().clone())),
        Some((
            CaptureOffset::from_microseconds(20),
            BrowserTerminalKind::EventLimitReached
        ))
    );
}
#[test]
fn explicit_deadline_normalizes_but_earlier_stop_wins() {
    let max = CaptureDeadline::try_from(100).unwrap();
    let terminal = resolve_browser_terminal(
        &[
            BrowserTerminalCandidate::new(
                CaptureOffset::from_microseconds(1),
                BrowserTerminalSignal::DeadlineReached,
            ),
            BrowserTerminalCandidate::new(
                CaptureOffset::from_microseconds(20),
                BrowserTerminalSignal::CallerInterrupted {
                    reason: reason("cancelled"),
                },
            ),
        ],
        max,
    )
    .unwrap();
    assert_eq!(terminal.at(), CaptureOffset::from_microseconds(20));
    assert!(matches!(
        terminal.kind(),
        BrowserTerminalKind::CallerCancelled { .. }
    ));
}
#[test]
fn resource_accounting_is_exact_or_explicitly_unknown() {
    assert!(BrowserResourceAccounting::new(3, 2, LossExtent::Known(1)).is_ok());
    assert!(BrowserResourceAccounting::new(3, 2, LossExtent::Unknown).is_ok());
    assert_eq!(
        BrowserResourceAccounting::new(3, 2, LossExtent::Known(0)),
        Err(BrowserResourceAccountingError::KnownLossMismatch)
    );
    assert_eq!(
        BrowserResourceAccounting::new(1, 2, LossExtent::Unknown),
        Err(BrowserResourceAccountingError::RetainedExceedsAdmitted)
    );
}
#[test]
fn deadline_boundary_and_later_candidates_normalize_to_exact_deadline() {
    let max = CaptureDeadline::try_from(100).unwrap();
    for offset in [100, 101, u64::MAX] {
        assert_eq!(
            resolve_browser_terminal(
                &[BrowserTerminalCandidate::new(
                    CaptureOffset::from_microseconds(offset),
                    BrowserTerminalSignal::ControllerCompleted
                )],
                max
            )
            .map(|terminal| terminal.kind().clone()),
            Some(BrowserTerminalKind::DeadlineReached {
                at: CaptureOffset::from_microseconds(100)
            })
        );
    }
    assert_eq!(
        resolve_browser_terminal(
            &[BrowserTerminalCandidate::new(
                CaptureOffset::from_microseconds(1),
                BrowserTerminalSignal::NavigationCompleted
            )],
            max
        ),
        None
    );
}
#[test]
fn every_wrong_staging_mapping_is_rejected() {
    let cases = [
        (
            BrowserStagingFamily::Artifact(WebArtifactFamily::Source),
            BrowserByteLayer::RenderedDomUtf8,
        ),
        (
            BrowserStagingFamily::SourceRepresentation,
            BrowserByteLayer::DecodedResponseBody,
        ),
        (
            BrowserStagingFamily::Artifact(WebArtifactFamily::RenderedDom),
            BrowserByteLayer::Png,
        ),
        (
            BrowserStagingFamily::Artifact(WebArtifactFamily::AccessibilityTree),
            BrowserByteLayer::Png,
        ),
        (
            BrowserStagingFamily::Artifact(WebArtifactFamily::Layout),
            BrowserByteLayer::AccessibilityTreeUtf8,
        ),
        (
            BrowserStagingFamily::Artifact(WebArtifactFamily::Visual),
            BrowserByteLayer::RuntimeDiagnosticsUtf8,
        ),
        (
            BrowserStagingFamily::Artifact(WebArtifactFamily::RuntimeDiagnostics),
            BrowserByteLayer::Png,
        ),
    ];
    for (family, layer) in cases {
        assert_eq!(
            BrowserArtifactMapping::new(family, layer),
            Err(BrowserMappingError)
        );
    }
}
#[test]
fn staging_byte_and_loss_arithmetic_is_checked() {
    let mapping = BrowserArtifactMapping::new(
        BrowserStagingFamily::Artifact(WebArtifactFamily::Source),
        BrowserByteLayer::DecodedResponseBody,
    )
    .unwrap();
    let bytes: Arc<[u8]> = Arc::from(b"abc".as_slice());
    assert_eq!(
        ArtifactStagingOutcome::complete(mapping, bytes.clone(), 4),
        Err(StagingOutcomeError::CompleteLengthMismatch)
    );
    assert_eq!(
        ArtifactStagingOutcome::partial(
            mapping,
            bytes.clone(),
            5,
            LossExtent::Known(1),
            reason("partial")
        ),
        Err(StagingOutcomeError::LossMismatch)
    );
    assert_eq!(
        ArtifactStagingOutcome::truncated(
            mapping,
            bytes,
            3,
            LossExtent::Known(0),
            reason("truncated")
        ),
        Err(StagingOutcomeError::NoLoss)
    );
}

#[test]
fn canonical_acquired_payload_preserves_browser_source_state_and_accounting() {
    let source_mapping = BrowserArtifactMapping::new(
        BrowserStagingFamily::Artifact(WebArtifactFamily::Source),
        BrowserByteLayer::DecodedResponseBody,
    )
    .unwrap();
    let outcome = AcquiredPayloadOutcome::truncated(
        b"abc".to_vec(),
        ByteCount::new(5),
        MeasuredCount::Known(ByteCount::new(2)),
        reason("source-limit"),
    )
    .unwrap();
    let staged = ArtifactStagingOutcome::acquired_payload(source_mapping, outcome).unwrap();
    assert_eq!(staged.state(), StagingState::Truncated);
    assert_eq!(staged.bytes(), Some(b"abc".as_slice()));
    assert_eq!(staged.accounting().unwrap().lost(), LossExtent::Known(2));

    let rendered_mapping = BrowserArtifactMapping::new(
        BrowserStagingFamily::Artifact(WebArtifactFamily::RenderedDom),
        BrowserByteLayer::RenderedDomUtf8,
    )
    .unwrap();
    assert_eq!(
        ArtifactStagingOutcome::acquired_payload(
            rendered_mapping,
            AcquiredPayloadOutcome::complete(b"dom".to_vec()).unwrap(),
        ),
        Err(StagingOutcomeError::AcquiredPayloadMappingMismatch)
    );
}
#[test]
fn bounds_do_not_force_recording_or_structured_provider_bytes() {
    let bounds = BrowserProviderBounds::new(
        vec![BrowserByteBound::new(
            BrowserByteDomain::ScreenshotPng,
            NonZeroU64::MIN,
            BrowserLimitEnforcement::RetentionAfterProviderMaterialization,
            BrowserBudgetScope::PerPayload,
        )],
        NonZeroU64::MIN,
        NonZeroU32::MIN,
        NonZeroU32::MIN,
    )
    .unwrap();
    assert_eq!(bounds.byte_bounds().len(), 1);
    assert_eq!(
        bounds.byte_bounds()[0].domain(),
        BrowserByteDomain::ScreenshotPng
    );
}
#[test]
fn capability_categories_are_distinct() {
    let values = [
        BrowserCapabilityStatus::Supported,
        BrowserCapabilityStatus::Disabled {
            reason: reason("disabled"),
        },
        BrowserCapabilityStatus::Unavailable {
            reason: reason("unavailable"),
        },
        BrowserCapabilityStatus::Unsupported {
            reason: reason("unsupported"),
        },
    ];
    assert!(values[0].is_supported());
    for value in &values[1..] {
        assert!(!value.is_supported());
    }
}
#[test]
fn architecture_and_documentation_contract() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let doc =
        fs::read_to_string(root.join("../../docs/archive/cas-330-browser-adapter-contract.md")).unwrap();
    assert!(doc.contains("de1cee33-b090-43a0-ab72-a8ef6c32a296"));
    assert!(doc.contains("ba8a62f7-f9c3-451f-ba5a-1d350f54271d"));
    for relative in ["src/browser_spec.rs", "src/browser_adapter.rs"] {
        let source = fs::read_to_string(root.join(relative)).unwrap();
        for forbidden in [
            "void_crawl",
            "chromiumoxide",
            "CaptureBundleBuilder",
            "WebCaptureWire",
            "RecordingFrame",
            "EncodedRecording",
        ] {
            assert!(!source.contains(forbidden), "{relative}: {forbidden}");
        }
    }
}
fn reason(value: &str) -> ReasonCode {
    ReasonCode::new(format!("test.{value}")).unwrap()
}
#[allow(dead_code)]
fn producer() -> Producer {
    Producer::new(
        ProducerId::new("test.browser").unwrap(),
        ProducerVersion::new("1").unwrap(),
    )
}
