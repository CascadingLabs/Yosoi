use super::{BrowserExecutionManager, VoidCrawlAdapterError, config, conversions};
use crate as yosoi;
use std::{
    env,
    ffi::OsStr,
    future::Future,
    time::{Duration, Instant, SystemTime},
};
use tokio::time::{Instant as TokioInstant, sleep_until};
use tokio_util::sync::CancellationToken;
use void_crawl_core as provider;

mod attempt;
mod managed;
mod settlement;
mod snapshots;
mod staging_facts;
mod termination;

use attempt::run_owned_attempt;
use managed::{cleanup_completed, cleanup_receipt_for_error, managed_terminal_reason};
use snapshots::{merge_event_accounting, observation_event_accounting};
use termination::finish_attempt;

#[cfg(test)]
use super::VoidCrawlAdapterErrorCategory;
#[cfg(test)]
use managed::{
    cleanup_dispositions_for_error, terminal_reason_for_cleanup, terminal_reason_for_error,
    terminal_reason_for_manager_error,
};
#[cfg(test)]
use termination::add_observation_terminal;

#[cfg(test)]
#[path = "capture_tests.rs"]
mod tests;

const CLEANUP_GRACE: Duration = Duration::from_secs(5);

fn headful_display_configured(
    x11_display: Option<&OsStr>,
    wayland_display: Option<&OsStr>,
) -> bool {
    [x11_display, wayland_display]
        .into_iter()
        .flatten()
        .any(|display| !display.is_empty())
}

enum Phase<T> {
    Complete(T),
    Cancelled,
    Deadline,
}

fn cleanup_deadline(attempt_deadline: TokioInstant) -> TokioInstant {
    attempt_deadline
        .checked_add(CLEANUP_GRACE)
        .unwrap_or(attempt_deadline)
}

async fn close_session(session: &provider::BrowserSession, deadline: TokioInstant) -> bool {
    session.close_before(deadline).await.is_ok()
}

async fn bounded<T>(
    future: impl Future<Output = T>,
    cancellation: &CancellationToken,
    deadline: TokioInstant,
) -> Phase<T> {
    tokio::pin!(future);
    tokio::select! { biased; () = cancellation.cancelled() => Phase::Cancelled, () = sleep_until(deadline) => Phase::Deadline, value = &mut future => Phase::Complete(value) }
}

struct ProviderOutput {
    environment: provider::BrowserEnvironmentSnapshot,
    navigation: Option<provider::NavigationCaptureReport>,
    dom: Option<(provider::RenderedDomSnapshot, yosoi::CaptureOffset)>,
    accessibility: Option<(provider::AccessibilitySnapshot, yosoi::CaptureOffset)>,
    layout: Option<(provider::LayoutSnapshot, yosoi::CaptureOffset)>,
    visual: Option<(provider::VisualSnapshot, yosoi::CaptureOffset)>,
    navigation_completed: bool,
    settlement: Option<yosoi::SettlementEvidence>,
    observation: Option<provider::ObservationReport>,
    observation_failed: bool,
    navigation_failed: bool,
    observation_armed_at_micros: Option<u64>,
    navigation_armed_at_micros: Option<u64>,
    primary_terminal_reason: Option<yosoi::BrowserExecutionTerminalReason>,
}

fn provider_stop(error: &VoidCrawlAdapterError, navigation: bool) -> yosoi::BrowserProviderStop {
    match error {
        VoidCrawlAdapterError::Provider {
            code: "voidcrawl.browser.closed",
            ..
        } => yosoi::BrowserProviderStop::BrowserDisconnected,
        VoidCrawlAdapterError::Provider {
            code: "voidcrawl.renderer.crashed",
            ..
        } => yosoi::BrowserProviderStop::RendererFailure,
        VoidCrawlAdapterError::Provider { .. } if navigation => {
            yosoi::BrowserProviderStop::NavigationFailure
        }
        VoidCrawlAdapterError::InvalidEnvironment
        | VoidCrawlAdapterError::CapabilityMismatch
        | VoidCrawlAdapterError::EnvironmentMismatch { .. }
        | VoidCrawlAdapterError::EnvironmentNumberMismatch { .. } => {
            yosoi::BrowserProviderStop::InternalFailure
        }
        _ => yosoi::BrowserProviderStop::PageFailure,
    }
}

