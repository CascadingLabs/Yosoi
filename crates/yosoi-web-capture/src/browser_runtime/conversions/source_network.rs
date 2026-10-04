use super::accounting_scope::{event_accounting, reason};
use crate as yosoi;
use crate::VoidCrawlAdapterError;
use std::collections::HashSet;
use void_crawl_core as provider;

mod challenge;

use challenge::admitted_main_document_headers;
pub use challenge::browser_challenge;

pub fn source(
    value: &provider::MainDocumentSource,
    at: yosoi::CaptureOffset,
    scope: yosoi::BrowserDocumentScope,
    admission: yosoi::BrowserMainBodyAdmission,
) -> Result<yosoi::ArtifactStagingOutcome, VoidCrawlAdapterError> {
    if value
        .body_layer
        .is_some_and(|layer| layer != provider::BrowserBodyLayer::DecodedRepresentation)
    {
        return Err(VoidCrawlAdapterError::InvalidStaging);
    }
    let mapping = yosoi::BrowserArtifactMapping::new(
        yosoi::BrowserStagingFamily::Artifact(yosoi::WebArtifactFamily::Source),
        yosoi::BrowserByteLayer::DecodedResponseBody,
    )
    .and_then(|mapping| mapping.with_snapshot(yosoi::BrowserSnapshotObservation::source(scope, at)))
    .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?;
    let outcome = if admission == yosoi::BrowserMainBodyAdmission::Omit {
        let observed = match value.complete_bytes {
            Some(value) => yosoi::MeasuredCount::Known(yosoi::ByteCount::new(
                u64::try_from(value).map_err(|_| VoidCrawlAdapterError::InvalidStaging)?,
            )),
            None => yosoi::MeasuredCount::Unavailable {
                reason: reason("voidcrawl.source.complete-size-unavailable")?,
            },
        };
        yosoi::AcquiredPayloadOutcome::discarded(
            observed,
            reason("yosoi.admission.main-body-omitted")?,
        )
        .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?
    } else {
        source_payload(value)?
    };
    yosoi::ArtifactStagingOutcome::acquired_payload(mapping, outcome)
        .map_err(|_| VoidCrawlAdapterError::InvalidStaging)
}

fn source_payload(
    value: &provider::MainDocumentSource,
) -> Result<yosoi::AcquiredPayloadOutcome, VoidCrawlAdapterError> {
    match value.body_state {
        provider::ResponseBodyState::Available => {
            let retained = u64::try_from(value.retained_bytes)
                .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?;
            let body_len = u64::try_from(value.body().len())
                .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?;
            if retained != body_len
                || value
                    .complete_bytes
                    .is_some_and(|complete| u64::try_from(complete) != Ok(retained))
            {
                return Err(VoidCrawlAdapterError::InvalidStaging);
            }
            yosoi::AcquiredPayloadOutcome::complete(value.body().to_vec())
                .map_err(|_| VoidCrawlAdapterError::InvalidStaging)
        }
        provider::ResponseBodyState::Truncated => {
            let retained = u64::try_from(value.retained_bytes)
                .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?;
            let observed = value
                .complete_bytes
                .and_then(|n| u64::try_from(n).ok())
                .ok_or(VoidCrawlAdapterError::InvalidStaging)?;
            let lost = observed
                .checked_sub(retained)
                .filter(|n| *n > 0)
                .ok_or(VoidCrawlAdapterError::InvalidStaging)?;
            yosoi::AcquiredPayloadOutcome::truncated(
                value.body().to_vec(),
                yosoi::ByteCount::new(observed),
                yosoi::MeasuredCount::Known(yosoi::ByteCount::new(lost)),
                reason("voidcrawl.source.byte-limit")?,
            )
            .map_err(|_| VoidCrawlAdapterError::InvalidStaging)
        }
        provider::ResponseBodyState::Unavailable => {
            source_unavailable_outcome(value.body_unavailable)
        }
    }
}

