use super::super::{VoidCrawlAdapterError, config, conversions};
use super::{ProviderOutput, merge_event_accounting, observation_event_accounting};
use crate as yosoi;
use std::sync::Arc;
use void_crawl_core as provider;

fn slot(
    family: yosoi::BrowserStagingFamily,
    outcome: yosoi::ArtifactStagingOutcome,
) -> Result<yosoi::BrowserStagingSlot, VoidCrawlAdapterError> {
    yosoi::BrowserStagingSlot::new(family, outcome)
        .map_err(|_| VoidCrawlAdapterError::InvalidStaging)
}
fn retained_slot(
    spec: &yosoi::ResolvedBrowserCaptureSpec,
    family: yosoi::BrowserStagingFamily,
    outcome: yosoi::ArtifactStagingOutcome,
    media_type: &str,
    at: yosoi::CaptureOffset,
    derived_from: Vec<yosoi_types::ArtifactRef>,
) -> Result<yosoi::BrowserStagingSlot, VoidCrawlAdapterError> {
    retained_slot_with_producer(
        spec,
        spec.producer(),
        family,
        outcome,
        media_type,
        at,
        derived_from,
    )
}

fn retained_slot_with_producer(
    spec: &yosoi::ResolvedBrowserCaptureSpec,
    producer: &yosoi_types::Producer,
    family: yosoi::BrowserStagingFamily,
    outcome: yosoi::ArtifactStagingOutcome,
    media_type: &str,
    at: yosoi::CaptureOffset,
    derived_from: Vec<yosoi_types::ArtifactRef>,
) -> Result<yosoi::BrowserStagingSlot, VoidCrawlAdapterError> {
    let Some(bytes) = outcome.bytes() else {
        let staged = slot(family, outcome.clone())?;
        if let yosoi::BrowserStagingParts::Discarded { observed, .. } = outcome.parts() {
            let observed_bytes = match observed {
                yosoi::LossExtent::Known(value) => {
                    yosoi::MeasuredCount::Known(yosoi::ByteCount::new(*value))
                }
                yosoi::LossExtent::Unknown => yosoi::MeasuredCount::Unavailable {
                    reason: conversions::reason("voidcrawl.discarded-byte-extent-unavailable")?,
                },
            };
            let schema = match family {
                yosoi::BrowserStagingFamily::SourceRepresentation => {
                    spec.output_schemas().source_representation()
                }
                yosoi::BrowserStagingFamily::Artifact(value) => spec.output_schemas().get(value),
            }
            .ok_or(VoidCrawlAdapterError::InvalidResolvedSpec)?
            .clone();
            let reference = spec
                .identity_plan()
                .reference(family)
                .ok_or(VoidCrawlAdapterError::InvalidResolvedSpec)?;
            let descriptor = yosoi::BrowserDiscardedArtifactDescriptor::new(
                reference,
                schema,
                producer.clone(),
                yosoi::MediaType::new(media_type)
                    .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?,
                yosoi::ArtifactSensitivity::Sensitive,
                at,
                observed_bytes,
                derived_from,
            );
            return staged
                .with_discarded_descriptor(descriptor)
                .map_err(|_| VoidCrawlAdapterError::InvalidStaging);
        }
        return Ok(staged);
    };
    let shared_bytes = outcome
        .shared_bytes()
        .ok_or(VoidCrawlAdapterError::InvalidStaging)?;
    let retained = u64::try_from(bytes.len()).map_err(|_| VoidCrawlAdapterError::InvalidStaging)?;
    let extent = match outcome.parts() {
        yosoi::BrowserStagingParts::Complete { .. } => yosoi::ArtifactByteExtent::Complete {
            retained_bytes: yosoi::ByteCount::new(retained),
        },
        yosoi::BrowserStagingParts::Partial { observed, loss, .. }
        | yosoi::BrowserStagingParts::Truncated { observed, loss, .. } => {
            let complete = match loss {
                yosoi::LossExtent::Known(_) => {
                    yosoi::MeasuredCount::Known(yosoi::ByteCount::new(*observed))
                }
                yosoi::LossExtent::Unknown => yosoi::MeasuredCount::Unavailable {
                    reason: conversions::reason("voidcrawl.bytes.complete-size-unknown")?,
                },
            };
            yosoi::ArtifactByteExtent::truncated(yosoi::ByteCount::new(retained), complete)
                .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?
        }
        _ => return Err(VoidCrawlAdapterError::InvalidStaging),
    };
    let schema = match family {
        yosoi::BrowserStagingFamily::SourceRepresentation => {
            spec.output_schemas().source_representation()
        }
        yosoi::BrowserStagingFamily::Artifact(value) => spec.output_schemas().get(value),
    }
    .ok_or(VoidCrawlAdapterError::InvalidResolvedSpec)?
    .clone();
    let reference = spec
        .identity_plan()
        .reference(family)
        .ok_or(VoidCrawlAdapterError::InvalidResolvedSpec)?;
    let envelope = yosoi::StagedBrowserArtifactEnvelope::new(
        reference,
        schema,
        producer.clone(),
        yosoi::MediaType::new(media_type).map_err(|_| VoidCrawlAdapterError::InvalidStaging)?,
        yosoi_types::Sha256Digest::digest(bytes),
        extent,
        yosoi::ArtifactSensitivity::Sensitive,
        at,
        shared_bytes,
        derived_from,
    )
    .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?;
    slot(family, outcome)?
        .with_envelope(envelope)
        .map_err(|_| VoidCrawlAdapterError::InvalidStaging)
}

