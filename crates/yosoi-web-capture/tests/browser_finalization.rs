#![allow(clippy::unwrap_used, reason = "deterministic CAS-332 fixtures")]
use std::num::{NonZeroU32, NonZeroU64};
use std::sync::Arc;
use yosoi_types::{
    CaptureId, OperationId, Producer, ProducerId, ProducerVersion, ReasonCode, Schema, SchemaId,
    SchemaVersion, Sha256Digest,
};
use yosoi_web_capture::*;
const FAMILIES: [WebArtifactFamily; 9] = [
    WebArtifactFamily::Source,
    WebArtifactFamily::RenderedDom,
    WebArtifactFamily::AccessibilityTree,
    WebArtifactFamily::Network,
    WebArtifactFamily::Cookies,
    WebArtifactFamily::Storage,
    WebArtifactFamily::Layout,
    WebArtifactFamily::Visual,
    WebArtifactFamily::RuntimeDiagnostics,
];
fn reason() -> ReasonCode {
    ReasonCode::new("test.unavailable").unwrap()
}
fn producer() -> Producer {
    Producer::new(
        ProducerId::new("test.browser").unwrap(),
        ProducerVersion::new("1").unwrap(),
    )
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
fn bounds(
    _family: WebArtifactFamily,
    request: ArtifactRequest,
    omit: Option<BrowserByteDomain>,
) -> BrowserProviderBounds {
    BrowserProviderBounds::new(
        [
            BrowserByteDomain::CdpDecodedBody,
            BrowserByteDomain::DecodedSourceUtf8,
            BrowserByteDomain::RenderedDomUtf8,
            BrowserByteDomain::AccessibilityJsonUtf8,
            BrowserByteDomain::RuntimeDiagnosticUtf8,
            BrowserByteDomain::ScreenshotPng,
        ]
        .into_iter()
        .filter(|domain| request != ArtifactRequest::NotRequested && Some(*domain) != omit)
        .map(|domain| {
            BrowserByteBound::new(
                domain,
                NonZeroU64::new(10_000).unwrap(),
                BrowserLimitEnforcement::RetentionAfterProviderMaterialization,
                BrowserBudgetScope::PerPayload,
            )
        })
        .collect(),
        NonZeroU64::new(10).unwrap(),
        NonZeroU32::new(10).unwrap(),
        NonZeroU32::new(10).unwrap(),
    )
    .unwrap()
}
fn spec(
    family: WebArtifactFamily,
    request: ArtifactRequest,
    has_schema: bool,
    omit: Option<BrowserByteDomain>,
    settlement: SettlementPolicy,
) -> Result<ResolvedBrowserCaptureSpec, BrowserCaptureSpecError> {
    let capture_id = CaptureId::random();
    let r = |f| {
        if matches!(f, WebArtifactFamily::Cookies | WebArtifactFamily::Storage) {
            ArtifactRequest::NotRequested
        } else {
            request
        }
    };
    let s = |f| {
        if has_schema && !matches!(f, WebArtifactFamily::Cookies | WebArtifactFamily::Storage) {
            Some(schema("test.output"))
        } else {
            None
        }
    };
    ResolvedBrowserCaptureSpec::new(
        WebCaptureRequest::new(
            capture_id,
            RequestedWebTarget::parse("https://example.test/").unwrap(),
            WebAcquisitionStrategy::DocumentNavigation(DocumentNavigationAcquisition::new(
                NavigationContext::FreshTopLevel,
            )),
        ),
        WebArtifactRequestSet::new(
            r(FAMILIES[0]),
            r(FAMILIES[1]),
            r(FAMILIES[2]),
            r(FAMILIES[3]),
            r(FAMILIES[4]),
            r(FAMILIES[5]),
            r(FAMILIES[6]),
            r(FAMILIES[7]),
            r(FAMILIES[8]),
        ),
        ObservationPolicy::new(
            ObservationLimits::new(CaptureDeadline::try_from(100).unwrap(), None, None),
            settlement,
        ),
        BrowserNavigationPolicy::new(NavigationCompletionPolicy::LoadEvent),
        BrowserAttemptEnvironment::new(BrowserMode::Headless),
        bounds(family, request, omit),
        capabilities(BrowserInstrumentationMode::Normal, true, true).unwrap(),
        producer(),
        OperationId::new("test.capture").unwrap(),
        BrowserOutputSchemas::new(
            s(FAMILIES[0]),
            if family == WebArtifactFamily::Source && has_schema {
                Some(schema("test.representation"))
            } else {
                None
            },
            if family == WebArtifactFamily::Source && has_schema {
                Some(schema("test.decoded-source"))
            } else {
                None
            },
            s(FAMILIES[1]),
            s(FAMILIES[2]),
            s(FAMILIES[3]),
            s(FAMILIES[4]),
            s(FAMILIES[5]),
            s(FAMILIES[6]),
            s(FAMILIES[7]),
            s(FAMILIES[8]),
        ),
        BrowserArtifactIdentityPlan::sequential(capture_id.activity_id()),
        BrowserEvidenceAdmissionPolicy::new(
            BrowserUrlAdmission::Omit,
            BrowserHeaderAdmission::Omit,
            BrowserMainBodyAdmission::Omit,
        ),
    )
}
#[allow(
    dead_code,
    clippy::needless_pass_by_value,
    reason = "copied provider-neutral fixture constructor"
)]
fn staging(family: WebArtifactFamily, outcome: ArtifactStagingOutcome) -> BrowserArtifactStaging {
    let slot = |f| {
        BrowserStagingSlot::new(
            BrowserStagingFamily::Artifact(f),
            if f == family {
                outcome.clone()
            } else {
                ArtifactStagingOutcome::unrequested()
            },
        )
        .unwrap()
    };
    BrowserArtifactStaging::new(
        slot(FAMILIES[0]),
        BrowserStagingSlot::new(
            BrowserStagingFamily::SourceRepresentation,
            if family == WebArtifactFamily::Source && outcome.state() != StagingState::Unrequested {
                ArtifactStagingOutcome::unavailable(reason())
            } else {
                ArtifactStagingOutcome::unrequested()
            },
        )
        .unwrap(),
        slot(FAMILIES[1]),
        slot(FAMILIES[2]),
        slot(FAMILIES[3]),
        slot(FAMILIES[4]),
        slot(FAMILIES[5]),
        slot(FAMILIES[6]),
        slot(FAMILIES[7]),
        slot(FAMILIES[8]),
    )
    .unwrap()
}
fn environment() -> BrowserCaptureEnvironment {
    BrowserCaptureEnvironment::new(
        producer(),
        producer(),
        EnvironmentValue::Known {
            value: BrowserMode::Headless,
        },
        BrowserRenderingContext::new(
            EnvironmentValue::Unavailable { reason: reason() },
            EnvironmentValue::Unavailable { reason: reason() },
            EnvironmentValue::Unavailable { reason: reason() },
            EnvironmentValue::Unavailable { reason: reason() },
            EnvironmentValue::Unavailable { reason: reason() },
            EnvironmentValue::Unavailable { reason: reason() },
            EnvironmentValue::Unavailable { reason: reason() },
        ),
    )
}
fn facts(
    spec: ResolvedBrowserCaptureSpec,
    staging: BrowserArtifactStaging,
    at: u64,
) -> Result<BrowserAdapterFacts, BrowserAdapterOutputError> {
    BrowserAdapterFacts::new(
        CaptureOffset::from_microseconds(at),
        staging,
        environment(),
        spec,
        EventAccounting::new(
            EventCount::new(0),
            EventCount::new(0),
            MeasuredCount::Known(EventCount::new(0)),
        )
        .unwrap(),
        InFlightActivity::new(ActivityCount::new(0), ActivityCount::new(0)).unwrap(),
        true,
        None,
        CleanupState::Complete,
        BrowserChallengeFact::unavailable(
            BrowserResponseSignalUnavailableReason::NavigationNotCollected,
        ),
    )
}

