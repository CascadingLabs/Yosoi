#![allow(clippy::missing_const_for_fn)]
use crate::internal::types as yosoi_types;
use crate::internal::web_capture as yosoi_web_capture;

use crate::internal::web_capture::browser_spec::{
    ResolvedBrowserCaptureSpec, byte_domain_for_staging, request_for,
};
use crate::internal::web_capture::{BrowserCaptureEnvironment, CaptureOffset, WebArtifactFamily};
use std::collections::HashSet;
use thiserror::Error;

use super::staging::{
    BrowserArtifactMapping, BrowserArtifactStaging, BrowserStagingAccounting, BrowserStagingFamily,
    BrowserStagingParts, BrowserStagingSlot, LossExtent, StagingState,
};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CleanupState {
    Complete,
    Failed,
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BrowserAdapterFacts {
    observed_through: CaptureOffset,
    staging: BrowserArtifactStaging,
    environment: BrowserCaptureEnvironment,
    spec: ResolvedBrowserCaptureSpec,
    events: yosoi_web_capture::EventAccounting,
    bytes: BrowserStagingAccounting,
    terminal_in_flight: yosoi_web_capture::InFlightActivity,
    navigation_completed: bool,
    main_document_status: Option<u16>,
    settlement: Option<yosoi_web_capture::SettlementEvidence>,
    cleanup: CleanupState,
    challenge: yosoi_web_capture::BrowserChallengeFact,
}
/// Unvalidated ownership extraction; reconstruct through `BrowserAdapterFacts::new`.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BrowserAdapterFactsParts {
    pub spec: ResolvedBrowserCaptureSpec,
    pub staging: BrowserArtifactStaging,
    pub environment: BrowserCaptureEnvironment,
    pub observed_through: CaptureOffset,
    pub events: yosoi_web_capture::EventAccounting,
    pub bytes: BrowserStagingAccounting,
    pub terminal_in_flight: yosoi_web_capture::InFlightActivity,
    pub navigation_completed: bool,
    pub main_document_status: Option<u16>,
    pub settlement: Option<yosoi_web_capture::SettlementEvidence>,
    pub cleanup: CleanupState,
    pub challenge: yosoi_web_capture::BrowserChallengeFact,
}
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum BrowserAdapterOutputError {
    #[error("staging contradicts resolved request, capability, or bounds")]
    RequestMismatch,
    #[error("terminal offset does not equal observed-through")]
    TerminalOffsetMismatch,
    #[error("retained aggregate exceeds observed aggregate")]
    RetainedExceedsObserved,
    #[error("known aggregate loss does not reconcile")]
    AggregateLossMismatch,
    #[error("accounting overflow")]
    Overflow,
    #[error("effective environment contradicts certification")]
    EnvironmentMismatch,
    #[error("ready result requires successful terminal, navigation, and cleanup")]
    InvalidReadyState,
    #[error("browser execution receipt must be bound to the adapter result capture")]
    ExecutionCaptureMismatch,
    #[error("acquisition lifecycle contradicts the adapter result capture or observation policy")]
    LifecycleMismatch,
    #[error("stopped result terminal contradicts cleanup")]
    InvalidStoppedState,
}
impl BrowserAdapterFacts {
    #[allow(clippy::too_many_arguments, clippy::cognitive_complexity)]
    pub fn new(
        observed_through: CaptureOffset,
        staging: BrowserArtifactStaging,
        environment: BrowserCaptureEnvironment,
        spec: ResolvedBrowserCaptureSpec,
        events: yosoi_web_capture::EventAccounting,
        terminal_in_flight: yosoi_web_capture::InFlightActivity,
        navigation_completed: bool,
        settlement: Option<yosoi_web_capture::SettlementEvidence>,
        cleanup: CleanupState,
        challenge: yosoi_web_capture::BrowserChallengeFact,
    ) -> Result<Self, BrowserAdapterOutputError> {
        let events_admitted = events.admitted().get();
        let events_retained = events.retained().get();
        let events_dropped = match events.dropped() {
            yosoi_web_capture::MeasuredCount::Known(count) => LossExtent::Known(count.get()),
            yosoi_web_capture::MeasuredCount::Unavailable { .. } => LossExtent::Unknown,
        };
        if let Some(evidence) = &settlement {
            let yosoi_web_capture::SettlementPolicy::QuietPeriod(policy) =
                spec.observation().settlement()
            else {
                return Err(BrowserAdapterOutputError::InvalidReadyState);
            };
            if evidence.policy() != policy.id()
                || evidence.satisfied_at() != observed_through
                || evidence.relevant_in_flight() > policy.maximum_relevant_in_flight()
                || evidence
                    .satisfied_at()
                    .as_microseconds()
                    .checked_sub(evidence.quiet_since().as_microseconds())
                    .is_none_or(|elapsed| elapsed < policy.required_quiet().as_microseconds())
                || terminal_in_flight.settlement_relevant()
                    != &yosoi_web_capture::MeasuredCount::Known(evidence.relevant_in_flight())
            {
                return Err(BrowserAdapterOutputError::InvalidReadyState);
            }
        }
        let expected_source_media = staging
            .source_representation()
            .and_then(BrowserStagingSlot::envelope)
            .and_then(|envelope| {
                yosoi_web_capture::SourceRepresentationEvidence::from_json(envelope.bytes()).ok()
            })
            .map(|evidence| match evidence.declaration() {
                yosoi_web_capture::MediaDeclaration::Parsed { essence, .. } => essence.clone(),
                yosoi_web_capture::MediaDeclaration::Missing
                | yosoi_web_capture::MediaDeclaration::Malformed(_) => {
                    "application/octet-stream".to_owned()
                }
            });
        let decoded_source_producer = yosoi_web_capture::source_decoder_producer()
            .map_err(|_| BrowserAdapterOutputError::RequestMismatch)?;
        let retained_layout = staging.slots().iter().find_map(|slot| {
            if slot.family() != BrowserStagingFamily::Artifact(WebArtifactFamily::Layout) {
                return None;
            }
            let BrowserStagingParts::Structured {
                evidence: yosoi_web_capture::BrowserStructuredEvidence::Layout(layout),
                ..
            } = slot.outcome().parts()
            else {
                return None;
            };
            slot.envelope().map(|envelope| (*layout, envelope))
        });
        let capabilities = spec.capabilities();
        for slot in staging.slots() {
            let state = slot.outcome().state();
            let evidence_family = matches!(
                slot.family(),
                BrowserStagingFamily::SourceRepresentation
                    | BrowserStagingFamily::Artifact(
                        WebArtifactFamily::Source
                            | WebArtifactFamily::DecodedSource
                            | WebArtifactFamily::RenderedDom
                            | WebArtifactFamily::Network
                            | WebArtifactFamily::AccessibilityTree
                            | WebArtifactFamily::Layout
                            | WebArtifactFamily::Visual
                            | WebArtifactFamily::RuntimeDiagnostics
                    )
            );
            let retained_state = matches!(
                state,
                StagingState::Complete | StagingState::Partial | StagingState::Truncated
            );
            let is_structured = matches!(
                slot.outcome().parts(),
                BrowserStagingParts::Structured { .. }
            );
            let requires_structured = matches!(
                slot.family(),
                BrowserStagingFamily::Artifact(
                    WebArtifactFamily::Network
                        | WebArtifactFamily::AccessibilityTree
                        | WebArtifactFamily::Layout
                        | WebArtifactFamily::RuntimeDiagnostics
                )
            );
            if retained_state && requires_structured != is_structured {
                return Err(BrowserAdapterOutputError::RequestMismatch);
            }
            let envelope_required = evidence_family && retained_state;
            if envelope_required != slot.envelope().is_some() {
                return Err(BrowserAdapterOutputError::RequestMismatch);
            }
            let discarded_descriptor_required = matches!(
                slot.family(),
                BrowserStagingFamily::Artifact(
                    WebArtifactFamily::Source
                        | WebArtifactFamily::RenderedDom
                        | WebArtifactFamily::Visual
                )
            );
            if state == StagingState::Discarded {
                if !discarded_descriptor_required {
                    return Err(BrowserAdapterOutputError::RequestMismatch);
                }
                let descriptor = slot
                    .discarded_descriptor()
                    .ok_or(BrowserAdapterOutputError::RequestMismatch)?;
                let expected_schema = match slot.family() {
                    BrowserStagingFamily::SourceRepresentation => {
                        spec.output_schemas().source_representation()
                    }
                    BrowserStagingFamily::Artifact(family) => spec.output_schemas().get(family),
                };
                let extent_matches = match (slot.outcome().parts(), descriptor.observed_extent()) {
                    (
                        BrowserStagingParts::Discarded {
                            observed: LossExtent::Known(observed),
                            ..
                        },
                        yosoi_web_capture::ArtifactByteExtent::Discarded {
                            observed_bytes:
                                yosoi_web_capture::MeasuredCount::Known(descriptor_observed),
                        },
                    ) => *observed == descriptor_observed.get(),
                    (
                        BrowserStagingParts::Discarded {
                            observed: LossExtent::Unknown,
                            ..
                        },
                        yosoi_web_capture::ArtifactByteExtent::Discarded {
                            observed_bytes: yosoi_web_capture::MeasuredCount::Unavailable { .. },
                        },
                    ) => true,
                    _ => false,
                };
                let media_type_matches = match slot.family() {
                    BrowserStagingFamily::Artifact(WebArtifactFamily::RenderedDom) => {
                        descriptor.media_type().as_str() == "text/html"
                    }
                    BrowserStagingFamily::Artifact(WebArtifactFamily::Visual) => {
                        descriptor.media_type().as_str() == "image/png"
                    }
                    BrowserStagingFamily::Artifact(WebArtifactFamily::Source) => true,
                    _ => false,
                };
                if spec.identity_plan().reference(slot.family()) != Some(descriptor.reference())
                    || expected_schema != Some(descriptor.schema())
                    || descriptor.producer() != spec.producer()
                    || descriptor.generated_at() > observed_through
                    || descriptor.sensitivity() != yosoi_web_capture::ArtifactSensitivity::Sensitive
                    || !extent_matches
                    || !media_type_matches
                    || !descriptor.derived_from().is_empty()
                {
                    return Err(BrowserAdapterOutputError::RequestMismatch);
                }
            } else if slot.discarded_descriptor().is_some() {
                return Err(BrowserAdapterOutputError::RequestMismatch);
            }
            if let Some(envelope) = slot.envelope() {
                let expected_schema = match slot.family() {
                    BrowserStagingFamily::SourceRepresentation => {
                        spec.output_schemas().source_representation()
                    }
                    BrowserStagingFamily::Artifact(value) => spec.output_schemas().get(value),
                };
                let media_type_matches = match slot.family() {
                    BrowserStagingFamily::SourceRepresentation => {
                        envelope.media_type().as_str()
                            == yosoi_web_capture::SOURCE_REPRESENTATION_EVIDENCE_MEDIA_TYPE
                    }
                    BrowserStagingFamily::Artifact(WebArtifactFamily::RenderedDom) => {
                        envelope.media_type().as_str() == "text/html"
                    }
                    BrowserStagingFamily::Artifact(WebArtifactFamily::DecodedSource) => {
                        envelope.media_type().as_str()
                            == yosoi_web_capture::DECODED_SOURCE_UTF8_MEDIA_TYPE
                    }
                    BrowserStagingFamily::Artifact(
                        WebArtifactFamily::Network
                        | WebArtifactFamily::AccessibilityTree
                        | WebArtifactFamily::Layout
                        | WebArtifactFamily::RuntimeDiagnostics,
                    ) => envelope.media_type().as_str() == "application/json",
                    BrowserStagingFamily::Artifact(WebArtifactFamily::Visual) => {
                        envelope.media_type().as_str() == "image/png"
                    }
                    BrowserStagingFamily::Artifact(WebArtifactFamily::Source) => {
                        expected_source_media.as_deref() == Some(envelope.media_type().as_str())
                    }
                    BrowserStagingFamily::Artifact(_) => true,
                };
                let expected_producer = match slot.family() {
                    BrowserStagingFamily::Artifact(WebArtifactFamily::DecodedSource) => {
                        &decoded_source_producer
                    }
                    BrowserStagingFamily::Artifact(_)
                    | BrowserStagingFamily::SourceRepresentation => spec.producer(),
                };
                if spec.identity_plan().reference(slot.family()) != Some(envelope.reference())
                    || expected_schema != Some(envelope.schema())
                    || envelope.producer() != expected_producer
                    || envelope.generated_at() > observed_through
                    || envelope.sensitivity() != yosoi_web_capture::ArtifactSensitivity::Sensitive
                    || !media_type_matches
                {
                    return Err(BrowserAdapterOutputError::RequestMismatch);
                }
                let expected_lineage = if matches!(
                    slot.family(),
                    BrowserStagingFamily::SourceRepresentation
                        | BrowserStagingFamily::Artifact(WebArtifactFamily::DecodedSource)
                ) {
                    spec.identity_plan()
                        .source()
                        .map(yosoi_web_capture::SourceArtifactRef::as_untyped)
                        .into_iter()
                        .collect::<Vec<_>>()
                } else {
                    Vec::new()
                };
                if envelope.derived_from() != expected_lineage.as_slice() {
                    return Err(BrowserAdapterOutputError::RequestMismatch);
                }
                if slot.family() == BrowserStagingFamily::SourceRepresentation
                    && !yosoi_web_capture::SourceRepresentationEvidence::from_json(envelope.bytes()).is_ok_and(
                        |evidence| {
                            let decoded_reference = match evidence.decoding() {
                                yosoi_web_capture::DurableCharacterDecoding::Complete(view)
                                | yosoi_web_capture::DurableCharacterDecoding::OutputTruncated(view) => {
                                    view.decoded_source()
                                }
                                yosoi_web_capture::DurableCharacterDecoding::UnsupportedEncoding { .. }
                                | yosoi_web_capture::DurableCharacterDecoding::Undecodable { .. }
                                | yosoi_web_capture::DurableCharacterDecoding::NotApplicable { .. } => None,
                            };
                            let staged_decoded_reference = staging
                                .decoded_source()
                                .and_then(BrowserStagingSlot::envelope)
                                .map(|decoded| {
                                    yosoi_web_capture::DecodedSourceArtifactRef::from_untyped(
                                        decoded.reference(),
                                    )
                                });
                            Some(evidence.source().as_untyped())
                                == spec
                                    .identity_plan()
                                    .source()
                                    .map(yosoi_web_capture::SourceArtifactRef::as_untyped)
                                && decoded_reference == staged_decoded_reference
                                && evidence
                                    .to_canonical_json()
                                    .is_ok_and(|bytes| bytes == envelope.bytes())
                        },
                    )
                {
                    return Err(BrowserAdapterOutputError::RequestMismatch);
                }
                if let BrowserStagingParts::Structured { evidence, .. } = slot.outcome().parts()
                    && !evidence
                        .to_canonical_json()
                        .is_ok_and(|bytes| bytes == envelope.bytes())
                {
                    return Err(BrowserAdapterOutputError::RequestMismatch);
                }
                if slot.outcome().bytes().is_some()
                    && (matches!(state, StagingState::Complete)
                        != matches!(
                            envelope.extent(),
                            yosoi_web_capture::ArtifactByteExtent::Complete { .. }
                        ))
                {
                    return Err(BrowserAdapterOutputError::RequestMismatch);
                }
            }
            let family = match slot.family() {
                BrowserStagingFamily::Artifact(family) => family,
                BrowserStagingFamily::SourceRepresentation => WebArtifactFamily::Source,
            };
            if let BrowserStagingParts::Structured { evidence, .. } = slot.outcome().parts() {
                match evidence {
                    yosoi_web_capture::BrowserStructuredEvidence::Network {
                        resources,
                        events: network_events,
                        resource_accounting,
                        event_accounting,
                        requested_url,
                        final_url,
                        redirects,
                        main_document,
                        ..
                    } => {
                        let network_retained = event_accounting.retained().get();
                        let network_loss = match event_accounting.dropped() {
                            yosoi_web_capture::MeasuredCount::Known(count) => {
                                LossExtent::Known(count.get())
                            }
                            yosoi_web_capture::MeasuredCount::Unavailable { .. } => {
                                LossExtent::Unknown
                            }
                        };
                        let loss_is_subset = match (network_loss, events_dropped) {
                            (LossExtent::Known(network), LossExtent::Known(global)) => {
                                network <= global
                            }
                            (_, LossExtent::Unknown) => true,
                            (LossExtent::Unknown, LossExtent::Known(_)) => false,
                        };
                        let retained_resources = u64::try_from(resources.len())
                            .map_err(|_| BrowserAdapterOutputError::Overflow)?;
                        if retained_resources != resource_accounting.retained()
                            || resource_accounting.retained()
                                > u64::from(spec.bounds().max_resources().get())
                            || u64::try_from(network_events.len())
                                .map_err(|_| BrowserAdapterOutputError::Overflow)?
                                != network_retained
                            || event_accounting.admitted().get() > events.admitted().get()
                            || network_retained > events_retained
                            || !loss_is_subset
                        {
                            return Err(BrowserAdapterOutputError::RequestMismatch);
                        }
                        let mut previous = None;
                        for event in network_events {
                            if event.at > observed_through
                                || matches!(
                                    event.kind,
                                    yosoi_web_capture::BrowserObservationKind::ConsoleApiCalled
                                        | yosoi_web_capture::BrowserObservationKind::RuntimeExceptionThrown
                                )
                                || previous.is_some_and(|(sequence, at)| {
                                    event.sequence <= sequence || event.at < at
                                })
                            {
                                return Err(BrowserAdapterOutputError::RequestMismatch);
                            }
                            previous = Some((event.sequence, event.at));
                        }
                        let mut ids = HashSet::new();
                        for resource in resources {
                            if resource.redirect_from.is_some_and(|id| !ids.contains(&id))
                                || !ids.insert(resource.id)
                            {
                                return Err(BrowserAdapterOutputError::RequestMismatch);
                            }
                        }
                        if network_events
                            .iter()
                            .any(|event| event.resource.is_some_and(|id| !ids.contains(&id)))
                            || redirects.iter().any(|edge| {
                                !ids.contains(&edge.from)
                                    || !ids.contains(&edge.to)
                                    || edge.from == edge.to
                            })
                            || main_document
                                .as_ref()
                                .is_some_and(|main| !ids.contains(&main.resource))
                            || (requested_url.is_some() || final_url.is_some())
                                && spec.admission().urls()
                                    != yosoi_web_capture::BrowserUrlAdmission::AdmitNetworkUrls
                            || main_document
                                .as_ref()
                                .is_some_and(|main| !main.headers.is_empty())
                                && spec.admission().headers()
                                    != yosoi_web_capture::BrowserHeaderAdmission::AdmitSafeMainDocument
                        {
                            return Err(BrowserAdapterOutputError::RequestMismatch);
                        }
                    }
                    yosoi_web_capture::BrowserStructuredEvidence::Accessibility(accessibility) => {
                        let nodes_sum = match accessibility.nodes_lost {
                            LossExtent::Known(lost) => {
                                accessibility.nodes_retained.checked_add(lost)
                            }
                            LossExtent::Unknown => None,
                        };
                        let capture_mode_valid = match accessibility.capture_mode {
                            yosoi_web_capture::BrowserAccessibilityCaptureMode::FullTree => {
                                accessibility.requested_depth.is_none()
                            }
                            yosoi_web_capture::BrowserAccessibilityCaptureMode::DepthLimited => {
                                accessibility.requested_depth.is_some()
                            }
                        };
                        if accessibility.at > observed_through
                            || accessibility.schema_version == 0
                            || !capture_mode_valid
                            || accessibility.nodes_retained > accessibility.nodes_observed
                            || accessibility.nodes_retained
                                > u64::from(spec.bounds().max_accessibility_nodes().get())
                            || nodes_sum.is_some_and(|sum| sum != accessibility.nodes_observed)
                            || accessibility.bytes.retained
                                != u64::try_from(accessibility.canonical_node_bytes.len())
                                    .map_err(|_| BrowserAdapterOutputError::Overflow)?
                            || !byte_accounting_matches_bound(
                                accessibility.bytes,
                                &spec,
                                yosoi_web_capture::BrowserByteDomain::AccessibilityJsonUtf8,
                            )
                        {
                            return Err(BrowserAdapterOutputError::RequestMismatch);
                        }
                    }
                    yosoi_web_capture::BrowserStructuredEvidence::Layout(layout) => {
                        if layout.at > observed_through
                            || layout.scope.frame.0 == 0
                            || layout.scope.epoch.0 == 0
                            || slot
                                .envelope()
                                .is_none_or(|envelope| envelope.generated_at() != layout.at)
                        {
                            return Err(BrowserAdapterOutputError::RequestMismatch);
                        }
                    }
                    yosoi_web_capture::BrowserStructuredEvidence::RuntimeDiagnostics {
                        scope,
                        diagnostics,
                        runtime_event_accounting,
                        byte_accounting,
                    } => {
                        if scope.is_some_and(|scope| scope.frame.0 == 0 || scope.epoch.0 == 0) {
                            return Err(BrowserAdapterOutputError::RequestMismatch);
                        }
                        let mut previous = None;
                        for diagnostic in diagnostics {
                            if diagnostic.at > observed_through
                                || diagnostic.retained_utf8_bytes > diagnostic.complete_utf8_bytes
                                || (diagnostic.truncated
                                    != (diagnostic.retained_utf8_bytes
                                        < diagnostic.complete_utf8_bytes))
                                || previous.is_some_and(|sequence| diagnostic.sequence <= sequence)
                            {
                                return Err(BrowserAdapterOutputError::RequestMismatch);
                            }
                            previous = Some(diagnostic.sequence);
                        }
                        let diagnostic_count = u64::try_from(diagnostics.len())
                            .map_err(|_| BrowserAdapterOutputError::Overflow)?;
                        let (complete_diagnostic_bytes, retained_diagnostic_bytes) = diagnostics
                            .iter()
                            .try_fold((0_u64, 0_u64), |(complete, retained), diagnostic| {
                                Ok::<_, BrowserAdapterOutputError>((
                                    complete
                                        .checked_add(diagnostic.complete_utf8_bytes)
                                        .ok_or(BrowserAdapterOutputError::Overflow)?,
                                    retained
                                        .checked_add(diagnostic.retained_utf8_bytes)
                                        .ok_or(BrowserAdapterOutputError::Overflow)?,
                                ))
                            })?;
                        if runtime_event_accounting.retained().get() != diagnostic_count
                            || runtime_event_accounting.admitted().get() > events.admitted().get()
                            || runtime_event_accounting.retained().get() > events.retained().get()
                            || complete_diagnostic_bytes != byte_accounting.observed
                            || retained_diagnostic_bytes != byte_accounting.retained
                            || !byte_accounting_matches_bound(
                                *byte_accounting,
                                &spec,
                                yosoi_web_capture::BrowserByteDomain::RuntimeDiagnosticUtf8,
                            )
                        {
                            return Err(BrowserAdapterOutputError::RequestMismatch);
                        }
                    }
                }
            }
            if let Some(mapping) = slot.outcome().mapping()
                && matches!(
                    slot.family(),
                    BrowserStagingFamily::Artifact(
                        WebArtifactFamily::Source
                            | WebArtifactFamily::RenderedDom
                            | WebArtifactFamily::AccessibilityTree
                            | WebArtifactFamily::Visual
                    )
                )
            {
                let snapshot = mapping
                    .snapshot()
                    .ok_or(BrowserAdapterOutputError::RequestMismatch)?;
                if snapshot.at > observed_through
                    || slot
                        .envelope()
                        .is_none_or(|envelope| envelope.generated_at() != snapshot.at)
                {
                    return Err(BrowserAdapterOutputError::RequestMismatch);
                }
                if family == WebArtifactFamily::AccessibilityTree
                    && snapshot
                        .accessibility_nodes
                        .is_none_or(|nodes| nodes > spec.bounds().max_accessibility_nodes().get())
                {
                    return Err(BrowserAdapterOutputError::RequestMismatch);
                }
                if family == WebArtifactFamily::Visual {
                    let Some(visual) = snapshot.visual else {
                        return Err(BrowserAdapterOutputError::RequestMismatch);
                    };
                    let correlation_valid = match visual.layout_correlation {
                        yosoi_web_capture::BrowserVisualLayoutCorrelation::SameDocumentEpochOnly => {
                            retained_layout.is_some_and(|(layout, _)| {
                                visual.paired_layout_at == Some(layout.at)
                                    && layout.at <= visual.at
                                    && layout.scope == visual.scope
                            })
                        }
                        yosoi_web_capture::BrowserVisualLayoutCorrelation::Unavailable => {
                            visual.paired_layout_at.is_none()
                        }
                    };
                    if visual.scope != snapshot.scope
                        || visual.at != snapshot.at
                        || visual.width_pixels == 0
                        || visual.height_pixels == 0
                        || visual.viewport_width_css == 0
                        || visual.viewport_height_css == 0
                        || visual.device_scale_micro == 0
                        || !correlation_valid
                    {
                        return Err(BrowserAdapterOutputError::RequestMismatch);
                    }
                } else if snapshot.visual.is_some() {
                    return Err(BrowserAdapterOutputError::RequestMismatch);
                }
            }
            let requested = request_for(spec.artifacts(), family);
            if matches!(requested, yosoi_web_capture::ArtifactRequest::NotRequested)
                != (state == StagingState::Unrequested)
            {
                return Err(BrowserAdapterOutputError::RequestMismatch);
            }
            if state != StagingState::Unrequested {
                let agrees = match capabilities.families().get(family) {
                    Some(yosoi_web_capture::BrowserCapabilityStatus::Supported) => {
                        !matches!(state, StagingState::Disabled | StagingState::Unsupported)
                    }
                    Some(yosoi_web_capture::BrowserCapabilityStatus::Disabled { .. }) => {
                        state == StagingState::Disabled
                    }
                    Some(yosoi_web_capture::BrowserCapabilityStatus::Unavailable { .. }) => {
                        state == StagingState::Unavailable
                    }
                    Some(yosoi_web_capture::BrowserCapabilityStatus::Unsupported { .. }) => {
                        state == StagingState::Unsupported
                    }
                    None => false,
                };
                if !agrees {
                    return Err(BrowserAdapterOutputError::RequestMismatch);
                }
            }
            if let Some(domain) = byte_domain_for_staging(slot.family()) {
                for bound in spec
                    .bounds()
                    .byte_bounds()
                    .iter()
                    .filter(|bound| bound.domain() == domain)
                {
                    if slot
                        .outcome()
                        .retained()
                        .map_err(|_| BrowserAdapterOutputError::Overflow)?
                        > bound.limit().get()
                    {
                        return Err(BrowserAdapterOutputError::RequestMismatch);
                    }
                }
            }
        }
        let source = staging.slots().iter().find(|slot| {
            slot.family() == BrowserStagingFamily::Artifact(WebArtifactFamily::Source)
        });
        let representation = staging
            .slots()
            .iter()
            .find(|slot| slot.family() == BrowserStagingFamily::SourceRepresentation);
        if let (Some(source), Some(representation)) = (source, representation) {
            let source_retained = matches!(
                source.outcome().state(),
                StagingState::Complete | StagingState::Partial | StagingState::Truncated
            );
            let representation_retained = matches!(
                representation.outcome().state(),
                StagingState::Complete | StagingState::Partial | StagingState::Truncated
            );
            let binding_matches = representation
                .outcome()
                .mapping()
                .and_then(BrowserArtifactMapping::source_binding)
                == source
                    .outcome()
                    .bytes()
                    .map(yosoi_types::Sha256Digest::digest);
            if representation_retained && (!source_retained || !binding_matches) {
                return Err(BrowserAdapterOutputError::RequestMismatch);
            }
        }
        if events_admitted > spec.bounds().max_events().get()
            || observed_through.as_microseconds()
                > spec
                    .observation()
                    .limits()
                    .maximum_elapsed()
                    .as_microseconds()
        {
            return Err(BrowserAdapterOutputError::RequestMismatch);
        }
        let bytes = staging.accounting()?;
        validate_accounting(bytes.observed(), bytes.retained(), bytes.lost())?;
        if spec
            .observation()
            .limits()
            .byte_limit()
            .is_some_and(|limit| bytes.observed() > limit.get())
            || spec
                .observation()
                .limits()
                .event_limit()
                .is_some_and(|limit| events_admitted > limit.get())
        {
            return Err(BrowserAdapterOutputError::RequestMismatch);
        }
        for bound in spec.bounds().byte_bounds().iter().filter(|bound| {
            bound.budget_scope() == yosoi_web_capture::BrowserBudgetScope::CaptureAggregate
        }) {
            let retained = staging
                .slots()
                .iter()
                .filter(|slot| byte_domain_for_staging(slot.family()) == Some(bound.domain()))
                .try_fold(0_u64, |sum, slot| {
                    sum.checked_add(slot.outcome().accounting()?.retained())
                        .ok_or(BrowserAdapterOutputError::Overflow)
                })?;
            if retained > bound.limit().get() {
                return Err(BrowserAdapterOutputError::RequestMismatch);
            }
        }
        if environment.controller() != capabilities.profile().producer() {
            return Err(BrowserAdapterOutputError::EnvironmentMismatch);
        }
        if !matches!(environment.mode(),yosoi_web_capture::EnvironmentValue::Known { value: mode } if matches!(capabilities.profile().acquisition(),yosoi_web_capture::AcquisitionCapabilityProfile::DocumentNavigation(p) if p.mode()==*mode))
        {
            return Err(BrowserAdapterOutputError::EnvironmentMismatch);
        }
        Ok(Self {
            observed_through,
            staging,
            environment,
            spec,
            events,
            bytes,
            terminal_in_flight,
            navigation_completed,
            main_document_status: None,
            settlement,
            cleanup,
            challenge,
        })
    }
    pub const fn spec(&self) -> &ResolvedBrowserCaptureSpec {
        &self.spec
    }
    pub const fn settlement(&self) -> Option<&yosoi_web_capture::SettlementEvidence> {
        self.settlement.as_ref()
    }
    pub const fn environment(&self) -> &BrowserCaptureEnvironment {
        &self.environment
    }
    pub const fn observed_through(&self) -> CaptureOffset {
        self.observed_through
    }
    pub const fn events(&self) -> &yosoi_web_capture::EventAccounting {
        &self.events
    }
    pub const fn bytes(&self) -> BrowserStagingAccounting {
        self.bytes
    }
    pub fn terminal_in_flight(&self) -> yosoi_web_capture::InFlightActivity {
        self.terminal_in_flight.clone()
    }
    pub fn into_parts(self) -> BrowserAdapterFactsParts {
        BrowserAdapterFactsParts {
            spec: self.spec,
            staging: self.staging,
            environment: self.environment,
            observed_through: self.observed_through,
            events: self.events,
            bytes: self.bytes,
            terminal_in_flight: self.terminal_in_flight,
            navigation_completed: self.navigation_completed,
            main_document_status: self.main_document_status,
            settlement: self.settlement,
            cleanup: self.cleanup,
            challenge: self.challenge,
        }
    }
    pub const fn cleanup(&self) -> CleanupState {
        self.cleanup
    }
    pub const fn navigation_completed(&self) -> bool {
        self.navigation_completed
    }
    pub const fn main_document_status(&self) -> Option<u16> {
        self.main_document_status
    }
    pub const fn with_main_document_status(mut self, status: Option<u16>) -> Self {
        self.main_document_status = status;
        self
    }
    pub const fn challenge(&self) -> &yosoi_web_capture::BrowserChallengeFact {
        &self.challenge
    }
    pub const fn staging(&self) -> &BrowserArtifactStaging {
        &self.staging
    }
    pub(super) fn source_representation_is_finalizable(&self) -> bool {
        let (Some(source), Some(representation)) =
            (self.staging.source(), self.staging.source_representation())
        else {
            return false;
        };
        let source_state = source.outcome().state();
        let representation_state = representation.outcome().state();
        if matches!(
            source_state,
            StagingState::Complete | StagingState::Partial | StagingState::Truncated
        ) {
            let decoded_reference = representation
                .envelope()
                .and_then(|envelope| {
                    yosoi_web_capture::SourceRepresentationEvidence::from_json(envelope.bytes())
                        .ok()
                })
                .and_then(|evidence| match evidence.decoding() {
                    yosoi_web_capture::DurableCharacterDecoding::Complete(view)
                    | yosoi_web_capture::DurableCharacterDecoding::OutputTruncated(view) => {
                        view.decoded_source()
                    }
                    yosoi_web_capture::DurableCharacterDecoding::UnsupportedEncoding { .. }
                    | yosoi_web_capture::DurableCharacterDecoding::Undecodable { .. }
                    | yosoi_web_capture::DurableCharacterDecoding::NotApplicable { .. } => None,
                });
            let staged_decoded_reference = self
                .staging
                .decoded_source()
                .and_then(BrowserStagingSlot::envelope)
                .map(|envelope| {
                    yosoi_web_capture::DecodedSourceArtifactRef::from_untyped(envelope.reference())
                });
            return representation_state == StagingState::Complete
                && representation
                    .outcome()
                    .mapping()
                    .and_then(BrowserArtifactMapping::source_binding)
                    == source
                        .outcome()
                        .bytes()
                        .map(yosoi_types::Sha256Digest::digest)
                && decoded_reference == staged_decoded_reference;
        }
        if source_state == StagingState::Discarded {
            // Discarded source has no bytes to interpret; unavailable is the
            // narrowest truthful representation outcome.
            return representation_state == StagingState::Unavailable
                && self
                    .staging
                    .decoded_source()
                    .is_some_and(|decoded| decoded.outcome().state() == StagingState::Unavailable);
        }
        matches!(
            (source_state, representation_state),
            (StagingState::Unrequested, StagingState::Unrequested)
                | (StagingState::Unavailable, StagingState::Unavailable)
                | (StagingState::Failed, StagingState::Failed)
                | (StagingState::Disabled, StagingState::Disabled)
                | (StagingState::Unsupported, StagingState::Unsupported)
        ) && self
            .staging
            .decoded_source()
            .is_some_and(|decoded| decoded.outcome().state() == representation_state)
    }
}
fn byte_accounting_matches_bound(
    value: yosoi_web_capture::BrowserByteAccounting,
    spec: &ResolvedBrowserCaptureSpec,
    domain: yosoi_web_capture::BrowserByteDomain,
) -> bool {
    let Some(bound) = spec
        .bounds()
        .byte_bounds()
        .iter()
        .find(|bound| bound.domain() == domain)
    else {
        return false;
    };
    value.configured_limit == bound.limit().get()
        && value.enforcement == bound.enforcement()
        && value.budget_scope == bound.budget_scope()
        && value.retained <= value.observed
        && value.retained <= value.configured_limit
        && match value.lost {
            LossExtent::Known(lost) => {
                value.retained.checked_add(lost) == Some(value.observed)
                    && value.complete == (lost == 0)
            }
            LossExtent::Unknown => !value.complete,
        }
}

fn validate_accounting(
    observed: u64,
    retained: u64,
    loss: LossExtent,
) -> Result<(), BrowserAdapterOutputError> {
    if retained > observed {
        return Err(BrowserAdapterOutputError::RetainedExceedsObserved);
    }
    if let LossExtent::Known(lost) = loss
        && retained
            .checked_add(lost)
            .ok_or(BrowserAdapterOutputError::Overflow)?
            != observed
    {
        return Err(BrowserAdapterOutputError::AggregateLossMismatch);
    }
    Ok(())
}