/// Runs one cancellation-aware, maximum-elapsed browser attempt. All provider
/// collectors and owned browser resources are finalized before this returns.
pub async fn capture_attempt(
    spec: &yosoi::ResolvedBrowserCaptureSpec,
    cancellation: &CancellationToken,
) -> Result<yosoi::BrowserAdapterResult, VoidCrawlAdapterError> {
    config::validate(spec)?;
    if matches!(spec.environment().mode(), yosoi::BrowserMode::Headful)
        && !headful_display_configured(
            env::var_os("DISPLAY").as_deref(),
            env::var_os("WAYLAND_DISPLAY").as_deref(),
        )
    {
        return Err(VoidCrawlAdapterError::HeadfulDisplayUnavailable);
    }
    let started_at: chrono::DateTime<chrono::Utc> = SystemTime::now().into();
    let started = Instant::now();
    let maximum = spec.observation().limits().maximum_elapsed();
    let lifecycle = yosoi::BoundedAcquisitionLifecycle::start(
        spec.request().capture_id(),
        spec.observation().clone(),
        started_at,
    );
    let boundary = yosoi::AttemptBoundary::new(
        started,
        yosoi::CaptureDuration::from_microseconds(maximum.as_microseconds()),
    )
    .map_err(|_| VoidCrawlAdapterError::InvalidResolvedSpec)?;
    let deadline = TokioInstant::from_std(boundary.deadline());
    // This is the attempt's only cleanup deadline. Stop-loading, collector
    // finalization, context disposal, and process close all consume it.
    let cleanup_deadline = cleanup_deadline(deadline);
    let mut builder = provider::BrowserSession::builder().cdp_mode(config::cdp_mode(spec));
    builder = match spec.environment().mode() {
        yosoi::BrowserMode::Headless => builder.headless(),
        yosoi::BrowserMode::Headful => builder.headful(),
    };
    let session = match bounded(builder.launch(), cancellation, deadline).await {
        Phase::Complete(Ok(value)) => value,
        Phase::Complete(Err(error)) => return Err(conversions::map_provider_error(&error)),
        Phase::Cancelled => return Err(VoidCrawlAdapterError::CancelledBeforeOwnership),
        Phase::Deadline => return Err(VoidCrawlAdapterError::DeadlineBeforeOwnership),
    };
    let context = match bounded(session.new_isolated_context(), cancellation, deadline).await {
        Phase::Complete(Ok(value)) => value,
        outcome => {
            let primary = match outcome {
                Phase::Complete(Err(error)) => conversions::map_provider_error(&error),
                Phase::Cancelled => VoidCrawlAdapterError::CancelledBeforeOwnership,
                Phase::Deadline => VoidCrawlAdapterError::DeadlineBeforeOwnership,
                Phase::Complete(Ok(_)) => return Err(VoidCrawlAdapterError::InvalidStaging),
            };
            return if close_session(&session, cleanup_deadline).await {
                Err(primary)
            } else {
                Err(VoidCrawlAdapterError::PrimaryAndCleanup {
                    primary: Box::new(primary),
                    cleanup: "session-close",
                })
            };
        }
    };
    let page = context.page();
    let operation = run_owned_attempt(
        spec,
        cancellation,
        page,
        boundary,
        deadline,
        cleanup_deadline,
    )
    .await;
    let disposed = context
        .dispose_before(cleanup_deadline)
        .await
        .cleanup_complete;
    let closed = close_session(&session, cleanup_deadline).await;
    let cleanup = if disposed && closed {
        yosoi::CleanupState::Complete
    } else {
        yosoi::CleanupState::Failed
    };
    finish_attempt(
        spec,
        cancellation,
        lifecycle,
        boundary,
        operation,
        cleanup,
        if disposed {
            "session-close"
        } else {
            "context-disposal"
        },
    )
}