use chrono::{TimeDelta, Utc};
use serde::{Deserialize, Serialize};
use std::{
    env, fs,
    path::{Path, PathBuf},
    process::{Command, Stdio, id as process_id},
    time::{SystemTime, UNIX_EPOCH},
};

const SOURCE: &[u8] = b"<!doctype html><title>fixture</title>";
const DOM: &[u8] = b"<html><head><title>fixture</title></head><body></body></html>";
const PNG: &[u8] = b"\x89PNG\r\n\x1a\nfixture";
const AT: CaptureOffset = CaptureOffset::from_microseconds(10);
const END: CaptureOffset = CaptureOffset::from_microseconds(20);

const fn scope() -> BrowserDocumentScope {
    BrowserDocumentScope {
        frame: BrowserFrameId(7),
        epoch: BrowserDocumentEpoch(3),
    }
}
fn byte_len(bytes: &[u8]) -> u64 {
    u64::try_from(bytes.len()).unwrap()
}

fn mapping(
    family: WebArtifactFamily,
    layer: BrowserByteLayer,
    snapshot: BrowserSnapshotObservation,
) -> BrowserArtifactMapping {
    BrowserArtifactMapping::new(BrowserStagingFamily::Artifact(family), layer)
        .unwrap()
        .with_snapshot(snapshot)
        .unwrap()
}
fn envelope(
    spec: &ResolvedBrowserCaptureSpec,
    family: BrowserStagingFamily,
    bytes: Vec<u8>,
    media: &str,
    derived: Vec<yosoi_types::ArtifactRef>,
    extent: ArtifactByteExtent,
) -> StagedBrowserArtifactEnvelope {
    StagedBrowserArtifactEnvelope::new(
        spec.identity_plan().reference(family).unwrap(),
        match family {
            BrowserStagingFamily::SourceRepresentation => spec
                .output_schemas()
                .source_representation()
                .unwrap()
                .clone(),
            BrowserStagingFamily::Artifact(family) => {
                spec.output_schemas().get(family).unwrap().clone()
            }
        },
        match family {
            BrowserStagingFamily::Artifact(WebArtifactFamily::DecodedSource) => {
                source_decoder_producer().unwrap()
            }
            BrowserStagingFamily::Artifact(_) | BrowserStagingFamily::SourceRepresentation => {
                spec.producer().clone()
            }
        },
        MediaType::new(media).unwrap(),
        yosoi_types::Sha256Digest::digest(&bytes),
        extent,
        ArtifactSensitivity::Sensitive,
        AT,
        Arc::from(bytes),
        derived,
    )
    .unwrap()
}
fn raw_slot(
    spec: &ResolvedBrowserCaptureSpec,
    family: WebArtifactFamily,
    layer: BrowserByteLayer,
    snapshot: BrowserSnapshotObservation,
    bytes: &[u8],
) -> BrowserStagingSlot {
    let map = mapping(family, layer, snapshot);
    let outcome = ArtifactStagingOutcome::complete(map, Arc::from(bytes), byte_len(bytes)).unwrap();
    let env = envelope(
        spec,
        BrowserStagingFamily::Artifact(family),
        bytes.to_vec(),
        if family == WebArtifactFamily::Visual {
            "image/png"
        } else {
            "text/html"
        },
        Vec::new(),
        ArtifactByteExtent::Complete {
            retained_bytes: ByteCount::new(byte_len(bytes)),
        },
    );
    BrowserStagingSlot::new(BrowserStagingFamily::Artifact(family), outcome)
        .unwrap()
        .with_envelope(env)
        .unwrap()
}
fn structured_slot(
    spec: &ResolvedBrowserCaptureSpec,
    evidence: BrowserStructuredEvidence,
) -> BrowserStagingSlot {
    let family = evidence.family();
    let bytes = evidence.to_canonical_json().unwrap();
    let outcome = ArtifactStagingOutcome::structured(evidence, None).unwrap();
    let env = envelope(
        spec,
        BrowserStagingFamily::Artifact(family),
        bytes.clone(),
        "application/json",
        Vec::new(),
        ArtifactByteExtent::Complete {
            retained_bytes: ByteCount::new(byte_len(&bytes)),
        },
    );
    BrowserStagingSlot::new(BrowserStagingFamily::Artifact(family), outcome)
        .unwrap()
        .with_envelope(env)
        .unwrap()
}
fn evidence() -> [BrowserStructuredEvidence; 4] {
    let zero_events = || {
        EventAccounting::new(
            EventCount::new(0),
            EventCount::new(0),
            MeasuredCount::Known(EventCount::new(0)),
        )
        .unwrap()
    };
    let rect = BrowserLayoutRect {
        x_micro_css: 0,
        y_micro_css: 0,
        width_micro_css: 800_000_000,
        height_micro_css: 600_000_000,
    };
    [
        BrowserStructuredEvidence::Accessibility(BrowserAccessibilityEvidence {
            schema: BrowserAccessibilitySchema::ChromiumCdpAxNodeJson,
            schema_version: 1,
            capture_mode: BrowserAccessibilityCaptureMode::FullTree,
            requested_depth: None,
            ignored_nodes: BrowserAccessibilityIgnoredNodes::Included,
            scope: scope(),
            at: AT,
            nodes_observed: 1,
            nodes_retained: 1,
            nodes_lost: LossExtent::Known(0),
            bytes: BrowserByteAccounting {
                configured_limit: 10_000,
                enforcement: BrowserLimitEnforcement::RetentionAfterProviderMaterialization,
                budget_scope: BrowserBudgetScope::PerPayload,
                observed: 2,
                retained: 2,
                lost: LossExtent::Known(0),
                complete: true,
            },
            canonical_node_bytes: b"[]".to_vec(),
        }),
        BrowserStructuredEvidence::Network {
            requested_url: None,
            final_url: None,
            redirects: Vec::new(),
            main_document: None,
            extra_info: BrowserExtraInfoEvidence::UnavailableInCurrentClient,
            resources: Vec::new(),
            events: Vec::new(),
            resource_accounting: BrowserResourceAccounting::new(0, 0, LossExtent::Known(0))
                .unwrap(),
            event_accounting: zero_events(),
        },
        BrowserStructuredEvidence::Layout(BrowserLayoutFact {
            scope: scope(),
            at: AT,
            layout_viewport: rect,
            visual_viewport: rect,
            content: rect,
            device_scale_micro: Some(1_000_000),
        }),
        BrowserStructuredEvidence::RuntimeDiagnostics {
            scope: None,
            diagnostics: Vec::new(),
            runtime_event_accounting: zero_events(),
            byte_accounting: BrowserByteAccounting {
                configured_limit: 10_000,
                enforcement: BrowserLimitEnforcement::RetentionAfterProviderMaterialization,
                budget_scope: BrowserBudgetScope::PerPayload,
                observed: 0,
                retained: 0,
                lost: LossExtent::Known(0),
                complete: true,
            },
        },
    ]
}
#[allow(
    clippy::option_if_let_else,
    reason = "fixture keeps decoded branches explicit"
)]
fn complete_staging(spec: &ResolvedBrowserCaptureSpec) -> BrowserArtifactStaging {
    let source = raw_slot(
        spec,
        WebArtifactFamily::Source,
        BrowserByteLayer::DecodedResponseBody,
        BrowserSnapshotObservation::source(scope(), AT),
        SOURCE,
    );
    let source_env = source.envelope().unwrap();
    let interpreted = canonical_browser_source_representation(
        source_env,
        &SourceMediaType::from_text("text/html; charset=utf-8"),
        DecodedSourceArtifactRef::from_untyped(
            spec.identity_plan()
                .reference(BrowserStagingFamily::Artifact(
                    WebArtifactFamily::DecodedSource,
                ))
                .unwrap(),
        ),
        spec.output_schemas()
            .get(WebArtifactFamily::DecodedSource)
            .unwrap()
            .clone(),
        1000,
    )
    .unwrap();
    let (representation_bytes, decoded_output) = interpreted.into_parts();
    let representation_mapping = BrowserArtifactMapping::new(
        BrowserStagingFamily::SourceRepresentation,
        BrowserByteLayer::SourceRepresentation,
    )
    .unwrap()
    .derived_from_source(SOURCE);
    let representation_outcome = ArtifactStagingOutcome::complete(
        representation_mapping,
        Arc::from(representation_bytes.as_slice()),
        byte_len(&representation_bytes),
    )
    .unwrap();
    let representation_env = envelope(
        spec,
        BrowserStagingFamily::SourceRepresentation,
        representation_bytes,
        SOURCE_REPRESENTATION_EVIDENCE_MEDIA_TYPE,
        vec![source_env.reference()],
        ArtifactByteExtent::Complete {
            retained_bytes: ByteCount::new(byte_len(representation_outcome.bytes().unwrap())),
        },
    );
    let representation = BrowserStagingSlot::new(
        BrowserStagingFamily::SourceRepresentation,
        representation_outcome,
    )
    .unwrap()
    .with_envelope(representation_env)
    .unwrap();
    let decoded = match decoded_output {
        Some(decoded) => {
            let (reference, decoder_producer, bytes, output_truncated) = decoded.into_parts();
            let family = BrowserStagingFamily::Artifact(WebArtifactFamily::DecodedSource);
            let mapping = BrowserArtifactMapping::new(family, BrowserByteLayer::DecodedSourceUtf8)
                .unwrap()
                .derived_from_source(SOURCE);
            let observed = byte_len(&bytes);
            let outcome = if output_truncated {
                ArtifactStagingOutcome::partial(
                    mapping,
                    Arc::clone(&bytes),
                    observed,
                    LossExtent::Unknown,
                    reason(),
                )
                .unwrap()
            } else {
                ArtifactStagingOutcome::complete(mapping, Arc::clone(&bytes), observed).unwrap()
            };
            let extent = if output_truncated {
                ArtifactByteExtent::truncated(
                    ByteCount::new(observed),
                    MeasuredCount::Unavailable { reason: reason() },
                )
                .unwrap()
            } else {
                ArtifactByteExtent::Complete {
                    retained_bytes: ByteCount::new(observed),
                }
            };
            assert_eq!(
                reference,
                DecodedSourceArtifactRef::from_untyped(
                    spec.identity_plan().reference(family).unwrap(),
                )
            );
            BrowserStagingSlot::new(family, outcome)
                .unwrap()
                .with_envelope(
                    StagedBrowserArtifactEnvelope::new(
                        spec.identity_plan().reference(family).unwrap(),
                        spec.output_schemas()
                            .get(WebArtifactFamily::DecodedSource)
                            .unwrap()
                            .clone(),
                        decoder_producer,
                        MediaType::new(DECODED_SOURCE_UTF8_MEDIA_TYPE).unwrap(),
                        Sha256Digest::digest(&bytes),
                        extent,
                        ArtifactSensitivity::Sensitive,
                        AT,
                        Arc::clone(&bytes),
                        vec![source_env.reference()],
                    )
                    .unwrap(),
                )
                .unwrap()
        }
        None => BrowserStagingSlot::new(
            BrowserStagingFamily::Artifact(WebArtifactFamily::DecodedSource),
            ArtifactStagingOutcome::unavailable(reason()),
        )
        .unwrap(),
    };
    let dom = raw_slot(
        spec,
        WebArtifactFamily::RenderedDom,
        BrowserByteLayer::RenderedDomUtf8,
        BrowserSnapshotObservation::rendered_dom(scope(), AT),
        DOM,
    );
    let [ax_e, net_e, layout_e, runtime_e] = evidence();
    let visual_fact = BrowserVisualFact {
        scope: scope(),
        at: AT,
        format: BrowserVisualFormat::Png,
        width_pixels: 1,
        height_pixels: 1,
        viewport_width_css: 800,
        viewport_height_css: 600,
        scroll_x_micro_css: 0,
        scroll_y_micro_css: 0,
        device_scale_micro: 1_000_000,
        layout_correlation: BrowserVisualLayoutCorrelation::SameDocumentEpochOnly,
        paired_layout_at: Some(AT),
    };
    let visual = raw_slot(
        spec,
        WebArtifactFamily::Visual,
        BrowserByteLayer::Png,
        BrowserSnapshotObservation::visual_fact(visual_fact),
        PNG,
    );
    BrowserArtifactStaging::new(
        source,
        representation,
        dom,
        structured_slot(spec, ax_e),
        structured_slot(spec, net_e),
        BrowserStagingSlot::new(
            BrowserStagingFamily::Artifact(WebArtifactFamily::Cookies),
            ArtifactStagingOutcome::unrequested(),
        )
        .unwrap(),
        BrowserStagingSlot::new(
            BrowserStagingFamily::Artifact(WebArtifactFamily::Storage),
            ArtifactStagingOutcome::unrequested(),
        )
        .unwrap(),
        structured_slot(spec, layout_e),
        visual,
        structured_slot(spec, runtime_e),
    )
    .unwrap()
    .with_decoded_source(decoded)
    .unwrap()
}
fn replace_layout_and_visual(
    staging: BrowserArtifactStaging,
    layout: BrowserStagingSlot,
    visual: BrowserStagingSlot,
) -> BrowserArtifactStaging {
    let [
        source,
        source_representation,
        decoded_source,
        rendered_dom,
        accessibility,
        network,
        cookies,
        storage,
        _layout,
        _visual,
        runtime,
    ] = staging.into_parts();
    BrowserArtifactStaging::new(
        source,
        source_representation,
        rendered_dom,
        accessibility,
        network,
        cookies,
        storage,
        layout,
        visual,
        runtime,
    )
    .unwrap()
    .with_decoded_source(decoded_source)
    .unwrap()
}