fn structured_slot(
    spec: &yosoi::ResolvedBrowserCaptureSpec,
    family: yosoi::BrowserStagingFamily,
    outcome: yosoi::ArtifactStagingOutcome,
    at: yosoi::CaptureOffset,
) -> Result<yosoi::BrowserStagingSlot, VoidCrawlAdapterError> {
    let yosoi::BrowserStagingParts::Structured { evidence, .. } = outcome.parts() else {
        return Err(VoidCrawlAdapterError::InvalidStaging);
    };
    let bytes = evidence
        .to_canonical_json()
        .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?;
    let extent = yosoi::ArtifactByteExtent::Complete {
        retained_bytes: yosoi::ByteCount::new(
            u64::try_from(bytes.len()).map_err(|_| VoidCrawlAdapterError::InvalidStaging)?,
        ),
    };
    let schema = match family {
        yosoi::BrowserStagingFamily::Artifact(value) => spec.output_schemas().get(value),
        yosoi::BrowserStagingFamily::SourceRepresentation => None,
    }
    .ok_or(VoidCrawlAdapterError::InvalidResolvedSpec)?
    .clone();
    let reference = spec
        .identity_plan()
        .reference(family)
        .ok_or(VoidCrawlAdapterError::InvalidResolvedSpec)?;
    let envelope = yosoi::StagedBrowserArtifactEnvelope::new(
        reference,
        schema,
        spec.producer().clone(),
        yosoi::MediaType::new("application/json")
            .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?,
        yosoi_types::Sha256Digest::digest(&bytes),
        extent,
        yosoi::ArtifactSensitivity::Sensitive,
        at,
        Arc::from(bytes),
        Vec::new(),
    )
    .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?;
    slot(family, outcome)?
        .with_envelope(envelope)
        .map_err(|_| VoidCrawlAdapterError::InvalidStaging)
}

fn unrequested(
    family: yosoi::BrowserStagingFamily,
) -> Result<yosoi::BrowserStagingSlot, VoidCrawlAdapterError> {
    slot(family, yosoi::ArtifactStagingOutcome::unrequested())
}
fn missing(
    family: yosoi::BrowserStagingFamily,
    requested: yosoi::ArtifactRequest,
) -> Result<yosoi::BrowserStagingSlot, VoidCrawlAdapterError> {
    if requested == yosoi::ArtifactRequest::NotRequested {
        unrequested(family)
    } else {
        slot(
            family,
            yosoi::ArtifactStagingOutcome::failed(conversions::reason(
                "voidcrawl.capture.stopped-before-snapshot",
            )?),
        )
    }
}

