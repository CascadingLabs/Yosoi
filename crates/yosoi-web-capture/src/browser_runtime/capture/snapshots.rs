use super::super::{VoidCrawlAdapterError, config, conversions};
use super::termination::{caller_cancelled, candidate};
use super::{Phase, bounded};
use crate as yosoi;
use tokio::time::Instant as TokioInstant;
use tokio_util::sync::CancellationToken;
use void_crawl_core as provider;

pub(super) fn merge_event_accounting(
    observation: &yosoi::EventAccounting,
    network: &yosoi::EventAccounting,
) -> Result<yosoi::EventAccounting, VoidCrawlAdapterError> {
    yosoi::EventAccounting::new(
        yosoi::EventCount::new(observation.admitted().get().max(network.admitted().get())),
        yosoi::EventCount::new(observation.retained().get().max(network.retained().get())),
        yosoi::MeasuredCount::Unavailable {
            reason: conversions::reason("voidcrawl.events.overlapping-collectors")?,
        },
    )
    .map_err(|_| VoidCrawlAdapterError::InvalidStaging)
}

pub(super) fn observation_event_accounting(
    value: &provider::ObservationCountAccounting,
) -> Result<yosoi::EventAccounting, VoidCrawlAdapterError> {
    let exact = |count| match count {
        provider::MeasuredCount::Known { value } => Ok(yosoi::EventCount::new(value)),
        provider::MeasuredCount::Unavailable { .. } => Err(VoidCrawlAdapterError::InvalidStaging),
    };
    let dropped = match value.dropped {
        provider::MeasuredCount::Known { value } => {
            yosoi::MeasuredCount::Known(yosoi::EventCount::new(value))
        }
        provider::MeasuredCount::Unavailable { reason } => yosoi::MeasuredCount::Unavailable {
            reason: conversions::reason(match reason {
                provider::MeasurementUnavailableReason::NotCollected => {
                    "voidcrawl.observation.not-collected"
                }
                provider::MeasurementUnavailableReason::ProviderDidNotReport => {
                    "voidcrawl.observation.provider-did-not-report"
                }
            })?,
        },
    };
    yosoi::EventAccounting::new(exact(value.admitted)?, exact(value.retained)?, dropped)
        .map_err(|_| VoidCrawlAdapterError::InvalidStaging)
}

#[allow(
    clippy::too_many_arguments,
    reason = "snapshot bounds and owned output slots remain explicit at the concrete adapter boundary"
)]
pub(super) async fn snapshot_requested(
    spec: &yosoi::ResolvedBrowserCaptureSpec,
    cancellation: &CancellationToken,
    page: &provider::Page,
    mut observation: Option<&mut provider::ObservationScope>,
    observation_armed_at_micros: Option<u64>,
    boundary: yosoi::AttemptBoundary,
    deadline: TokioInstant,
    dom: &mut Option<(provider::RenderedDomSnapshot, yosoi::CaptureOffset)>,
    accessibility: &mut Option<(provider::AccessibilitySnapshot, yosoi::CaptureOffset)>,
    layout: &mut Option<(provider::LayoutSnapshot, yosoi::CaptureOffset)>,
    visual: &mut Option<(provider::VisualSnapshot, yosoi::CaptureOffset)>,
    candidates: &mut Vec<yosoi::BrowserTerminalCandidate>,
) -> Result<(), VoidCrawlAdapterError> {
    macro_rules! snapshot {
        ($target:expr, $future:expr) => {
            if let Some(checkpoint) = observation
                .as_deref_mut()
                .and_then(provider::ObservationScope::checkpoint)
                && let Some(signal) = observation_checkpoint_signal(checkpoint)
            {
                let at = if checkpoint.renderer_crashed {
                    boundary
                        .elapsed()
                        .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?
                        .as_microseconds()
                } else {
                    observation_armed_at_micros
                        .and_then(|armed_at| {
                            armed_at.checked_add(checkpoint.last_event_offset_micros)
                        })
                        .ok_or(VoidCrawlAdapterError::InvalidStaging)?
                };
                candidates.push(yosoi::BrowserTerminalCandidate::new(
                    yosoi::CaptureOffset::from_microseconds(at),
                    signal,
                ));
                return Ok(());
            }
            match bounded($future, cancellation, deadline).await {
                Phase::Complete(Ok(value)) => {
                    let at = boundary
                        .elapsed()
                        .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?;
                    *$target = Some((value, at));
                }
                Phase::Complete(Err(_error)) => {
                    // Snapshot-family provider failures are local. Leave this family
                    // unavailable and continue attempting independent siblings.
                }
                Phase::Cancelled => {
                    candidates.push(candidate(boundary, caller_cancelled()?)?);
                    return Ok(());
                }
                Phase::Deadline => {
                    candidates.push(candidate(
                        boundary,
                        yosoi::BrowserTerminalSignal::DeadlineReached,
                    )?);
                    return Ok(());
                }
            }
        };
    }
    let artifacts = spec.artifacts();
    if artifacts.rendered_dom() != yosoi::ArtifactRequest::NotRequested {
        snapshot!(
            dom,
            page.rendered_dom_snapshot(config::byte_limit(
                spec,
                yosoi::BrowserByteDomain::RenderedDomUtf8,
            )?)
        );
        if dom
            .as_ref()
            .is_some_and(|(value, _)| value.state == provider::SnapshotState::Truncated)
        {
            // Per-family truncation is retained without terminating sibling capture.
        }
    }
    if artifacts.accessibility_tree() != yosoi::ArtifactRequest::NotRequested {
        snapshot!(
            accessibility,
            page.accessibility_snapshot(provider::AccessibilitySnapshotOptions {
                depth: None,
                max_nodes: usize::try_from(spec.bounds().max_accessibility_nodes().get())
                    .map_err(|_| VoidCrawlAdapterError::InvalidResolvedSpec)?,
                max_bytes: config::byte_limit(
                    spec,
                    yosoi::BrowserByteDomain::AccessibilityJsonUtf8
                )?,
            })
        );
        if accessibility
            .as_ref()
            .is_some_and(|(value, _)| value.state == provider::SnapshotState::Truncated)
        {
            // Per-family truncation is retained without terminating sibling capture.
        }
    }
    // These are intentionally separate factual observations. A shared document
    // epoch permits pairing but does not imply simultaneous measurement.
    if artifacts.layout() != yosoi::ArtifactRequest::NotRequested {
        snapshot!(layout, page.layout_snapshot());
    }
    if artifacts.visual() != yosoi::ArtifactRequest::NotRequested {
        snapshot!(
            visual,
            page.visual_snapshot(provider::ScreenshotOptions::default().viewport_only())
        );
    }
    Ok(())
}

const fn observation_checkpoint_signal(
    checkpoint: provider::ObservationCheckpoint,
) -> Option<yosoi::BrowserTerminalSignal> {
    if checkpoint.renderer_crashed {
        return Some(yosoi::BrowserTerminalSignal::ProviderFailed {
            reason: yosoi::BrowserProviderStop::RendererFailure,
        });
    }
    match checkpoint.termination {
        Some(provider::ObservationTermination::EventLimitReached) => {
            Some(yosoi::BrowserTerminalSignal::EventLimitReached)
        }
        Some(provider::ObservationTermination::DeadlineReached) => {
            Some(yosoi::BrowserTerminalSignal::DeadlineReached)
        }
        Some(provider::ObservationTermination::ProviderDisconnected) => {
            Some(yosoi::BrowserTerminalSignal::ProviderFailed {
                reason: yosoi::BrowserProviderStop::BrowserDisconnected,
            })
        }
        _ => None,
    }
}