#[test]
fn same_document_visual_correlation_requires_matching_retained_layout_fact() {
    let spec = spec(
        WebArtifactFamily::Source,
        ArtifactRequest::Required,
        true,
        None,
        SettlementPolicy::Disabled,
    )
    .unwrap();
    let base = complete_staging(&spec);
    let visual = base
        .slots()
        .iter()
        .find(|slot| slot.family() == BrowserStagingFamily::Artifact(WebArtifactFamily::Visual))
        .unwrap()
        .clone();
    let unavailable_layout = BrowserStagingSlot::new(
        BrowserStagingFamily::Artifact(WebArtifactFamily::Layout),
        ArtifactStagingOutcome::unavailable(reason()),
    )
    .unwrap();
    assert_eq!(
        facts(
            spec.clone(),
            replace_layout_and_visual(base, unavailable_layout, visual.clone()),
            20,
        )
        .unwrap_err(),
        BrowserAdapterOutputError::RequestMismatch
    );

    let [_, _, BrowserStructuredEvidence::Layout(mut layout), _] = evidence() else {
        panic!("layout fixture");
    };
    layout.scope.epoch = BrowserDocumentEpoch(99);
    let mismatched_layout = structured_slot(&spec, BrowserStructuredEvidence::Layout(layout));
    assert_eq!(
        facts(
            spec.clone(),
            replace_layout_and_visual(complete_staging(&spec), mismatched_layout, visual.clone(),),
            20,
        )
        .unwrap_err(),
        BrowserAdapterOutputError::RequestMismatch
    );

    layout.scope = scope();
    layout.at = CaptureOffset::from_microseconds(9);
    let false_offset_layout = structured_slot(&spec, BrowserStructuredEvidence::Layout(layout));
    assert_eq!(
        facts(
            spec.clone(),
            replace_layout_and_visual(complete_staging(&spec), false_offset_layout, visual,),
            20,
        )
        .unwrap_err(),
        BrowserAdapterOutputError::RequestMismatch
    );
}

