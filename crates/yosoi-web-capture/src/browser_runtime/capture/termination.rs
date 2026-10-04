use super::super::{VoidCrawlAdapterError, conversions};
use super::{ProviderOutput, staging_facts};
use crate as yosoi;
use tokio_util::sync::CancellationToken;
use void_crawl_core as provider;

pub(super) fn finish_attempt(
    spec: &yosoi::ResolvedBrowserCaptureSpec,
    cancellation: &CancellationToken,
    lifecycle: yosoi::BoundedAcquisitionLifecycle,
    boundary: yosoi::AttemptBoundary,
    operation: Result<
        (ProviderOutput, Vec<yosoi::BrowserTerminalCandidate>),
        VoidCrawlAdapterError,
    >,
    cleanup: yosoi::CleanupState,
    cleanup_failure: &'static str,
) -> Result<yosoi::BrowserAdapterResult, VoidCrawlAdapterError> {
    let (output, mut candidates) = match operation {
        Ok(value) => value,
        Err(primary) => {
            return Err(if cleanup == yosoi::CleanupState::Complete {
                primary
            } else {
                VoidCrawlAdapterError::PrimaryAndCleanup {
                    primary: Box::new(primary),
                    cleanup: cleanup_failure,
                }
            });
        }
    };
    add_observation_terminal(
        output.observation.as_ref(),
        output.observation_armed_at_micros,
        output.navigation.as_ref(),
        output.navigation_armed_at_micros,
        cancellation,
        &mut candidates,
    )?;
    if cleanup == yosoi::CleanupState::Failed {
        candidates.retain(|candidate| {
            !matches!(
                candidate.signal(),
                yosoi::BrowserTerminalSignal::ControllerCompleted
                    | yosoi::BrowserTerminalSignal::QuietSettled
            )
        });
        candidates.push(yosoi::BrowserTerminalCandidate::new(
            boundary
                .elapsed()
                .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?,
            yosoi::BrowserTerminalSignal::CleanupFailed,
        ));
    }
    let terminal =
        yosoi::resolve_browser_terminal(&candidates, spec.observation().limits().maximum_elapsed())
            .ok_or(VoidCrawlAdapterError::InvalidStaging)?;
    let facts = staging_facts::into_facts(spec, output, terminal.at(), cleanup)?;
    if matches!(
        terminal.kind(),
        yosoi::BrowserTerminalKind::ControllerCompleted | yosoi::BrowserTerminalKind::QuietSettled
    ) {
        yosoi::BrowserAdapterResult::ready_for_finalization(terminal, facts)
            .and_then(|result| result.with_lifecycle(lifecycle))
            .map_err(VoidCrawlAdapterError::InvalidOutput)
    } else {
        yosoi::BrowserAdapterResult::stopped(terminal, facts)
            .and_then(|result| result.with_lifecycle(lifecycle))
            .map_err(VoidCrawlAdapterError::InvalidOutput)
    }
}

pub(super) fn candidate(
    boundary: yosoi::AttemptBoundary,
    signal: yosoi::BrowserTerminalSignal,
) -> Result<yosoi::BrowserTerminalCandidate, VoidCrawlAdapterError> {
    Ok(yosoi::BrowserTerminalCandidate::new(
        boundary
            .elapsed()
            .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?,
        signal,
    ))
}

pub(super) fn caller_cancelled() -> Result<yosoi::BrowserTerminalSignal, VoidCrawlAdapterError> {
    Ok(yosoi::BrowserTerminalSignal::CallerInterrupted {
        reason: conversions::reason("yosoi.browser.caller-cancelled")?,
    })
}

pub(super) fn add_observation_terminal(
    observation: Option<&provider::ObservationReport>,
    observation_armed_at_micros: Option<u64>,
    navigation: Option<&provider::NavigationCaptureReport>,
    navigation_armed_at_micros: Option<u64>,
    cancellation: &CancellationToken,
    candidates: &mut Vec<yosoi::BrowserTerminalCandidate>,
) -> Result<(), VoidCrawlAdapterError> {
    if let Some(observation) = observation {
        let signal = match observation.termination {
            provider::ObservationTermination::EventLimitReached => {
                Some(yosoi::BrowserTerminalSignal::EventLimitReached)
            }
            provider::ObservationTermination::DeadlineReached => {
                Some(yosoi::BrowserTerminalSignal::DeadlineReached)
            }
            provider::ObservationTermination::ProviderDisconnected => {
                Some(yosoi::BrowserTerminalSignal::ProviderFailed {
                    reason: yosoi::BrowserProviderStop::BrowserDisconnected,
                })
            }
            provider::ObservationTermination::Cancelled if cancellation.is_cancelled() => {
                Some(caller_cancelled()?)
            }
            _ => None,
        };
        if let Some(signal) = signal {
            let relative_at = if matches!(
                observation.termination,
                provider::ObservationTermination::EventLimitReached
            ) {
                observation
                    .events
                    .last()
                    .map_or(observation.elapsed_micros, |event| event.offset_micros)
            } else {
                observation.elapsed_micros
            };
            let at = observation_armed_at_micros
                .and_then(|armed_at| armed_at.checked_add(relative_at))
                .ok_or(VoidCrawlAdapterError::InvalidStaging)?;
            candidates.push(yosoi::BrowserTerminalCandidate::new(
                yosoi::CaptureOffset::from_microseconds(at),
                signal,
            ));
        }
    }
    add_navigation_terminal(
        navigation,
        navigation_armed_at_micros,
        cancellation,
        candidates,
    )
}

fn add_navigation_terminal(
    report: Option<&provider::NavigationCaptureReport>,
    armed_at: Option<u64>,
    cancellation: &CancellationToken,
    candidates: &mut Vec<yosoi::BrowserTerminalCandidate>,
) -> Result<(), VoidCrawlAdapterError> {
    let (Some(report), Some(armed_at)) = (report, armed_at) else {
        return Ok(());
    };
    let signal = match report.termination {
        provider::NavigationCaptureTermination::EventLimitReached => {
            Some(yosoi::BrowserTerminalSignal::EventLimitReached)
        }
        provider::NavigationCaptureTermination::ProviderDisconnected => {
            Some(yosoi::BrowserTerminalSignal::ProviderFailed {
                reason: yosoi::BrowserProviderStop::BrowserDisconnected,
            })
        }
        provider::NavigationCaptureTermination::DeadlineReached => {
            Some(yosoi::BrowserTerminalSignal::DeadlineReached)
        }
        provider::NavigationCaptureTermination::Cancelled if cancellation.is_cancelled() => {
            Some(caller_cancelled()?)
        }
        _ => None,
    };
    if let Some(signal) = signal {
        let at = armed_at
            .checked_add(report.elapsed_micros)
            .ok_or(VoidCrawlAdapterError::InvalidStaging)?;
        candidates.push(yosoi::BrowserTerminalCandidate::new(
            yosoi::CaptureOffset::from_microseconds(at),
            signal,
        ));
    }
    Ok(())
}
