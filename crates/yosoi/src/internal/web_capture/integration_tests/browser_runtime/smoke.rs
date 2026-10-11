#![cfg(feature = "browser")]
#![allow(
    clippy::expect_used,
    clippy::panic,
    clippy::unwrap_used,
    reason = "accepted deterministic CAS-326 test fixture"
)]
use crate::internal::web_capture as internal_web_capture;
use std::{
    num::{NonZeroU32, NonZeroU64},
    time::Duration,
};
use tokio::time::timeout;

use super::fixture;
use crate::internal::types::{
    CaptureId, OperationId, Producer, ReasonCode, Schema, SchemaId, SchemaVersion,
};
use crate::internal::web_capture::*;
fn reason() -> ReasonCode {
    ReasonCode::new("test.unavailable").unwrap()
}
fn producer() -> Producer {
    void_crawl_adapter_producer().expect("linked VoidCrawl producer identity must be valid")
}
fn schema(name: &str) -> Schema {
    Schema::new(
        SchemaId::new(name).unwrap(),
        SchemaVersion::new(NonZeroU32::MIN),
    )
}
fn capabilities(
    mode: BrowserInstrumentationMode,
    network: bool,
    runtime: bool,
) -> Result<CertifiedBrowserCapabilities, BrowserCertificationError> {
    let yes = ArtifactCapability::Supported {
        multiplicity: ArtifactMultiplicity::ExactlyOne,
    };
    let profile = WebProviderCapabilityProfile::new(
        producer(),
        AcquisitionCapabilityProfile::DocumentNavigation(BrowserNavigationCapabilityProfile::new(
            BrowserMode::Headless,
        )),
        WebArtifactCapabilitySet::new(
            yes.clone(),
            yes.clone(),
            yes.clone(),
            yes.clone(),
            yes.clone(),
            ArtifactCapability::Unsupported { reason: reason() },
            yes.clone(),
            yes.clone(),
            yes,
        ),
    )
    .unwrap();
    let enabled = |yes| {
        if yes {
            BrowserCapabilityStatus::Supported
        } else {
            BrowserCapabilityStatus::Disabled { reason: reason() }
        }
    };
    CertifiedBrowserCapabilities::new(
        profile,
        &producer(),
        BrowserMode::Headless,
        mode,
        BrowserFamilyCapabilities::new(
            enabled(network),
            enabled(true),
            enabled(true),
            enabled(network),
            enabled(true),
            BrowserCapabilityStatus::Unsupported { reason: reason() },
            enabled(true),
            enabled(true),
            enabled(runtime),
        ),
    )
}