fn execution_receipt(capture_id: CaptureId) -> BrowserExecutionReceipt {
    execution_receipt_with_cleanup(
        capture_id,
        BrowserContextCleanupDisposition::Completed,
        BrowserProcessCleanupDisposition::WarmRetained,
        BrowserExecutionTerminalReason::Completed,
    )
}

fn execution_receipt_with_cleanup(
    capture_id: CaptureId,
    context_cleanup: BrowserContextCleanupDisposition,
    process_cleanup: BrowserProcessCleanupDisposition,
    reason: BrowserExecutionTerminalReason,
) -> BrowserExecutionReceipt {
    let process = BrowserProcessSlotLease::new(
        BrowserExecutionManagerId::random(),
        BrowserProcessSlotId::random(),
        BrowserProcessGeneration::new(NonZeroU64::MIN),
    );
    let execution = BrowserExecutionLease::new(process, BrowserExecutionId::random());
    let context = BrowserContextLease::new(execution.clone(), BrowserContextLeaseId::random());
    let session = BrowserSessionLease::new(context.clone(), BrowserSessionLeaseId::random());
    let tab = BrowserTabLease::new(session.clone(), BrowserTabLeaseId::random());
    let admission = BrowserExecutionAdmissionReceipt::new(
        BrowserExecutionScope::Independent,
        execution,
        context,
        session,
        tab,
    )
    .unwrap();
    let cleanup =
        BrowserExecutionCleanupReceipt::new(admission.clone(), context_cleanup, process_cleanup);
    let terminal =
        BrowserExecutionTerminalReceipt::new(admission.clone(), cleanup, reason).unwrap();
    let limits = BrowserExecutionLimits::new(
        BrowserProcessLimit::new(NonZeroU32::MIN),
        BrowserContextTotalLimit::new(NonZeroU32::MIN),
        BrowserContextsPerProcessLimit::new(NonZeroU32::MIN),
        BrowserTabTotalLimit::new(NonZeroU32::MIN),
        BrowserTabsPerSessionLimit::new(NonZeroU32::MIN),
        BrowserQueueDepthLimit::new(NonZeroU32::MIN),
        BrowserQueueWaitLimit::new(NonZeroU64::MIN),
        BrowserCleanupDeadline::new(NonZeroU64::MIN),
        BrowserRecycleThreshold::new(NonZeroU32::MIN),
    )
    .unwrap();
    let active_processes =
        u32::from(process_cleanup != BrowserProcessCleanupDisposition::Completed);
    let accounting = BrowserExecutionAccountingReceipt::terminal(
        admission,
        limits,
        active_processes,
        0,
        0,
        0,
        0,
        0,
        1,
    )
    .unwrap();
    BrowserExecutionReceipt::new(capture_id, terminal, accounting).unwrap()
}

fn attempt_lifecycle(
    spec: &ResolvedBrowserCaptureSpec,
    started_at: chrono::DateTime<Utc>,
) -> BoundedAcquisitionLifecycle {
    BoundedAcquisitionLifecycle::start(
        spec.request().capture_id(),
        spec.observation().clone(),
        started_at,
    )
}

fn ready_result(started_at: chrono::DateTime<Utc>) -> BrowserAdapterResult {
    let spec = spec(
        WebArtifactFamily::Source,
        ArtifactRequest::Required,
        true,
        None,
        SettlementPolicy::Disabled,
    )
    .unwrap();
    let facts = facts(spec.clone(), complete_staging(&spec), 20).unwrap();
    let terminal = resolve_browser_terminal(
        &[BrowserTerminalCandidate::new(
            END,
            BrowserTerminalSignal::ControllerCompleted,
        )],
        spec.observation().limits().maximum_elapsed(),
    )
    .unwrap();
    BrowserAdapterResult::ready_for_finalization(terminal, facts)
        .unwrap()
        .with_lifecycle(attempt_lifecycle(&spec, started_at))
        .unwrap()
}

fn ready_bundle() -> CaptureBundle {
    let start = chrono::DateTime::<Utc>::UNIX_EPOCH;
    finalize_browser_capture(
        ready_result(start),
        BrowserFinalizationInput {
            finished_at: start
                .checked_add_signed(TimeDelta::microseconds(20))
                .unwrap(),
            resource_origin: Observation::Unobserved,
            initiator_origin: Observation::Unobserved,
        },
    )
    .unwrap()
}

