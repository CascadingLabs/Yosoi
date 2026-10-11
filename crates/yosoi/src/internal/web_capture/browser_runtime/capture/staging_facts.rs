mod source;
use source::{source_media_type, source_representation_and_decoded_source};
mod envelopes;
use super::super::{VoidCrawlAdapterError, config, conversions};
use super::{ProviderOutput, merge_event_accounting, observation_event_accounting};
use crate::internal::browser as provider;
use crate::internal::web_capture as yosoi;
use envelopes::{
    missing, retained_slot, retained_slot_with_producer, slot, structured_slot, unrequested,
};

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