fn source_representation_and_decoded_source(
    spec: &yosoi::ResolvedBrowserCaptureSpec,
    requested: yosoi::ArtifactRequest,
    source_envelope: Option<&yosoi::StagedBrowserArtifactEnvelope>,
    declaration: &yosoi::SourceMediaType,
    at: yosoi::CaptureOffset,
) -> Result<(yosoi::BrowserStagingSlot, yosoi::BrowserStagingSlot), VoidCrawlAdapterError> {
    let representation_family = yosoi::BrowserStagingFamily::SourceRepresentation;
    let decoded_family =
        yosoi::BrowserStagingFamily::Artifact(yosoi::WebArtifactFamily::DecodedSource);
    if requested == yosoi::ArtifactRequest::NotRequested {
        return Ok((
            unrequested(representation_family)?,
            unrequested(decoded_family)?,
        ));
    }
    let Some(source_envelope) = source_envelope else {
        let reason = conversions::reason("yosoi.source-representation.source-bytes-unavailable")?;
        return Ok((
            slot(
                representation_family,
                yosoi::ArtifactStagingOutcome::unavailable(reason.clone()),
            )?,
            slot(
                decoded_family,
                yosoi::ArtifactStagingOutcome::unavailable(reason),
            )?,
        ));
    };
    let decoded_ref = spec
        .identity_plan()
        .reference(decoded_family)
        .map(yosoi::DecodedSourceArtifactRef::from_untyped)
        .ok_or(VoidCrawlAdapterError::InvalidResolvedSpec)?;
    let decoded_schema = spec
        .output_schemas()
        .get(yosoi::WebArtifactFamily::DecodedSource)
        .ok_or(VoidCrawlAdapterError::InvalidResolvedSpec)?
        .clone();
    let unicode_limit = u64::try_from(config::byte_limit(
        spec,
        yosoi::BrowserByteDomain::DecodedSourceUtf8,
    )?)
    .map_err(|_| VoidCrawlAdapterError::InvalidResolvedSpec)?;
    let interpreted = yosoi::canonical_browser_source_representation(
        source_envelope,
        declaration,
        decoded_ref,
        decoded_schema,
        unicode_limit,
    )
    .map_err(VoidCrawlAdapterError::SourceRepresentation)?;
    let (evidence_bytes, decoded_output) = interpreted.into_parts();
    let mapping = yosoi::BrowserArtifactMapping::new(
        representation_family,
        yosoi::BrowserByteLayer::SourceRepresentation,
    )
    .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?
    .derived_from_source(source_envelope.bytes());
    let observed =
        u64::try_from(evidence_bytes.len()).map_err(|_| VoidCrawlAdapterError::InvalidStaging)?;
    let outcome =
        yosoi::ArtifactStagingOutcome::complete(mapping, Arc::from(evidence_bytes), observed)
            .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?;
    let representation = retained_slot(
        spec,
        representation_family,
        outcome,
        yosoi::SOURCE_REPRESENTATION_EVIDENCE_MEDIA_TYPE,
        at,
        vec![source_envelope.reference()],
    )?;
    let decoded = match decoded_output {
        Some(output) => {
            let (reference, decoder_producer, bytes, output_truncated) = output.into_parts();
            if reference != decoded_ref {
                return Err(VoidCrawlAdapterError::InvalidStaging);
            }
            let mapping = yosoi::BrowserArtifactMapping::new(
                decoded_family,
                yosoi::BrowserByteLayer::DecodedSourceUtf8,
            )
            .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?
            .derived_from_source(source_envelope.bytes());
            let observed =
                u64::try_from(bytes.len()).map_err(|_| VoidCrawlAdapterError::InvalidStaging)?;
            let outcome = if output_truncated {
                yosoi::ArtifactStagingOutcome::partial(
                    mapping,
                    bytes,
                    observed,
                    yosoi::LossExtent::Unknown,
                    conversions::reason("browser.decoded-source.output-truncated")?,
                )
            } else {
                yosoi::ArtifactStagingOutcome::complete(mapping, bytes, observed)
            }
            .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?;
            retained_slot_with_producer(
                spec,
                &decoder_producer,
                decoded_family,
                outcome,
                yosoi::DECODED_SOURCE_UTF8_MEDIA_TYPE,
                at,
                vec![source_envelope.reference()],
            )?
        }
        None => slot(
            decoded_family,
            yosoi::ArtifactStagingOutcome::unavailable(conversions::reason(
                "yosoi.source-representation.decoded-source-unavailable",
            )?),
        )?,
    };
    Ok((representation, decoded))
}