#[test]
fn challenge_fact_survives_finalization_and_wire_round_trip() {
    let bundle = ready_bundle();
    let challenge = bundle
        .capture()
        .browser_challenge()
        .expect("browser capture challenge fact");
    assert!(matches!(
        challenge.completeness(),
        BrowserResponseSignalCompleteness::Unavailable {
            reason: BrowserResponseSignalUnavailableReason::NavigationNotCollected
        }
    ));
    let bytes = WebCaptureWire::to_canonical_json(bundle.capture()).unwrap();
    let decoded = WebCaptureWire::from_json(&bytes).unwrap();
    assert_eq!(decoded.browser_challenge(), Some(challenge));

    let mut contradictory: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    *contradictory
        .pointer_mut("/capture/browser_challenge/active_challenge")
        .expect("challenge state") = serde_json::Value::String("present".into());
    assert!(WebCaptureWire::from_json(&serde_json::to_vec(&contradictory).unwrap()).is_err());
}

#[test]
fn finalization_rejects_a_result_without_its_attempt_lifecycle() {
    let start = chrono::DateTime::<Utc>::UNIX_EPOCH;
    let (state, terminal, facts) = ready_result(start).into_parts();
    assert_eq!(state, BrowserAdapterResultState::ReadyForFinalization);
    let result = BrowserAdapterResult::ready_for_finalization(terminal, facts).unwrap();

    assert!(matches!(
        finalize_browser_capture(
            result,
            BrowserFinalizationInput {
                finished_at: start
                    .checked_add_signed(TimeDelta::microseconds(20))
                    .unwrap(),
                resource_origin: Observation::Unobserved,
                initiator_origin: Observation::Unobserved,
            },
        ),
        Err(BrowserFinalizationError::MissingLifecycle)
    ));
}

#[test]
fn adapter_rejects_lifecycle_accounting_that_diverges_from_browser_facts() {
    let start = chrono::DateTime::<Utc>::UNIX_EPOCH;
    let (_, terminal, facts) = ready_result(start).into_parts();
    let mut lifecycle = attempt_lifecycle(facts.spec(), start);
    lifecycle
        .admit(
            LifecycleEvent::new(
                CaptureOffset::from_microseconds(1),
                ByteCount::new(1),
                ByteCount::new(1),
                true,
            )
            .unwrap(),
        )
        .unwrap();
    let result = BrowserAdapterResult::ready_for_finalization(terminal, facts).unwrap();

    assert!(matches!(
        result.with_lifecycle(lifecycle),
        Err(BrowserAdapterOutputError::LifecycleMismatch)
    ));
}

#[test]
fn adapter_result_requires_an_execution_receipt_for_its_exact_capture() {
    let result = ready_result(chrono::DateTime::<Utc>::UNIX_EPOCH);
    let capture_id = result.facts().spec().request().capture_id();

    assert!(matches!(
        result
            .clone()
            .with_execution(execution_receipt(CaptureId::random())),
        Err(BrowserAdapterOutputError::ExecutionCaptureMismatch)
    ));
    assert!(result.with_execution(execution_receipt(capture_id)).is_ok());
}

#[test]
fn finalizer_source_has_no_provider_or_direct_http_dependency() {
    let sources = [
        ("facade", include_str!("../src/browser_finalization.rs")),
        (
            "artifacts",
            include_str!("../src/browser_finalization/artifacts.rs"),
        ),
        (
            "references",
            include_str!("../src/browser_finalization/references.rs"),
        ),
        (
            "resolution",
            include_str!("../src/browser_finalization/resolution.rs"),
        ),
        (
            "termination",
            include_str!("../src/browser_finalization/termination.rs"),
        ),
    ];
    for (module, source) in sources {
        for forbidden in ["void_crawl", "provider::", "ResolvedDirectHttp", "wreq"] {
            assert!(
                !source.contains(forbidden),
                "{module} contains forbidden dependency: {forbidden}"
            );
        }
    }
}