pub(super) fn source_unavailable_outcome(
    unavailable: Option<provider::SourceBodyUnavailableReason>,
) -> Result<yosoi::AcquiredPayloadOutcome, VoidCrawlAdapterError> {
    match unavailable {
        Some(provider::SourceBodyUnavailableReason::RequestFailed) => {
            yosoi::AcquiredPayloadOutcome::failed(reason("voidcrawl.source.request-failed")?)
                .map_err(|_| VoidCrawlAdapterError::InvalidStaging)
        }
        Some(provider::SourceBodyUnavailableReason::InvalidBase64) => {
            yosoi::AcquiredPayloadOutcome::failed(reason("voidcrawl.source.invalid-base64")?)
                .map_err(|_| VoidCrawlAdapterError::InvalidStaging)
        }
        Some(provider::SourceBodyUnavailableReason::CdpBodyUnavailable) => {
            yosoi::AcquiredPayloadOutcome::unavailable(reason(
                "voidcrawl.source.cdp-body-unavailable",
            )?)
            .map_err(|_| VoidCrawlAdapterError::InvalidStaging)
        }
        Some(provider::SourceBodyUnavailableReason::CaptureEndedBeforeBody) => {
            yosoi::AcquiredPayloadOutcome::unavailable(reason(
                "voidcrawl.source.capture-ended-before-body",
            )?)
            .map_err(|_| VoidCrawlAdapterError::InvalidStaging)
        }
        None => yosoi::AcquiredPayloadOutcome::unavailable(reason(
            "voidcrawl.source.provider-did-not-report",
        )?)
        .map_err(|_| VoidCrawlAdapterError::InvalidStaging),
    }
}

pub fn network(
    report: provider::NavigationCaptureReport,
    admission: yosoi::BrowserEvidenceAdmissionPolicy,
    navigation_armed_at_micros: u64,
    observed_through: yosoi::CaptureOffset,
) -> Result<(yosoi::ArtifactStagingOutcome, yosoi::EventAccounting), VoidCrawlAdapterError> {
    if !report.cleanup_complete {
        return Err(VoidCrawlAdapterError::InvalidStaging);
    }
    let event_accounting =
        navigation_event_accounting(&report, navigation_armed_at_micros, observed_through)?;
    let retained =
        u64::try_from(report.resources.len()).map_err(|_| VoidCrawlAdapterError::InvalidStaging)?;
    let admitted_resources = retained
        .checked_add(report.resources_dropped)
        .ok_or(VoidCrawlAdapterError::InvalidStaging)?;
    let resource_loss = if report.additional_loss_unknown {
        yosoi::LossExtent::Unknown
    } else {
        yosoi::LossExtent::Known(report.resources_dropped)
    };
    let resource_accounting =
        yosoi::BrowserResourceAccounting::new(admitted_resources, retained, resource_loss)
            .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?;
    let admit_urls = admission.urls() == yosoi::BrowserUrlAdmission::AdmitNetworkUrls;
    let requested_url = if admit_urls {
        report
            .requested_url
            .as_ref()
            .map(|v| yosoi::ResolvedWebUrl::parse(v.as_str()))
            .transpose()
            .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?
    } else {
        None
    };
    let final_url = if admit_urls {
        report
            .final_url
            .as_ref()
            .map(|v| yosoi::ResolvedWebUrl::parse(v.as_str()))
            .transpose()
            .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?
    } else {
        None
    };
    let main_document = report
        .main_document
        .as_ref()
        .map(|main| {
            Ok::<_, VoidCrawlAdapterError>(yosoi::BrowserMainDocumentFact {
                resource: main.resource_id,
                url: if admit_urls {
                    Some(
                        yosoi::ResolvedWebUrl::parse(main.url.as_str())
                            .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?,
                    )
                } else {
                    None
                },
                status: main.status,
                headers: admitted_main_document_headers(&main.headers, admission.headers())
                    .unwrap_or_default(),
                mime_type: main.mime_type.clone(),
                from_cache: main.from_cache,
                from_service_worker: main.from_service_worker,
            })
        })
        .transpose()?;
    let redirects = report
        .redirects
        .iter()
        .map(|hop| yosoi::BrowserRedirectFact {
            from: hop.from,
            to: hop.to,
            status: hop.status,
        })
        .collect();
    let mut document_resources = HashSet::new();
    if let Some(main) = &report.main_document {
        document_resources.insert(main.resource_id);
        for hop in report.redirects.iter().rev() {
            if document_resources.contains(&hop.to) {
                document_resources.insert(hop.from);
            }
        }
    }
    let mut provider_events = Vec::new();
    for event in &report.events {
        let at = navigation_armed_at_micros
            .checked_add(event.offset_micros)
            .ok_or(VoidCrawlAdapterError::InvalidStaging)?;
        let at = yosoi::CaptureOffset::from_microseconds(at);
        if at > observed_through {
            break;
        }
        provider_events.push(yosoi::BrowserObservationFact {
            sequence: event.sequence,
            at,
            kind: match event.kind {
                provider::NavigationEventKind::Request
                    if event
                        .resource_id
                        .is_some_and(|id| document_resources.contains(&id)) =>
                {
                    yosoi::BrowserObservationKind::DocumentRequestStarted
                }
                provider::NavigationEventKind::Request => {
                    yosoi::BrowserObservationKind::ResourceRequestStarted
                }
                provider::NavigationEventKind::Response => {
                    yosoi::BrowserObservationKind::ResponseReceived
                }
                provider::NavigationEventKind::Finished => {
                    yosoi::BrowserObservationKind::RequestFinished
                }
                provider::NavigationEventKind::Failed => {
                    yosoi::BrowserObservationKind::RequestFailed
                }
            },
            resource: event.resource_id,
        });
    }
    let resources = report
        .resources
        .into_iter()
        .map(|r| {
            Ok(yosoi::BrowserResourceFact {
                id: r.id,
                redirect_from: r.redirect_from,
                // Provider frame and loader identifiers are capture-local opaque
                // identifiers, not Yosoi document epochs. Preserve no scope rather
                // than inventing a cross-model identity relationship.
                scope: None,
                url: if admit_urls {
                    Some(
                        yosoi::ResolvedWebUrl::parse(r.url.as_str())
                            .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?,
                    )
                } else {
                    None
                },
                status: r.status,
                outcome: r.outcome,
                from_cache: r.from_cache,
                from_service_worker: r.from_service_worker,
                encoded_data_length: r.encoded_data_length,
            })
        })
        .collect::<Result<Vec<_>, VoidCrawlAdapterError>>()?;
    let filtered_events = report
        .events_retained
        .checked_sub(event_accounting.retained().get())
        .ok_or(VoidCrawlAdapterError::InvalidStaging)?;
    let outcome = yosoi::ArtifactStagingOutcome::structured(
        yosoi::BrowserStructuredEvidence::Network {
            requested_url,
            final_url,
            redirects,
            main_document,
            extra_info: yosoi::BrowserExtraInfoEvidence::UnavailableInCurrentClient,
            resources,
            events: provider_events,
            resource_accounting,
            event_accounting: event_accounting.clone(),
        },
        if report.additional_loss_unknown
            || report.resources_dropped > 0
            || filtered_events > 0
            || !matches!(
                report.events_dropped,
                provider::MeasuredCount::Known { value: 0 }
            )
        {
            Some(reason("voidcrawl.network.bounded-loss")?)
        } else {
            None
        },
    )
    .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?;
    Ok((outcome, event_accounting))
}