fn source_media_type(
    main: &provider::MainDocumentSource,
    admission: yosoi::BrowserEvidenceAdmissionPolicy,
) -> yosoi::SourceMediaType {
    if admission.headers() == yosoi::BrowserHeaderAdmission::AdmitSafeMainDocument {
        let mut declarations = main
            .headers
            .as_slice()
            .iter()
            .filter(|(name, _)| name.eq_ignore_ascii_case("content-type"))
            .map(|(_, value)| value.as_str());
        if let Some(value) = declarations.next() {
            return if declarations.next().is_some() {
                yosoi::SourceMediaType::Duplicate
            } else {
                yosoi::SourceMediaType::from_text(value)
            };
        }
    }
    main.mime_type
        .as_ref()
        .map_or(yosoi::SourceMediaType::Absent, |value| {
            yosoi::SourceMediaType::from_text(value.clone())
        })
}

fn observed_runtime_scope(output: &ProviderOutput) -> Option<yosoi::BrowserDocumentScope> {
    let provider_scopes = [
        output.dom.as_ref().map(|(value, _)| &value.scope),
        output.accessibility.as_ref().map(|(value, _)| &value.scope),
        output.layout.as_ref().map(|(value, _)| &value.scope),
        output.visual.as_ref().map(|(value, _)| &value.scope),
    ];
    let mut observed = None;
    for provider_scope in provider_scopes.into_iter().flatten() {
        let mapped = conversions::document_scope(provider_scope)?;
        if observed.is_some_and(|existing| existing != mapped) {
            return None;
        }
        observed = Some(mapped);
    }
    observed
}