#[test]
fn stopped_preserves_truncated_discarded_failed_and_unavailable_results() {
    let spec = spec(
        WebArtifactFamily::Source,
        ArtifactRequest::Required,
        true,
        None,
        SettlementPolicy::Disabled,
    )
    .unwrap();
    let [
        source,
        representation,
        decoded_source,
        _dom,
        _ax,
        _network,
        cookies,
        storage,
        layout,
        _visual,
        runtime,
    ] = complete_staging(&spec).into_parts();
    let why = reason();
    let dom_family = BrowserStagingFamily::Artifact(WebArtifactFamily::RenderedDom);
    let dom = BrowserStagingSlot::new(
        dom_family,
        ArtifactStagingOutcome::discarded(
            BrowserByteDomain::RenderedDomUtf8,
            LossExtent::Known(byte_len(DOM)),
            why.clone(),
        ),
    )
    .unwrap()
    .with_discarded_descriptor(BrowserDiscardedArtifactDescriptor::new(
        spec.identity_plan().reference(dom_family).unwrap(),
        spec.output_schemas()
            .get(WebArtifactFamily::RenderedDom)
            .unwrap()
            .clone(),
        spec.producer().clone(),
        MediaType::new("text/html").unwrap(),
        ArtifactSensitivity::Sensitive,
        AT,
        MeasuredCount::Known(ByteCount::new(byte_len(DOM))),
        Vec::new(),
    ))
    .unwrap();
    let ax = BrowserStagingSlot::new(
        BrowserStagingFamily::Artifact(WebArtifactFamily::AccessibilityTree),
        ArtifactStagingOutcome::failed(why.clone()),
    )
    .unwrap();
    let network = BrowserStagingSlot::new(
        BrowserStagingFamily::Artifact(WebArtifactFamily::Network),
        ArtifactStagingOutcome::unavailable(why.clone()),
    )
    .unwrap();
    let visual_family = BrowserStagingFamily::Artifact(WebArtifactFamily::Visual);
    let retained = &PNG[..8];
    let visual_fact = BrowserVisualFact {
        scope: scope(),
        at: AT,
        format: BrowserVisualFormat::Png,
        width_pixels: 1,
        height_pixels: 1,
        viewport_width_css: 800,
        viewport_height_css: 600,
        scroll_x_micro_css: 0,
        scroll_y_micro_css: 0,
        device_scale_micro: 1_000_000,
        layout_correlation: BrowserVisualLayoutCorrelation::SameDocumentEpochOnly,
        paired_layout_at: Some(AT),
    };
    let visual_mapping = mapping(
        WebArtifactFamily::Visual,
        BrowserByteLayer::Png,
        BrowserSnapshotObservation::visual_fact(visual_fact),
    );
    let visual_outcome = ArtifactStagingOutcome::truncated(
        visual_mapping,
        Arc::from(retained),
        byte_len(PNG),
        LossExtent::Known(byte_len(PNG).checked_sub(byte_len(retained)).unwrap()),
        why,
    )
    .unwrap();
    let visual_env = envelope(
        &spec,
        visual_family,
        retained.to_vec(),
        "image/png",
        Vec::new(),
        ArtifactByteExtent::truncated(
            ByteCount::new(byte_len(retained)),
            MeasuredCount::Known(ByteCount::new(byte_len(PNG))),
        )
        .unwrap(),
    );
    let visual = BrowserStagingSlot::new(visual_family, visual_outcome)
        .unwrap()
        .with_envelope(visual_env)
        .unwrap();
    let staging = BrowserArtifactStaging::new(
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
    let facts = facts(spec.clone(), staging, 20).unwrap();
    let terminal = resolve_browser_terminal(
        &[BrowserTerminalCandidate::new(
            END,
            BrowserTerminalSignal::ProviderFailed {
                reason: BrowserProviderStop::RendererFailure,
            },
        )],
        spec.observation().limits().maximum_elapsed(),
    )
    .unwrap();
    let start = chrono::DateTime::<Utc>::UNIX_EPOCH;
    let result = BrowserAdapterResult::stopped(terminal, facts)
        .unwrap()
        .with_lifecycle(attempt_lifecycle(&spec, start))
        .unwrap();
    let bundle = finalize_browser_capture(
        result,
        BrowserFinalizationInput {
            finished_at: start
                .checked_add_signed(TimeDelta::microseconds(20))
                .unwrap(),
            resource_origin: Observation::Unobserved,
            initiator_origin: Observation::Unobserved,
        },
    )
    .unwrap();
    assert_eq!(
        bundle.capture().completeness(),
        CaptureCompleteness::Incomplete
    );
    assert_eq!(
        bundle.capture().acquisition().receipt().receipt().outcome(),
        yosoi_types::ActivityOutcome::Partial
    );
    assert!(bundle.capture().browser_challenge().is_some());
    let results = bundle.capture().artifacts().results();
    let discarded_dom = results
        .rendered_dom()
        .artifacts()
        .and_then(|artifacts| artifacts.first())
        .expect("discarded DOM record");
    assert_eq!(
        discarded_dom.metadata().record().availability(),
        yosoi_types::ArtifactAvailability::Discarded
    );
    assert!(
        bundle
            .payload(WebArtifactRef::RenderedDom(discarded_dom.reference()))
            .is_none()
    );
    assert!(matches!(
        results.rendered_dom(),
        ArtifactFamilyResult::Partial { .. }
    ));
    assert!(matches!(
        results.accessibility_tree(),
        ArtifactFamilyResult::Failed { .. }
    ));
    assert!(matches!(
        results.network(),
        ArtifactFamilyResult::Unavailable { .. }
    ));
    let truncated_visual = results
        .visual()
        .artifacts()
        .and_then(|artifacts| artifacts.first())
        .expect("truncated visual record");
    assert_eq!(
        truncated_visual.metadata().record().availability(),
        yosoi_types::ArtifactAvailability::Truncated
    );
    assert_eq!(
        bundle.payload(WebArtifactRef::Visual(truncated_visual.reference())),
        Some(retained)
    );
    assert!(matches!(
        results.visual(),
        ArtifactFamilyResult::Partial { .. }
    ));
    assert_eq!(bundle.payloads().count(), 6);
}

#[test]
fn provider_stop_without_preserved_evidence_is_failed_not_partial() {
    let spec = spec(
        WebArtifactFamily::Source,
        ArtifactRequest::NotRequested,
        false,
        None,
        SettlementPolicy::Disabled,
    )
    .unwrap();
    let facts = facts(
        spec.clone(),
        staging(
            WebArtifactFamily::Source,
            ArtifactStagingOutcome::unrequested(),
        ),
        20,
    )
    .unwrap();
    let terminal = resolve_browser_terminal(
        &[BrowserTerminalCandidate::new(
            END,
            BrowserTerminalSignal::ProviderFailed {
                reason: BrowserProviderStop::BrowserDisconnected,
            },
        )],
        spec.observation().limits().maximum_elapsed(),
    )
    .unwrap();
    let start = chrono::DateTime::<Utc>::UNIX_EPOCH;
    let result = BrowserAdapterResult::stopped(terminal, facts)
        .unwrap()
        .with_lifecycle(attempt_lifecycle(&spec, start))
        .unwrap();
    let bundle = finalize_browser_capture(
        result,
        BrowserFinalizationInput {
            finished_at: start
                .checked_add_signed(TimeDelta::microseconds(20))
                .unwrap(),
            resource_origin: Observation::Unobserved,
            initiator_origin: Observation::Unobserved,
        },
    )
    .unwrap();
    assert_eq!(
        bundle.capture().completeness(),
        CaptureCompleteness::Incomplete
    );
    assert_eq!(
        bundle.capture().acquisition().receipt().receipt().outcome(),
        yosoi_types::ActivityOutcome::Failed
    );
    assert_eq!(bundle.payloads().count(), 0);
}

#[test]
fn browser_execution_receipts_bind_the_exact_browser_capture_and_round_trip() {
    let first = ready_bundle().capture().clone();
    let second = ready_bundle().capture().clone();
    let exact = first
        .clone()
        .with_browser_execution(execution_receipt(first.id()))
        .unwrap();
    assert!(exact.browser_execution().is_some());

    assert!(matches!(
        second.with_browser_execution(execution_receipt(first.id())),
        Err(WebCaptureError::ForeignBrowserExecution)
    ));

    let encoded = WebCaptureWire::to_canonical_json(&exact).unwrap();
    let decoded = WebCaptureWire::from_json(&encoded).unwrap();
    assert_eq!(
        WebCaptureWire::to_canonical_json(&decoded).unwrap(),
        encoded
    );

    let alternate = first
        .with_browser_execution(execution_receipt(exact.id()))
        .unwrap();
    assert_ne!(exact, alternate);
    assert_eq!(
        WebCaptureWire::identity_digest(&exact).unwrap(),
        WebCaptureWire::identity_digest(&alternate).unwrap()
    );
}

#[test]
fn browser_execution_semantic_digest_retains_context_cleanup_but_not_runtime_uuids() {
    let capture = ready_bundle().capture().clone();
    let with_cleanup = |context_cleanup| {
        capture
            .clone()
            .with_browser_execution(execution_receipt_with_cleanup(
                capture.id(),
                context_cleanup,
                BrowserProcessCleanupDisposition::Completed,
                BrowserExecutionTerminalReason::ProviderFailure,
            ))
            .unwrap()
    };
    let completed = with_cleanup(BrowserContextCleanupDisposition::Completed);
    let completed_with_other_runtime_ids =
        with_cleanup(BrowserContextCleanupDisposition::Completed);
    let failed = with_cleanup(BrowserContextCleanupDisposition::Failed);
    let deadline = with_cleanup(BrowserContextCleanupDisposition::DeadlineExceeded);

    assert_ne!(completed, completed_with_other_runtime_ids);
    assert_eq!(
        WebCaptureWire::identity_digest(&completed).unwrap(),
        WebCaptureWire::identity_digest(&completed_with_other_runtime_ids).unwrap()
    );
    let digests = [completed, failed, deadline]
        .map(|capture| WebCaptureWire::identity_digest(&capture).unwrap());
    assert_ne!(digests[0], digests[1]);
    assert_ne!(digests[0], digests[2]);
    assert_ne!(digests[1], digests[2]);
}

#[test]
#[allow(
    clippy::cognitive_complexity,
    reason = "one assertion table audits every durable browser evidence family"
)]
fn ready_finalizes_exact_payloads_and_browser_contexts() {
    let bundle = ready_bundle();
    assert_eq!(
        bundle.capture().completeness(),
        CaptureCompleteness::Complete
    );
    assert_eq!(bundle.payloads().count(), 9);
    let results = bundle.capture().artifacts().results();
    let artifacts = results.all_artifacts();
    let first = |family: WebArtifactFamily| {
        artifacts
            .iter()
            .find(|artifact| artifact.family() == family)
            .unwrap()
    };
    for artifact in &artifacts {
        let metadata = artifact.metadata();
        let payload = bundle
            .payload(artifact.reference())
            .expect("retained payload");
        assert_eq!(
            metadata.content_digest(),
            Some(yosoi_types::Sha256Digest::digest(payload))
        );
        if artifact.family() == WebArtifactFamily::DecodedSource {
            assert_eq!(
                metadata.provenance().producer(),
                &source_decoder_producer().unwrap()
            );
        } else {
            assert_eq!(metadata.provenance().producer(), &producer());
        }
        assert_eq!(
            metadata.provenance().generated_at(),
            &chrono::DateTime::<Utc>::UNIX_EPOCH
                .checked_add_signed(TimeDelta::microseconds(10))
                .unwrap()
        );
        if artifact.family() == WebArtifactFamily::SourceRepresentation {
            assert_eq!(
                metadata.provenance().schema(),
                &schema("test.representation")
            );
            assert_eq!(metadata.provenance().derived_from().len(), 1);
        } else if artifact.family() == WebArtifactFamily::DecodedSource {
            assert_eq!(
                metadata.provenance().schema(),
                &schema("test.decoded-source")
            );
            assert_eq!(metadata.provenance().derived_from().len(), 1);
        } else {
            assert_eq!(metadata.provenance().schema(), &schema("test.output"));
            assert!(metadata.provenance().derived_from().is_empty());
        }
    }
    assert_eq!(
        bundle.payload(first(WebArtifactFamily::Source).reference()),
        Some(SOURCE)
    );
    assert_eq!(
        first(WebArtifactFamily::Source)
            .metadata()
            .browser_context(),
        Some(&BrowserArtifactContext::DocumentSnapshot {
            scope: scope(),
            captured_at: AT
        })
    );
    assert_eq!(
        first(WebArtifactFamily::RenderedDom)
            .metadata()
            .browser_context(),
        Some(&BrowserArtifactContext::DocumentSnapshot {
            scope: scope(),
            captured_at: AT
        })
    );
    assert_eq!(
        first(WebArtifactFamily::Layout)
            .metadata()
            .browser_context(),
        Some(&BrowserArtifactContext::DocumentSnapshot {
            scope: scope(),
            captured_at: AT
        })
    );
    assert_eq!(
        first(WebArtifactFamily::AccessibilityTree)
            .metadata()
            .browser_context(),
        Some(&BrowserArtifactContext::DocumentSnapshot {
            scope: scope(),
            captured_at: AT
        })
    );
    assert!(matches!(
        first(WebArtifactFamily::Visual)
            .metadata()
            .browser_context(),
        Some(BrowserArtifactContext::Visual(_))
    ));
    let representation = results
        .source_representation()
        .artifacts()
        .unwrap()
        .first()
        .unwrap();
    let representation_payload = bundle
        .payload(WebArtifactRef::SourceRepresentation(
            representation.reference(),
        ))
        .unwrap();
    let representation_evidence = representation
        .parse_payload_for_capture(bundle.capture(), representation_payload)
        .unwrap();
    assert_eq!(
        representation_evidence.source(),
        results
            .source()
            .artifacts()
            .unwrap()
            .first()
            .unwrap()
            .reference()
    );
    let decoded_artifact = results
        .decoded_source()
        .artifacts()
        .unwrap()
        .first()
        .unwrap();
    let decoded_reference = decoded_artifact.reference();
    assert_eq!(
        bundle.payload(WebArtifactRef::DecodedSource(decoded_reference)),
        Some(SOURCE)
    );
    assert!(matches!(
        representation_evidence.decoding(),
        DurableCharacterDecoding::Complete(view)
            if view.decoded_source() == Some(decoded_reference)
    ));
    assert_eq!(decoded_artifact.interpretation().encoding(), "UTF-8");
    for family in [
        WebArtifactFamily::AccessibilityTree,
        WebArtifactFamily::Network,
        WebArtifactFamily::Layout,
        WebArtifactFamily::RuntimeDiagnostics,
    ] {
        let artifact = first(family);
        let parsed =
            BrowserStructuredEvidence::from_json(bundle.payload(artifact.reference()).unwrap())
                .unwrap();
        assert_eq!(parsed.family(), family);
        match parsed {
            BrowserStructuredEvidence::Accessibility(value) => {
                assert_eq!(value.scope, scope());
                assert_eq!(value.at, AT);
                assert!(value.bytes.complete);
            }
            BrowserStructuredEvidence::Network {
                resource_accounting,
                event_accounting,
                ..
            } => {
                assert_eq!(resource_accounting.lost(), LossExtent::Known(0));
                assert!(matches!(
                    event_accounting.dropped(),
                    MeasuredCount::Known(count) if count.get() == 0
                ));
            }
            BrowserStructuredEvidence::Layout(value) => {
                assert_eq!(value.scope, scope());
                assert_eq!(value.at, AT);
            }
            BrowserStructuredEvidence::RuntimeDiagnostics {
                scope: runtime_scope,
                byte_accounting,
                ..
            } => {
                assert_eq!(runtime_scope, None);
                assert!(byte_accounting.complete);
            }
        }
    }
}