/// Runs one capture through a reusable manager.
///
/// Ordinary managers preserve a fresh disposable-context boundary. A manager
/// explicitly bound to a managed profile uses a session-group lease so the
/// capture intentionally observes that profile's persistent browser state.
///
/// Every error after admission owns its complete terminal execution receipt and
/// exposes it through [`VoidCrawlAdapterError::execution_receipt`].
pub async fn capture_attempt_managed(
    manager: &BrowserExecutionManager,
    spec: &yosoi::ResolvedBrowserCaptureSpec,
    cancellation: &CancellationToken,
) -> Result<yosoi::BrowserAdapterResult, VoidCrawlAdapterError> {
    config::validate(spec)?;
    let headful = matches!(spec.environment().mode(), yosoi::BrowserMode::Headful);
    if headful
        && !headful_display_configured(
            env::var_os("DISPLAY").as_deref(),
            env::var_os("WAYLAND_DISPLAY").as_deref(),
        )
    {
        return Err(VoidCrawlAdapterError::HeadfulDisplayUnavailable);
    }
    if manager.config().headful != headful {
        return Err(VoidCrawlAdapterError::CapabilityMismatch);
    }

    let started_at: chrono::DateTime<chrono::Utc> = SystemTime::now().into();
    let started = Instant::now();
    let maximum = spec.observation().limits().maximum_elapsed();
    let lifecycle = yosoi::BoundedAcquisitionLifecycle::start(
        spec.request().capture_id(),
        spec.observation().clone(),
        started_at,
    );
    let boundary = yosoi::AttemptBoundary::new(
        started,
        yosoi::CaptureDuration::from_microseconds(maximum.as_microseconds()),
    )
    .map_err(|_| VoidCrawlAdapterError::InvalidResolvedSpec)?;
    let deadline = TokioInstant::from_std(boundary.deadline());
    let collector_cleanup_deadline = cleanup_deadline(deadline);
    let acquisition = async {
        if manager.is_managed_profile() {
            manager.acquire_session(cancellation).await
        } else {
            manager.acquire_independent(cancellation).await
        }
    };
    let lease = match bounded(acquisition, cancellation, deadline).await {
        Phase::Complete(Ok(lease)) => lease,
        Phase::Complete(Err(error)) => return Err(error.into()),
        Phase::Cancelled => return Err(VoidCrawlAdapterError::CancelledBeforeOwnership),
        Phase::Deadline => return Err(VoidCrawlAdapterError::DeadlineBeforeOwnership),
    };
    let admission = lease.admission().clone();
    let operation = match lease.initial_tab().page().await {
        Ok(page) => {
            run_owned_attempt(
                spec,
                cancellation,
                &page,
                boundary,
                deadline,
                collector_cleanup_deadline,
            )
            .await
        }
        Err(error) => Err(error.into()),
    };
    let cleanup = lease
        .release()
        .await
        .unwrap_or_else(|error| cleanup_receipt_for_error(admission.clone(), error));
    let accounting = lease.terminal_accounting_receipt().await?;
    let primary_terminal_reason = operation
        .as_ref()
        .ok()
        .and_then(|(output, _)| output.primary_terminal_reason);
    let cleanup_state = if cleanup_completed(&cleanup) {
        yosoi::CleanupState::Complete
    } else {
        yosoi::CleanupState::Failed
    };
    let finished = finish_attempt(
        spec,
        cancellation,
        lifecycle,
        boundary,
        operation,
        cleanup_state,
        "managed-context-release",
    );
    let reason = managed_terminal_reason(&finished, primary_terminal_reason, &cleanup);
    let terminal = yosoi::BrowserExecutionTerminalReceipt::new(admission, cleanup, reason)
        .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?;
    let receipt =
        yosoi::BrowserExecutionReceipt::new(spec.request().capture_id(), terminal, accounting)
            .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?;
    match finished {
        Ok(result) => result
            .with_execution(receipt)
            .map_err(VoidCrawlAdapterError::InvalidOutput),
        Err(primary) => Err(VoidCrawlAdapterError::ManagedExecution {
            primary: Box::new(primary),
            receipt: Box::new(receipt),
        }),
    }
}

/// Backwards-compatible successful controller capture.
pub async fn capture(
    spec: &yosoi::ResolvedBrowserCaptureSpec,
) -> Result<yosoi::BrowserAdapterFacts, VoidCrawlAdapterError> {
    let result = capture_attempt(spec, &CancellationToken::new()).await?;
    if !result.is_ready() {
        return Err(VoidCrawlAdapterError::AttemptStopped);
    }
    let (_, _, facts) = result.into_parts();
    Ok(facts)
}