pub(super) fn into_facts(
    spec: &yosoi::ResolvedBrowserCaptureSpec,
    output: ProviderOutput,
    at: yosoi::CaptureOffset,
    cleanup: yosoi::CleanupState,
) -> Result<yosoi::BrowserAdapterFacts, VoidCrawlAdapterError> {
    let main_document_status = output
        .navigation
        .as_ref()
        .and_then(|report| report.main_document.as_ref())
        .and_then(|main| main.status);
    let runtime_scope = observed_runtime_scope(&output);
    let challenge = conversions::browser_challenge(output.navigation.as_ref(), spec.admission());
    let artifacts = spec.artifacts();
    let source_at = match (
        output
            .navigation
            .as_ref()
            .and_then(|report| report.main_document.as_ref()),
        output.navigation_armed_at_micros,
    ) {
        (Some(main), Some(armed_at)) => yosoi::CaptureOffset::from_microseconds(
            armed_at
                .checked_add(main.captured_at_micros)
                .ok_or(VoidCrawlAdapterError::InvalidStaging)?,
        ),
        _ => at,
    };
    let source = match output
        .navigation
        .as_ref()
        .and_then(|report| report.main_document.as_ref())
    {
        Some(value) if artifacts.source() != yosoi::ArtifactRequest::NotRequested => retained_slot(
            spec,
            yosoi::BrowserStagingFamily::Artifact(yosoi::WebArtifactFamily::Source),
            conversions::source(
                value,
                source_at,
                conversions::main_document_scope(),
                spec.admission().main_body(),
            )?,
            value
                .mime_type
                .as_deref()
                .unwrap_or("application/octet-stream"),
            source_at,
            Vec::new(),
        )?,
        _ => missing(
            yosoi::BrowserStagingFamily::Artifact(yosoi::WebArtifactFamily::Source),
            artifacts.source(),
        )?,
    };
    let declaration = output
        .navigation
        .as_ref()
        .and_then(|report| report.main_document.as_ref())
        .map_or(yosoi::SourceMediaType::Absent, |main| {
            source_media_type(main, spec.admission())
        });
    let (source_representation, decoded_source) = source_representation_and_decoded_source(
        spec,
        artifacts.source(),
        source.envelope(),
        &declaration,
        at,
    )?;
    let network_events = match (&output.navigation, output.navigation_armed_at_micros) {
        (Some(report), Some(armed_at)) => Some(conversions::navigation_event_accounting(
            report, armed_at, at,
        )?),
        (Some(_), None) => return Err(VoidCrawlAdapterError::InvalidStaging),
        (None, _) => None,
    };
    let network = match output.navigation {
        Some(value) if artifacts.network() != yosoi::ArtifactRequest::NotRequested => {
            let navigation_armed_at = output
                .navigation_armed_at_micros
                .ok_or(VoidCrawlAdapterError::InvalidStaging)?;
            let (outcome, _) =
                conversions::network(value, spec.admission(), navigation_armed_at, at)?;
            structured_slot(
                spec,
                yosoi::BrowserStagingFamily::Artifact(yosoi::WebArtifactFamily::Network),
                outcome,
                at,
            )?
        }
        Some(_) => unrequested(yosoi::BrowserStagingFamily::Artifact(
            yosoi::WebArtifactFamily::Network,
        ))?,
        None if output.navigation_failed => slot(
            yosoi::BrowserStagingFamily::Artifact(yosoi::WebArtifactFamily::Network),
            yosoi::ArtifactStagingOutcome::failed(conversions::reason(
                "voidcrawl.navigation.finalization-failed",
            )?),
        )?,
        None => missing(
            yosoi::BrowserStagingFamily::Artifact(yosoi::WebArtifactFamily::Network),
            artifacts.network(),
        )?,
    };
    let events = match (&output.observation, network_events) {
        (Some(report), Some(network)) => merge_event_accounting(
            &observation_event_accounting(&report.accounting.events)?,
            &network,
        )?,
        (Some(report), None) => observation_event_accounting(&report.accounting.events)?,
        (None, network) => network.unwrap_or(conversions::missing_observation_accounting(
            output.observation_failed || output.navigation_failed,
        )?),
    };
    let staging = yosoi::BrowserArtifactStaging::new(
        source,
        source_representation,
        match output.dom {
            Some((v, captured_at)) => retained_slot(
                spec,
                yosoi::BrowserStagingFamily::Artifact(yosoi::WebArtifactFamily::RenderedDom),
                conversions::rendered_dom(&v, captured_at)?,
                "text/html",
                captured_at,
                Vec::new(),
            )?,
            None => missing(
                yosoi::BrowserStagingFamily::Artifact(yosoi::WebArtifactFamily::RenderedDom),
                artifacts.rendered_dom(),
            )?,
        },
        match output.accessibility {
            Some((v, captured_at)) => structured_slot(
                spec,
                yosoi::BrowserStagingFamily::Artifact(yosoi::WebArtifactFamily::AccessibilityTree),
                conversions::accessibility(&v, captured_at)?,
                captured_at,
            )?,
            None => missing(
                yosoi::BrowserStagingFamily::Artifact(yosoi::WebArtifactFamily::AccessibilityTree),
                artifacts.accessibility_tree(),
            )?,
        },
        network,
        unrequested(yosoi::BrowserStagingFamily::Artifact(
            yosoi::WebArtifactFamily::Cookies,
        ))?,
        unrequested(yosoi::BrowserStagingFamily::Artifact(
            yosoi::WebArtifactFamily::Storage,
        ))?,
        match output.layout.clone() {
            Some((v, captured_at)) => structured_slot(
                spec,
                yosoi::BrowserStagingFamily::Artifact(yosoi::WebArtifactFamily::Layout),
                conversions::layout(&v, captured_at)?,
                captured_at,
            )?,
            None => missing(
                yosoi::BrowserStagingFamily::Artifact(yosoi::WebArtifactFamily::Layout),
                artifacts.layout(),
            )?,
        },
        match output.visual {
            Some((ref value, captured_at)) => retained_slot(
                spec,
                yosoi::BrowserStagingFamily::Artifact(yosoi::WebArtifactFamily::Visual),
                conversions::visual(
                    value,
                    output.layout.as_ref(),
                    captured_at,
                    config::byte_limit(spec, yosoi::BrowserByteDomain::ScreenshotPng)?,
                )?,
                "image/png",
                captured_at,
                Vec::new(),
            )?,
            None => missing(
                yosoi::BrowserStagingFamily::Artifact(yosoi::WebArtifactFamily::Visual),
                artifacts.visual(),
            )?,
        },
        match (&output.observation, output.observation_armed_at_micros) {
            (Some(report), Some(armed_at))
                if artifacts.runtime_diagnostics() != yosoi::ArtifactRequest::NotRequested =>
            {
                structured_slot(
                    spec,
                    yosoi::BrowserStagingFamily::Artifact(
                        yosoi::WebArtifactFamily::RuntimeDiagnostics,
                    ),
                    conversions::runtime(report, armed_at, runtime_scope)?,
                    at,
                )?
            }
            _ => missing(
                yosoi::BrowserStagingFamily::Artifact(yosoi::WebArtifactFamily::RuntimeDiagnostics),
                artifacts.runtime_diagnostics(),
            )?,
        },
    )
    .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?
    .with_decoded_source(decoded_source)
    .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?;
    yosoi::BrowserAdapterFacts::new(
        at,
        staging,
        conversions::environment(output.environment, spec.capabilities().instrumentation())?,
        spec.clone(),
        events,
        terminal_in_flight(output.observation.as_ref(), output.settlement.as_ref())?,
        output.navigation_completed,
        output.settlement,
        cleanup,
        challenge,
    )
    .map(|facts| facts.with_main_document_status(main_document_status))
    .map_err(VoidCrawlAdapterError::InvalidOutput)
}

fn terminal_in_flight(
    observation: Option<&provider::ObservationReport>,
    settlement: Option<&yosoi::SettlementEvidence>,
) -> Result<yosoi::InFlightActivity, VoidCrawlAdapterError> {
    let total = match observation.map(|report| report.accounting.in_flight_requests) {
        Some(provider::MeasuredCount::Known { value }) => {
            yosoi::MeasuredCount::Known(yosoi::ActivityCount::new(value))
        }
        Some(provider::MeasuredCount::Unavailable { .. }) | None => {
            yosoi::MeasuredCount::Unavailable {
                reason: conversions::reason("voidcrawl.observation.in-flight-unavailable")?,
            }
        }
    };
    let relevant = match settlement {
        Some(proof) => yosoi::MeasuredCount::Known(proof.relevant_in_flight()),
        None => yosoi::MeasuredCount::Unavailable {
            reason: conversions::reason("voidcrawl.observation.settlement-in-flight-unavailable")?,
        },
    };
    yosoi::InFlightActivity::measured(total, relevant)
        .map_err(|_| VoidCrawlAdapterError::InvalidStaging)
}