pub fn navigation_event_accounting(
    report: &provider::NavigationCaptureReport,
    navigation_armed_at_micros: u64,
    observed_through: yosoi::CaptureOffset,
) -> Result<yosoi::EventAccounting, VoidCrawlAdapterError> {
    let retained_events = report.events.iter().try_fold(0_u64, |retained, event| {
        let at = navigation_armed_at_micros
            .checked_add(event.offset_micros)
            .ok_or(VoidCrawlAdapterError::InvalidStaging)?;
        if at <= observed_through.as_microseconds() {
            retained
                .checked_add(1)
                .ok_or(VoidCrawlAdapterError::InvalidStaging)
        } else {
            Ok(retained)
        }
    })?;
    let filtered_events = report
        .events_retained
        .checked_sub(retained_events)
        .ok_or(VoidCrawlAdapterError::InvalidStaging)?;
    let dropped_events = if report.additional_loss_unknown {
        provider::MeasuredCount::Unavailable {
            reason: provider::MeasurementUnavailableReason::ProviderDidNotReport,
        }
    } else {
        match report.events_dropped {
            provider::MeasuredCount::Known { value } => provider::MeasuredCount::Known {
                value: value
                    .checked_add(filtered_events)
                    .ok_or(VoidCrawlAdapterError::InvalidStaging)?,
            },
            unavailable @ provider::MeasuredCount::Unavailable { .. } => unavailable,
        }
    };
    event_accounting(report.events_admitted, retained_events, dropped_events)
}