#[derive(Serialize, Deserialize)]
struct PayloadFile {
    reference: WebArtifactRef,
    file: String,
}
struct TempDirectory(PathBuf);
impl TempDirectory {
    fn new(label: &str) -> Self {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path = env::temp_dir().join(format!("yosoi-cas332-{label}-{}-{nonce}", process_id()));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
}
impl Drop for TempDirectory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}
fn write_handoff(dir: &Path) {
    let bundle = ready_bundle();
    fs::write(
        dir.join("capture.json"),
        WebCaptureWire::to_canonical_json(bundle.capture()).unwrap(),
    )
    .unwrap();
    let mut index = Vec::new();
    for (n, (reference, bytes)) in bundle.payloads().enumerate() {
        let file = format!("payload-{n}.bin");
        fs::write(dir.join(&file), bytes).unwrap();
        index.push(PayloadFile { reference, file });
    }
    fs::write(dir.join("index.json"), serde_json::to_vec(&index).unwrap()).unwrap();
}
fn receive_handoff(dir: &Path) -> Result<(), String> {
    let metadata = fs::read(dir.join("capture.json")).map_err(|e| e.to_string())?;
    let capture = WebCaptureWire::from_json(&metadata).map_err(|e| e.to_string())?;
    if WebCaptureWire::to_canonical_json(&capture).map_err(|e| e.to_string())? != metadata {
        return Err("noncanonical".into());
    }
    let index: Vec<PayloadFile> =
        serde_json::from_slice(&fs::read(dir.join("index.json")).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())?;
    let mut builder = CaptureBundle::builder(capture);
    for item in index {
        builder
            .insert(
                item.reference,
                fs::read(dir.join(item.file)).map_err(|e| e.to_string())?,
            )
            .map_err(|e| e.to_string())?;
    }
    let bundle = builder.finalize().map_err(|e| e.to_string())?;
    let results = bundle.capture().artifacts().results();
    let rep = results
        .source_representation()
        .artifacts()
        .and_then(|artifacts| artifacts.first())
        .ok_or("representation")?;
    rep.parse_payload_for_capture(
        bundle.capture(),
        bundle
            .payload(WebArtifactRef::SourceRepresentation(rep.reference()))
            .ok_or("representation payload")?,
    )
    .map_err(|error| error.to_string())?;
    let artifacts = results.all_artifacts();
    for (family, expected) in [
        (
            WebArtifactFamily::Source,
            BrowserArtifactContext::DocumentSnapshot {
                scope: scope(),
                captured_at: AT,
            },
        ),
        (
            WebArtifactFamily::RenderedDom,
            BrowserArtifactContext::DocumentSnapshot {
                scope: scope(),
                captured_at: AT,
            },
        ),
        (
            WebArtifactFamily::Layout,
            BrowserArtifactContext::DocumentSnapshot {
                scope: scope(),
                captured_at: AT,
            },
        ),
    ] {
        let artifact = artifacts
            .iter()
            .find(|artifact| artifact.family() == family)
            .ok_or("raw artifact")?;
        if artifact.metadata().browser_context() != Some(&expected) {
            return Err("document context".into());
        }
    }
    let visual = artifacts
        .iter()
        .find(|artifact| artifact.family() == WebArtifactFamily::Visual)
        .ok_or("visual")?;
    if !matches!(
        visual.metadata().browser_context(),
        Some(BrowserArtifactContext::Visual(_))
    ) {
        return Err("visual context".into());
    }
    for family in [
        WebArtifactFamily::AccessibilityTree,
        WebArtifactFamily::Network,
        WebArtifactFamily::Layout,
        WebArtifactFamily::RuntimeDiagnostics,
    ] {
        let artifact = artifacts
            .iter()
            .find(|artifact| artifact.family() == family)
            .ok_or("artifact")?;
        if BrowserStructuredEvidence::from_json(
            bundle.payload(artifact.reference()).ok_or("payload")?,
        )
        .map_err(|e| e.to_string())?
        .family()
            != family
        {
            return Err("substituted family".into());
        }
    }
    Ok(())
}
fn subprocess_case(label: &str, mutate: impl FnOnce(&Path), success: bool) {
    if let Some(dir) = env::var_os("YOSOI_CAS332_RECEIVER") {
        assert!(receive_handoff(Path::new(&dir)).is_ok());
        return;
    }
    let dir = TempDirectory::new(label);
    write_handoff(&dir.0);
    mutate(&dir.0);
    let status = Command::new(env::current_exe().unwrap())
        .arg("--exact")
        .arg(label)
        .arg("--nocapture")
        .env("YOSOI_CAS332_RECEIVER", &dir.0)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .unwrap();
    assert_eq!(status.success(), success);
}
#[test]
fn finalized_visual_correlation_rejects_missing_layout_context() {
    let bundle = ready_bundle();
    let mut value = serde_json::to_value(bundle.capture()).unwrap();
    let layout = value
        .get_mut("artifacts")
        .and_then(|value| value.get_mut("results"))
        .and_then(|value| value.get_mut("layout"))
        .and_then(|value| value.get_mut("artifacts"))
        .and_then(serde_json::Value::as_array_mut)
        .and_then(|values| values.first_mut())
        .and_then(serde_json::Value::as_object_mut)
        .unwrap();
    layout.remove("browser_context");
    assert!(serde_json::from_value::<WebCapture>(value).is_err());
}