#[tokio::test]
async fn headless_loopback_facts_survive_teardown() {
    let fixture = fixture::BrowserFixture::start().await.unwrap();
    let target = fixture.url("/redirect").unwrap();
    let no = ArtifactRequest::NotRequested;
    let yes = ArtifactRequest::Required;
    let overrides = BrowserEnvironmentOverrides {
        viewport: Some(Viewport::new(
            NonZeroU32::new(1024).unwrap(),
            NonZeroU32::new(768).unwrap(),
        )),
        device_scale_factor: Some(DeviceScaleFactor::new("1.25").unwrap()),
        user_agent: Some(UserAgent::new("Yosoi-CAS-329-Smoke/1.0").unwrap()),
        locale: Some(Locale::new("en-US").unwrap()),
        time_zone: Some(TimeZone::new("UTC").unwrap()),
        color_scheme: Some(ColorScheme::Dark),
        reduced_motion: Some(ReducedMotion::Reduce),
    };
    let expected_overrides = overrides.clone();
    let capture_id = CaptureId::random();
    let spec = ResolvedBrowserCaptureSpec::new(
        WebCaptureRequest::new(
            capture_id,
            RequestedWebTarget::parse(&target).unwrap(),
            WebAcquisitionStrategy::DocumentNavigation(DocumentNavigationAcquisition::new(
                NavigationContext::FreshTopLevel,
            )),
        ),
        WebArtifactRequestSet::new(no, yes, yes, yes, no, no, yes, yes, yes),
        ObservationPolicy::new(
            ObservationLimits::new(CaptureDeadline::try_from(30_000_000).unwrap(), None, None),
            SettlementPolicy::Disabled,
        ),
        BrowserNavigationPolicy::new(NavigationCompletionPolicy::ControllerCompleted),
        BrowserAttemptEnvironment::with_overrides(BrowserMode::Headless, overrides),
        BrowserProviderBounds::new(
            vec![
                BrowserByteDomain::RenderedDomUtf8,
                BrowserByteDomain::AccessibilityJsonUtf8,
                BrowserByteDomain::ScreenshotPng,
                BrowserByteDomain::RuntimeDiagnosticUtf8,
            ]
            .into_iter()
            .map(|domain| {
                let budget_scope = if domain == BrowserByteDomain::RuntimeDiagnosticUtf8 {
                    BrowserBudgetScope::CaptureAggregate
                } else {
                    BrowserBudgetScope::PerPayload
                };
                BrowserByteBound::new(
                    domain,
                    NonZeroU64::new(1_000_000).unwrap(),
                    BrowserLimitEnforcement::RetentionAfterProviderMaterialization,
                    budget_scope,
                )
            })
            .collect(),
            NonZeroU64::new(10000).unwrap(),
            NonZeroU32::new(1000).unwrap(),
            NonZeroU32::new(10000).unwrap(),
        )
        .unwrap(),
        capabilities(BrowserInstrumentationMode::Normal, true, true).unwrap(),
        producer(),
        OperationId::new("test.capture").unwrap(),
        BrowserOutputSchemas::new(
            None,
            None,
            None,
            Some(schema("test.dom")),
            Some(schema("test.ax")),
            Some(schema("test.network")),
            None,
            None,
            Some(schema("test.layout")),
            Some(schema("test.visual")),
            Some(schema("test.runtime")),
        ),
        BrowserArtifactIdentityPlan::sequential(capture_id.activity_id()),
        BrowserEvidenceAdmissionPolicy::new(
            BrowserUrlAdmission::AdmitNetworkUrls,
            BrowserHeaderAdmission::Omit,
            BrowserMainBodyAdmission::Omit,
        ),
    )
    .unwrap();
    let captured = timeout(
        Duration::from_secs(45),
        internal_web_capture::browser_capture(&spec),
    )
    .await;
    let receipts = fixture.requests().await;
    let fixture_result = timeout(Duration::from_secs(5), fixture.shutdown()).await;
    assert!(fixture_result.is_ok(), "fixture shutdown timed out");
    fixture_result.unwrap().unwrap();
    let facts = captured.expect("browser capture timed out").unwrap();
    assert_eq!(facts.cleanup(), CleanupState::Complete);
    assert!(facts.navigation_completed());
    assert_eq!(facts.staging().slots().len(), 11);
    assert_eq!(
        facts.environment().mode().as_known(),
        Some(&BrowserMode::Headless)
    );
    let rendering = facts.environment().rendering();
    assert_eq!(
        rendering.viewport().as_known(),
        expected_overrides.viewport.as_ref()
    );
    assert_eq!(
        rendering.device_scale_factor().as_known(),
        expected_overrides.device_scale_factor.as_ref()
    );
    assert_eq!(
        rendering.user_agent().as_known(),
        expected_overrides.user_agent.as_ref()
    );
    assert_eq!(
        rendering.locale().as_known(),
        expected_overrides.locale.as_ref()
    );
    assert_eq!(
        rendering.time_zone().as_known(),
        expected_overrides.time_zone.as_ref()
    );
    assert_eq!(
        rendering.color_scheme().as_known(),
        expected_overrides.color_scheme.as_ref()
    );
    assert_eq!(
        rendering.reduced_motion().as_known(),
        expected_overrides.reduced_motion.as_ref()
    );
    assert_eq!(
        facts.spec().capabilities().instrumentation(),
        BrowserInstrumentationMode::Normal
    );
    assert!(
        facts
            .spec()
            .capabilities()
            .families()
            .get(WebArtifactFamily::Network)
            .is_some_and(BrowserCapabilityStatus::is_supported)
    );
    let mut document_scopes = Vec::new();
    for slot in facts.staging().slots() {
        let requested = matches!(
            slot.family(),
            BrowserStagingFamily::Artifact(
                WebArtifactFamily::RenderedDom
                    | WebArtifactFamily::AccessibilityTree
                    | WebArtifactFamily::Network
                    | WebArtifactFamily::Layout
                    | WebArtifactFamily::Visual
                    | WebArtifactFamily::RuntimeDiagnostics
            )
        );
        assert_eq!(
            slot.outcome().state() != StagingState::Unrequested,
            requested
        );
        match slot.family() {
            BrowserStagingFamily::Artifact(WebArtifactFamily::RenderedDom) => {
                assert_eq!(slot.outcome().state(), StagingState::Complete);
                assert_ne!(slot.outcome().bytes().expect("DOM bytes").len(), 0);
                let mapping = slot.outcome().mapping().expect("byte mapping");
                assert_eq!(mapping.layer(), BrowserByteLayer::RenderedDomUtf8);
                assert!(mapping.source_binding().is_none());
                document_scopes.push(mapping.snapshot().expect("document scope").scope);
            }
            BrowserStagingFamily::Artifact(WebArtifactFamily::AccessibilityTree) => {
                assert_eq!(slot.outcome().state(), StagingState::Complete);
                let BrowserStagingParts::Structured {
                    evidence: BrowserStructuredEvidence::Accessibility(accessibility),
                    ..
                } = slot.outcome().parts()
                else {
                    panic!("typed accessibility evidence");
                };
                assert_ne!(accessibility.canonical_node_bytes.len(), 0);
                assert!(slot.envelope().is_some());
                document_scopes.push(accessibility.scope);
            }
            BrowserStagingFamily::Artifact(WebArtifactFamily::Network) => {
                assert_eq!(slot.outcome().state(), StagingState::Complete);
                let BrowserStagingParts::Structured {
                    evidence:
                        BrowserStructuredEvidence::Network {
                            resources,
                            events,
                            resource_accounting,
                            event_accounting,
                            ..
                        },
                    ..
                } = slot.outcome().parts()
                else {
                    panic!("network must be structured");
                };
                assert_ne!(events.len(), 0, "ordered provider events are retained");
                assert!(resources.iter().all(|resource| resource.scope.is_none()));
                let (redirect, shell, secondary, favicon) = match resources.as_slice() {
                    [redirect, shell] => (redirect, shell, None, None),
                    [redirect, shell, secondary] => (redirect, shell, Some(secondary), None),
                    [redirect, shell, secondary, favicon] => {
                        (redirect, shell, Some(secondary), Some(favicon))
                    }
                    unexpected => panic!("unexpected resource sequence: {unexpected:#?}"),
                };
                assert!(
                    redirect
                        .url
                        .as_ref()
                        .unwrap()
                        .as_str()
                        .ends_with("/redirect")
                );
                assert_eq!(redirect.id, BrowserResourceId(0));
                assert_eq!(redirect.redirect_from, None);
                assert_eq!(redirect.status, Some(302));
                assert_eq!(redirect.outcome, BrowserResourceOutcome::Redirected);
                assert!(!redirect.from_cache && !redirect.from_service_worker);
                assert_eq!(redirect.encoded_data_length, None);
                assert!(shell.url.as_ref().unwrap().as_str().ends_with("/shell"));
                assert_eq!(shell.id, BrowserResourceId(1));
                assert_eq!(shell.redirect_from, Some(redirect.id));
                assert_eq!(shell.status, Some(200));
                assert_eq!(shell.outcome, BrowserResourceOutcome::Complete);
                assert!(!shell.from_cache && !shell.from_service_worker);
                assert_eq!(shell.encoded_data_length, Some(820));
                if let Some(secondary) = secondary {
                    assert!(
                        secondary
                            .url
                            .as_ref()
                            .unwrap()
                            .as_str()
                            .ends_with("/secondary")
                    );
                    assert_eq!(secondary.id, BrowserResourceId(2));
                    assert_eq!(secondary.redirect_from, None);
                    assert!(matches!(
                        secondary.outcome,
                        BrowserResourceOutcome::Pending
                            | BrowserResourceOutcome::ResponseReceived
                            | BrowserResourceOutcome::Complete
                    ));
                    assert!(!secondary.from_cache && !secondary.from_service_worker);
                }
                if let Some(favicon) = favicon {
                    assert!(
                        favicon
                            .url
                            .as_ref()
                            .unwrap()
                            .as_str()
                            .ends_with("/favicon.ico")
                    );
                    assert_eq!(favicon.id, BrowserResourceId(3));
                    assert_eq!(favicon.redirect_from, None);
                    assert_eq!(favicon.status, Some(404));
                    assert_eq!(favicon.outcome, BrowserResourceOutcome::Complete);
                    assert!(!favicon.from_cache && !favicon.from_service_worker);
                }
                let retained = u64::try_from(resources.len()).unwrap();
                assert_eq!(resource_accounting.retained(), retained);
                assert_eq!(resource_accounting.admitted(), retained);
                assert_eq!(resource_accounting.lost(), LossExtent::Known(0));
                assert!(event_accounting.admitted().get() >= retained);
                assert_eq!(
                    event_accounting.retained().get(),
                    u64::try_from(events.len()).unwrap()
                );
                assert!(
                    matches!(event_accounting.dropped(), MeasuredCount::Known(count) if count.get() == 0)
                );
            }
            BrowserStagingFamily::Artifact(WebArtifactFamily::Layout) => {
                assert_eq!(slot.outcome().state(), StagingState::Complete);
                let BrowserStagingParts::Structured {
                    evidence: BrowserStructuredEvidence::Layout(layout),
                    ..
                } = slot.outcome().parts()
                else {
                    panic!("layout must be structured");
                };
                document_scopes.push(layout.scope);
            }
            BrowserStagingFamily::Artifact(WebArtifactFamily::Visual) => {
                assert_eq!(slot.outcome().state(), StagingState::Complete);
                assert_eq!(
                    slot.outcome()
                        .bytes()
                        .map(|bytes| bytes.starts_with(b"\x89PNG\r\n\x1a\n")),
                    Some(true)
                );
                let snapshot = slot
                    .outcome()
                    .mapping()
                    .and_then(BrowserArtifactMapping::snapshot)
                    .expect("visual snapshot facts");
                let visual = snapshot.visual.expect("typed visual facts");
                assert!(visual.width_pixels > 0 && visual.height_pixels > 0);
                assert_eq!(
                    visual.layout_correlation,
                    BrowserVisualLayoutCorrelation::SameDocumentEpochOnly
                );
                assert!(visual.paired_layout_at.is_some());
                assert!(slot.envelope().is_some());
                document_scopes.push(visual.scope);
            }
            BrowserStagingFamily::Artifact(WebArtifactFamily::RuntimeDiagnostics) => {
                assert!(matches!(
                    slot.outcome().state(),
                    StagingState::Complete | StagingState::Partial
                ));
                let BrowserStagingParts::Structured {
                    evidence:
                        BrowserStructuredEvidence::RuntimeDiagnostics {
                            scope,
                            diagnostics,
                            runtime_event_accounting,
                            byte_accounting,
                        },
                    ..
                } = slot.outcome().parts()
                else {
                    panic!("runtime diagnostics must be structured");
                };
                assert_ne!(diagnostics.len(), 0);
                assert_eq!(
                    runtime_event_accounting.retained().get(),
                    u64::try_from(diagnostics.len()).unwrap()
                );
                assert!(byte_accounting.retained > 0);
                assert!(diagnostics.iter().all(
                    |diagnostic| diagnostic.value_type == BrowserRuntimeValueType::RedactedText
                ));
                assert!(slot.envelope().is_some());
                document_scopes.push(scope.expect("provider-observed runtime scope"));
            }
            BrowserStagingFamily::Artifact(
                WebArtifactFamily::Source
                | WebArtifactFamily::SourceRepresentation
                | WebArtifactFamily::DecodedSource
                | WebArtifactFamily::Cookies
                | WebArtifactFamily::Storage,
            )
            | BrowserStagingFamily::SourceRepresentation => {
                assert_eq!(slot.outcome().state(), StagingState::Unrequested);
                assert!(slot.outcome().bytes().is_none());
            }
        }
    }
    assert_eq!(document_scopes.len(), 5);
    assert!(document_scopes.windows(2).all(|pair| pair[0] == pair[1]));
    let scope = document_scopes.first().expect("one document scope");
    assert_ne!(scope.frame, BrowserFrameId(0));
    assert_ne!(scope.epoch, BrowserDocumentEpoch(0));
    assert_eq!(receipts.first().map(String::as_str), Some("/redirect"));
    assert_eq!(receipts.get(1).map(String::as_str), Some("/shell"));
    assert!(receipts.iter().all(|receipt| matches!(
        receipt.as_str(),
        "/redirect" | "/shell" | "/secondary" | "/favicon.ico"
    )));
    assert_ne!(format!("{facts:?}"), "");
}
