use super::*;
use crate::internal::types as internal_types;

#[test]
fn snapshot_bounds_and_all_byte_outcomes() {
    let scope = BrowserDocumentScope {
        frame: BrowserFrameId(1),
        epoch: BrowserDocumentEpoch(1),
    };
    for (family, layer, domain) in [
        (
            WebArtifactFamily::Source,
            BrowserByteLayer::DecodedResponseBody,
            BrowserByteDomain::CdpDecodedBody,
        ),
        (
            WebArtifactFamily::RenderedDom,
            BrowserByteLayer::RenderedDomUtf8,
            BrowserByteDomain::RenderedDomUtf8,
        ),
        (
            WebArtifactFamily::AccessibilityTree,
            BrowserByteLayer::AccessibilityTreeUtf8,
            BrowserByteDomain::AccessibilityJsonUtf8,
        ),
        (
            WebArtifactFamily::Visual,
            BrowserByteLayer::Png,
            BrowserByteDomain::ScreenshotPng,
        ),
        (
            WebArtifactFamily::RuntimeDiagnostics,
            BrowserByteLayer::RuntimeDiagnosticsUtf8,
            BrowserByteDomain::RuntimeDiagnosticUtf8,
        ),
    ] {
        let mapping =
            BrowserArtifactMapping::new(BrowserStagingFamily::Artifact(family), layer).unwrap();
        let mapping = match family {
            WebArtifactFamily::Source => mapping
                .with_snapshot(BrowserSnapshotObservation::source(
                    scope,
                    CaptureOffset::from_microseconds(10),
                ))
                .unwrap(),
            WebArtifactFamily::RenderedDom => mapping
                .with_snapshot(BrowserSnapshotObservation::rendered_dom(
                    scope,
                    CaptureOffset::from_microseconds(10),
                ))
                .unwrap(),
            WebArtifactFamily::AccessibilityTree => mapping
                .with_snapshot(BrowserSnapshotObservation::accessibility_tree(
                    scope,
                    CaptureOffset::from_microseconds(10),
                    10,
                ))
                .unwrap(),
            WebArtifactFamily::Visual => mapping
                .with_snapshot(BrowserSnapshotObservation::visual(
                    scope,
                    CaptureOffset::from_microseconds(10),
                ))
                .unwrap(),
            WebArtifactFamily::RuntimeDiagnostics
            | WebArtifactFamily::SourceRepresentation
            | WebArtifactFamily::DecodedSource
            | WebArtifactFamily::Network
            | WebArtifactFamily::Cookies
            | WebArtifactFamily::Storage
            | WebArtifactFamily::Layout => mapping,
        };
        let bytes: Arc<[u8]> = Arc::from(b"abc".as_slice());
        for outcome in [
            ArtifactStagingOutcome::complete(mapping, bytes.clone(), 3).unwrap(),
            ArtifactStagingOutcome::partial(
                mapping,
                bytes.clone(),
                3,
                LossExtent::Unknown,
                reason(),
            )
            .unwrap(),
            ArtifactStagingOutcome::truncated(
                mapping,
                bytes.clone(),
                5,
                LossExtent::Known(2),
                reason(),
            )
            .unwrap(),
            ArtifactStagingOutcome::discarded(domain, LossExtent::Known(5), reason()),
        ] {
            for request in [ArtifactRequest::Optional, ArtifactRequest::Required] {
                let spec = spec(family, request, true, None, SettlementPolicy::Disabled).unwrap();
                let envelope_required = outcome.bytes().is_some();
                assert_eq!(
                    facts(spec, staging(family, outcome.clone()), 20).is_ok(),
                    !envelope_required && outcome.state() != StagingState::Discarded
                );
            }
        }
        let too_large =
            ArtifactStagingOutcome::complete(mapping, Arc::from(vec![0; 101]), 101).unwrap();
        assert!(
            facts(
                spec(
                    family,
                    ArtifactRequest::Required,
                    true,
                    None,
                    SettlementPolicy::Disabled
                )
                .unwrap(),
                staging(family, too_large),
                20
            )
            .is_err()
        );
    }
    for (nodes, configured_limit, valid) in [(10, 100, true), (11, 100, false), (10, 99, false)] {
        let family = WebArtifactFamily::AccessibilityTree;
        let spec = spec(
            family,
            ArtifactRequest::Required,
            true,
            None,
            SettlementPolicy::Disabled,
        )
        .unwrap();
        let evidence = BrowserStructuredEvidence::Accessibility(BrowserAccessibilityEvidence {
            schema: BrowserAccessibilitySchema::ChromiumCdpAxNodeJson,
            schema_version: 1,
            capture_mode: BrowserAccessibilityCaptureMode::FullTree,
            requested_depth: None,
            ignored_nodes: BrowserAccessibilityIgnoredNodes::Included,
            scope,
            at: CaptureOffset::from_microseconds(10),
            nodes_observed: nodes,
            nodes_retained: nodes,
            nodes_lost: LossExtent::Known(0),
            bytes: BrowserByteAccounting {
                configured_limit,
                enforcement: BrowserLimitEnforcement::RetentionAfterProviderMaterialization,
                budget_scope: BrowserBudgetScope::PerPayload,
                observed: 3,
                retained: 3,
                lost: LossExtent::Known(0),
                complete: true,
            },
            canonical_node_bytes: b"abc".to_vec(),
        });
        let envelope_bytes = evidence.to_canonical_json().unwrap();
        let outcome = ArtifactStagingOutcome::structured(evidence, None).unwrap();
        let envelope = StagedBrowserArtifactEnvelope::new(
            spec.identity_plan()
                .reference(BrowserStagingFamily::Artifact(family))
                .unwrap(),
            spec.output_schemas().get(family).unwrap().clone(),
            spec.producer().clone(),
            MediaType::new("application/json").unwrap(),
            internal_types::Sha256Digest::digest(&envelope_bytes),
            ArtifactByteExtent::Complete {
                retained_bytes: ByteCount::new(u64::try_from(envelope_bytes.len()).unwrap()),
            },
            ArtifactSensitivity::Sensitive,
            CaptureOffset::from_microseconds(10),
            Arc::from(envelope_bytes),
            Vec::new(),
        )
        .unwrap();
        let [
            source,
            representation,
            decoded_source,
            dom,
            _ax,
            network,
            cookies,
            storage,
            layout,
            visual,
            runtime,
        ] = staging(family, outcome.clone()).into_parts();
        let ax = BrowserStagingSlot::new(BrowserStagingFamily::Artifact(family), outcome)
            .unwrap()
            .with_envelope(envelope)
            .unwrap();
        let staged = BrowserArtifactStaging::new(
            source,
            representation,
            dom,
            ax,
            network,
            cookies,
            storage,
            layout,
            visual,
            runtime,
        )
        .unwrap()
        .with_decoded_source(decoded_source)
        .unwrap();
        assert_eq!(facts(spec, staged, 20).is_ok(), valid);
    }
}
#[test]
fn source_interpretation_requires_validated_envelopes() {
    let source_mapping = BrowserArtifactMapping::new(
        BrowserStagingFamily::Artifact(WebArtifactFamily::Source),
        BrowserByteLayer::DecodedResponseBody,
    )
    .unwrap()
    .with_snapshot(BrowserSnapshotObservation::source(
        BrowserDocumentScope {
            frame: BrowserFrameId(1),
            epoch: BrowserDocumentEpoch(1),
        },
        CaptureOffset::from_microseconds(10),
    ))
    .unwrap();
    let source =
        ArtifactStagingOutcome::complete(source_mapping, Arc::from(b"abc".as_slice()), 3).unwrap();
    for binding in [None, Some(b"abc".as_slice()), Some(b"xyz".as_slice())] {
        let base = BrowserArtifactMapping::new(
            BrowserStagingFamily::SourceRepresentation,
            BrowserByteLayer::SourceRepresentation,
        )
        .unwrap();
        let mapping = binding.map_or(base, |bytes| base.derived_from_source(bytes));
        let representation = BrowserStagingSlot::new(
            BrowserStagingFamily::SourceRepresentation,
            ArtifactStagingOutcome::complete(mapping, Arc::from(b"{}".as_slice()), 2).unwrap(),
        )
        .unwrap();
        let [
            source,
            _,
            decoded_source,
            dom,
            ax,
            network,
            cookies,
            storage,
            layout,
            visual,
            runtime,
        ] = staging(WebArtifactFamily::Source, source.clone()).into_parts();
        let staged = BrowserArtifactStaging::new(
            source,
            representation,
            dom,
            ax,
            network,
            cookies,
            storage,
            layout,
            visual,
            runtime,
        )
        .unwrap()
        .with_decoded_source(decoded_source)
        .unwrap();
        let facts = facts(
            spec(
                WebArtifactFamily::Source,
                ArtifactRequest::Required,
                true,
                None,
                SettlementPolicy::Disabled,
            )
            .unwrap(),
            staged,
            20,
        );
        assert!(
            facts.is_err(),
            "loose source bytes without validated envelopes must be rejected"
        );
    }
}
#[test]
fn cleanup_failure_does_not_overwrite_earlier_stop() {
    let spec = spec(
        WebArtifactFamily::Visual,
        ArtifactRequest::NotRequested,
        false,
        None,
        SettlementPolicy::Disabled,
    )
    .unwrap();
    let staging = staging(
        WebArtifactFamily::Visual,
        ArtifactStagingOutcome::unrequested(),
    );
    let at = CaptureOffset::from_microseconds(20);
    let events = EventAccounting::new(
        EventCount::new(0),
        EventCount::new(0),
        MeasuredCount::Known(EventCount::new(0)),
    )
    .unwrap();
    for cleanup in [CleanupState::Complete, CleanupState::Failed] {
        let facts = BrowserAdapterFacts::new(
            at,
            staging.clone(),
            environment(),
            spec.clone(),
            events.clone(),
            InFlightActivity::new(ActivityCount::new(0), ActivityCount::new(0)).unwrap(),
            true,
            None,
            cleanup,
            BrowserChallengeFact::unavailable(
                BrowserResponseSignalUnavailableReason::NavigationNotCollected,
            ),
        )
        .unwrap();
        for signal in [
            BrowserTerminalSignal::EventLimitReached,
            BrowserTerminalSignal::CleanupFailed,
        ] {
            let terminal = resolve_browser_terminal(
                &[BrowserTerminalCandidate::new(at, signal.clone())],
                CaptureDeadline::try_from(100).unwrap(),
            )
            .unwrap();
            assert_eq!(
                BrowserAdapterResult::stopped(terminal, facts.clone()).is_ok(),
                signal != BrowserTerminalSignal::CleanupFailed || cleanup == CleanupState::Failed
            );
        }
    }
}