#[test]
fn canonical_subprocess_handoff() {
    subprocess_case("canonical_subprocess_handoff", |_| {}, true);
}
#[test]
fn missing_payload_is_rejected() {
    subprocess_case(
        "missing_payload_is_rejected",
        |d| fs::remove_file(d.join("payload-0.bin")).unwrap(),
        false,
    );
}
#[test]
fn tampered_metadata_is_rejected() {
    subprocess_case(
        "tampered_metadata_is_rejected",
        |d| {
            let path = d.join("capture.json");
            let mut bytes = fs::read(&path).unwrap();
            bytes[0] = b'!';
            fs::write(path, bytes).unwrap();
        },
        false,
    );
}
#[test]
fn wrong_digest_metadata_is_rejected() {
    subprocess_case(
        "wrong_digest_metadata_is_rejected",
        |directory| {
            let path = directory.join("capture.json");
            let mut value: serde_json::Value =
                serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
            value["capture"]["artifacts"]["results"]["source"]["artifacts"][0]["record"]["content_digest"] =
                serde_json::json!("00".repeat(32));
            let changed_record = value["capture"]["artifacts"]["results"]["source"]["artifacts"][0]
                ["record"]
                .clone();
            let changed_id = changed_record["id"].clone();
            let outputs = value["capture"]["acquisition"]["receipt"]["receipt"]["outputs"]
                .as_array_mut()
                .unwrap();
            let output = outputs
                .iter_mut()
                .find(|output| output["id"] == changed_id)
                .unwrap();
            *output = changed_record;
            let changed = serde_json::to_vec(&value).unwrap();
            let capture = WebCaptureWire::from_json(&changed).unwrap();
            fs::write(path, WebCaptureWire::to_canonical_json(&capture).unwrap()).unwrap();
        },
        false,
    );
}

#[test]
fn tampered_payload_is_rejected() {
    subprocess_case(
        "tampered_payload_is_rejected",
        |d| {
            let p = d.join("payload-0.bin");
            let mut b = fs::read(&p).unwrap();
            b[0] ^= 1;
            fs::write(p, b).unwrap();
        },
        false,
    );
}
#[test]
fn substituted_payload_pair_is_rejected() {
    subprocess_case(
        "substituted_payload_pair_is_rejected",
        |d| {
            let a = fs::read(d.join("payload-0.bin")).unwrap();
            let b = fs::read(d.join("payload-1.bin")).unwrap();
            fs::write(d.join("payload-0.bin"), b).unwrap();
            fs::write(d.join("payload-1.bin"), a).unwrap();
        },
        false,
    );
}
#[test]
fn wrong_size_payload_is_rejected() {
    subprocess_case(
        "wrong_size_payload_is_rejected",
        |d| {
            let p = d.join("payload-0.bin");
            let mut b = fs::read(&p).unwrap();
            b.push(0);
            fs::write(p, b).unwrap();
        },
        false,
    );
}
