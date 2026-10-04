use super::super::{VoidCrawlAdapterError, conversions};
use super::managed::terminal_reason_for_error;
use super::settlement::{push_quiet_failure, settlement_evidence, wait_for_quiet};
use super::snapshots::snapshot_requested;
use super::termination::{caller_cancelled, candidate};
use super::{Phase, ProviderOutput, bounded, provider_stop};
use crate as yosoi;
use std::num::NonZeroUsize;
use tokio::{
    join,
    time::{Instant as TokioInstant, timeout_at},
};
use tokio_util::sync::CancellationToken;
use void_crawl_core as provider;

mod arming;
use arming::ArmedAttempt;

#[allow(
    clippy::cognitive_complexity,
    reason = "attempt orchestration keeps cancellation, deadline, cleanup, and terminal ordering explicit"
)]
pub(super) async fn run_owned_attempt(
    spec: &yosoi::ResolvedBrowserCaptureSpec,
    cancellation: &CancellationToken,
    page: &provider::Page,
    boundary: yosoi::AttemptBoundary,
    deadline: TokioInstant,
    cleanup_deadline: TokioInstant,
) -> Result<(ProviderOutput, Vec<yosoi::BrowserTerminalCandidate>), VoidCrawlAdapterError> {
    let ArmedAttempt {
        max_events,
        needs_observation,
        observation_armed_at_micros,
        observation_setup_failed,
        mut observation,
        navigation_armed_at_micros,
        mut navigation,
        mut primary_terminal_reason,
        mut candidates,
    } = arming::initialize_and_arm_collectors(spec, cancellation, page, boundary, deadline).await?;

    // Minimal-mode domains are enabled lazily by collector arming. Observe and
    // certify the effective environment only after every required domain has
    // been armed, but still before navigation can emit evidence.
    let environment = match bounded(page.environment_snapshot(), cancellation, deadline).await {
        Phase::Complete(Ok(value)) => value,
        Phase::Complete(Err(error)) => return Err(conversions::map_provider_error(&error)),
        Phase::Cancelled => return Err(VoidCrawlAdapterError::CancelledBeforeStaging),
        Phase::Deadline => return Err(VoidCrawlAdapterError::DeadlineBeforeStaging),
    };
    conversions::verify_environment(&environment, spec.environment(), spec.capabilities())?;

    let navigation_completed = if candidates.is_empty() {
        let navigation = async {
            match spec.navigation_policy().completion() {
                yosoi::NavigationCompletionPolicy::DomContentLoaded => {
                    let capacity = NonZeroUsize::new(max_events).ok_or(
                        provider::VoidCrawlError::InvalidInput {
                            operation: "navigate_until_dom_content_loaded",
                            reason: "progress capacity must be positive",
                        },
                    )?;
                    page.navigate_until_dom_content_loaded(
                        spec.target().as_str(),
                        provider::ActiveNavigationOptions::new(
                            capacity,
                            deadline.saturating_duration_since(TokioInstant::now()),
                        ),
                    )
                    .await
                }
                yosoi::NavigationCompletionPolicy::ControllerCompleted => {
                    page.navigate(spec.target().as_str()).await
                }
                yosoi::NavigationCompletionPolicy::LoadEvent
                | yosoi::NavigationCompletionPolicy::NetworkIdle => {
                    Err(provider::VoidCrawlError::InvalidInput {
                        operation: "browser_capture_navigation",
                        reason: "navigation completion mode is unsupported",
                    })
                }
            }
        };
        match bounded(navigation, cancellation, deadline).await {
            Phase::Complete(Ok(())) => true,
            Phase::Complete(Err(error)) => {
                let mapped = conversions::map_provider_error(&error);
                primary_terminal_reason = Some(terminal_reason_for_error(&mapped));
                candidates.push(candidate(
                    boundary,
                    yosoi::BrowserTerminalSignal::ProviderFailed {
                        reason: provider_stop(&mapped, true),
                    },
                )?);
                false
            }
            Phase::Cancelled => {
                candidates.push(candidate(boundary, caller_cancelled()?)?);
                false
            }
            Phase::Deadline => {
                candidates.push(candidate(
                    boundary,
                    yosoi::BrowserTerminalSignal::DeadlineReached,
                )?);
                false
            }
        }
    } else {
        false
    };

    let mut dom = None;
    let mut accessibility = None;
    let mut layout = None;
    let mut visual = None;
    let mut settlement = None;
    if candidates.is_empty()
        && let yosoi::SettlementPolicy::QuietPeriod(policy) = spec.observation().settlement()
    {
        let Some(observation) = observation.as_mut() else {
            return Err(VoidCrawlAdapterError::InvalidStaging);
        };
        match wait_for_quiet(observation, policy, cancellation, deadline).await {
            Phase::Complete(Ok(_)) => {}
            outcome => push_quiet_failure(outcome, boundary, &mut candidates)?,
        }
    }
    if candidates.is_empty() {
        snapshot_requested(
            spec,
            cancellation,
            page,
            observation.as_mut(),
            observation_armed_at_micros,
            boundary,
            deadline,
            &mut dom,
            &mut accessibility,
            &mut layout,
            &mut visual,
            &mut candidates,
        )
        .await?;
    }
    if candidates.is_empty() {
        match spec.observation().settlement() {
            yosoi::SettlementPolicy::Disabled => {}
            yosoi::SettlementPolicy::QuietPeriod(policy) => {
                let (Some(observation), Some(armed_at)) =
                    (observation.as_mut(), observation_armed_at_micros)
                else {
                    return Err(VoidCrawlAdapterError::InvalidStaging);
                };
                match wait_for_quiet(observation, policy, cancellation, deadline).await {
                    Phase::Complete(Ok(proof)) => {
                        let evidence = settlement_evidence(policy, &proof, armed_at)?;
                        let at = evidence.satisfied_at();
                        settlement = Some(evidence);
                        candidates.push(yosoi::BrowserTerminalCandidate::new(
                            at,
                            yosoi::BrowserTerminalSignal::QuietSettled,
                        ));
                    }
                    outcome => push_quiet_failure(outcome, boundary, &mut candidates)?,
                }
            }
        }
    }

    let interrupted = cancellation.is_cancelled()
        || candidates.iter().any(|value| {
            matches!(
                value.signal(),
                yosoi::BrowserTerminalSignal::DeadlineReached
                    | yosoi::BrowserTerminalSignal::CallerInterrupted { .. }
            )
        });
    if interrupted {
        let _ = timeout_at(cleanup_deadline, page.stop_loading()).await;
    }
    let observation_finalization = async move {
        match observation {
            Some(observation) => Some(
                timeout_at(cleanup_deadline, async {
                    if interrupted {
                        observation.cancel().await
                    } else {
                        observation.finish().await
                    }
                })
                .await,
            ),
            None => None,
        }
    };
    let navigation_finalization = async move {
        match navigation.take() {
            Some(value) => Some(
                timeout_at(cleanup_deadline, async {
                    if interrupted {
                        value.cancel().await
                    } else {
                        value.finish().await
                    }
                })
                .await,
            ),
            None => None,
        }
    };
    // Both collectors receive the full remaining opportunity under the same
    // fixed cleanup deadline; one stalled sibling cannot starve the other.
    let (observation_result, navigation_result) =
        join!(observation_finalization, navigation_finalization);
    let observation_requested = observation_result.is_some();
    let observation_renderer_crashed = matches!(
        observation_result.as_ref(),
        Some(Ok(Err(provider::VoidCrawlError::RendererCrashed)))
    );
    let observation_report_collected = observation_result
        .as_ref()
        .is_some_and(|result| matches!(result, Ok(Ok(_))));
    let observation_report = if needs_observation {
        observation_result.and_then(Result::ok).and_then(Result::ok)
    } else {
        None
    };
    let observation_failed = observation_setup_failed
        || (observation_requested
            && !observation_report_collected
            && !observation_renderer_crashed);
    let navigation_requested = navigation_result.is_some();
    let navigation_report = navigation_result.and_then(Result::ok).and_then(Result::ok);
    let navigation_failed = navigation_requested && navigation_report.is_none();
    if observation_renderer_crashed
        && !candidates.iter().any(|value| {
            matches!(
                value.signal(),
                yosoi::BrowserTerminalSignal::ProviderFailed {
                    reason: yosoi::BrowserProviderStop::RendererFailure,
                }
            )
        })
    {
        primary_terminal_reason = Some(yosoi::BrowserExecutionTerminalReason::ProviderFailure);
        candidates.push(candidate(
            boundary,
            yosoi::BrowserTerminalSignal::ProviderFailed {
                reason: yosoi::BrowserProviderStop::RendererFailure,
            },
        )?);
    }
    if (observation_failed || navigation_failed) && !observation_renderer_crashed {
        candidates.push(candidate(
            boundary,
            yosoi::BrowserTerminalSignal::ProviderFailed {
                reason: yosoi::BrowserProviderStop::InternalFailure,
            },
        )?);
    }
    if candidates.is_empty()
        && matches!(
            spec.observation().settlement(),
            yosoi::SettlementPolicy::Disabled
        )
    {
        candidates.push(candidate(
            boundary,
            yosoi::BrowserTerminalSignal::ControllerCompleted,
        )?);
    }
    Ok((
        ProviderOutput {
            environment,
            navigation: navigation_report,
            dom,
            accessibility,
            layout,
            visual,
            navigation_completed,
            settlement,
            observation: observation_report,
            observation_failed,
            navigation_failed,
            observation_armed_at_micros,
            navigation_armed_at_micros,
            primary_terminal_reason,
        },
        candidates,
    ))
}
