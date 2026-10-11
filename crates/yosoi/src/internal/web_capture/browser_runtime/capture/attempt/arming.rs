use super::super::super::{VoidCrawlAdapterError, config, conversions, overrides};
use super::super::managed::terminal_reason_for_error;
use super::super::termination::{caller_cancelled, candidate};
use super::super::{Phase, bounded, provider_stop};
use crate::internal::browser as provider;
use crate::internal::web_capture as yosoi;
use std::future::Future;
use tokio::time::Instant as TokioInstant;
use tokio_util::sync::CancellationToken;

pub(super) struct ArmedAttempt {
    pub(super) max_events: usize,
    pub(super) needs_observation: bool,
    pub(super) observation_armed_at_micros: Option<u64>,
    pub(super) observation_setup_failed: bool,
    pub(super) observation: Option<provider::ObservationScope>,
    pub(super) navigation_armed_at_micros: Option<u64>,
    pub(super) navigation: Option<provider::NavigationCapture>,
    pub(super) primary_terminal_reason: Option<yosoi::BrowserExecutionTerminalReason>,
    pub(super) candidates: Vec<yosoi::BrowserTerminalCandidate>,
}

pub(super) async fn initialize_and_arm_collectors(
    spec: &yosoi::ResolvedBrowserCaptureSpec,
    cancellation: &CancellationToken,
    page: &provider::Page,
    boundary: yosoi::AttemptBoundary,
    deadline: TokioInstant,
) -> Result<ArmedAttempt, VoidCrawlAdapterError> {
    run_initialization(
        overrides::apply(page, spec.environment().overrides()),
        cancellation,
        deadline,
    )
    .await?;
    let artifacts = spec.artifacts();
    let instrumentation_needs = config::instrumentation_needs(spec);
    let collect_network_observation = artifacts.network() != yosoi::ArtifactRequest::NotRequested
        || matches!(
            spec.observation().settlement(),
            yosoi::SettlementPolicy::QuietPeriod(_)
        );

    let max_events = usize::try_from(spec.bounds().max_events().get())
        .map_err(|_| VoidCrawlAdapterError::InvalidResolvedSpec)?;
    let max_resources = usize::try_from(spec.bounds().max_resources().get())
        .map_err(|_| VoidCrawlAdapterError::InvalidResolvedSpec)?;
    let needs_observation = collect_network_observation || instrumentation_needs.runtime;
    let mut primary_terminal_reason = None;
    let mut candidates = Vec::new();
    let observation_armed_at_micros = if needs_observation {
        Some(
            boundary
                .elapsed()
                .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?
                .as_microseconds(),
        )
    } else {
        None
    };
    // ObservationScope also watches the page's renderer signal when all
    // ordinary collectors are disabled. Every capture therefore wakes on a
    // factual renderer crash without enabling extra CDP domains or changing
    // artifact accounting.
    let observation = match bounded(
        page.arm_observation(provider::ObservationOptions {
            collect_network: collect_network_observation,
            collect_console: instrumentation_needs.runtime,
            collect_exceptions: instrumentation_needs.runtime,
            max_events,
            max_diagnostic_bytes: if artifacts.runtime_diagnostics()
                == yosoi::ArtifactRequest::NotRequested
            {
                1
            } else {
                config::byte_limit(spec, yosoi::BrowserByteDomain::RuntimeDiagnosticUtf8)?
            },
            max_duration: deadline.saturating_duration_since(TokioInstant::now()),
        }),
        cancellation,
        deadline,
    )
    .await
    {
        Phase::Complete(Ok(value)) => Some(value),
        Phase::Complete(Err(error)) => {
            let mapped = conversions::map_provider_error(&error);
            primary_terminal_reason = Some(terminal_reason_for_error(&mapped));
            candidates.push(candidate(
                boundary,
                yosoi::BrowserTerminalSignal::ProviderFailed {
                    reason: provider_stop(&mapped, false),
                },
            )?);
            None
        }
        Phase::Cancelled => {
            candidates.push(candidate(boundary, caller_cancelled()?)?);
            None
        }
        Phase::Deadline => {
            candidates.push(candidate(
                boundary,
                yosoi::BrowserTerminalSignal::DeadlineReached,
            )?);
            None
        }
    };

    let observation_setup_failed = needs_observation && observation.is_none();
    let mut navigation_armed_at_micros = None;
    let navigation = if (artifacts.network() == yosoi::ArtifactRequest::NotRequested
        && artifacts.source() == yosoi::ArtifactRequest::NotRequested)
        || !candidates.is_empty()
    {
        None
    } else {
        navigation_armed_at_micros = Some(
            boundary
                .elapsed()
                .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?
                .as_microseconds(),
        );
        let options = provider::NavigationCaptureOptions {
            max_events,
            max_resources,
            max_source_bytes: if artifacts.source() == yosoi::ArtifactRequest::NotRequested {
                1
            } else {
                config::byte_limit(spec, yosoi::BrowserByteDomain::CdpDecodedBody)?
            },
            max_duration: deadline.saturating_duration_since(TokioInstant::now()),
        };
        match bounded(page.arm_navigation_capture(options), cancellation, deadline).await {
            Phase::Complete(Ok(value)) => Some(value),
            Phase::Complete(Err(error)) => {
                let mapped = conversions::map_provider_error(&error);
                primary_terminal_reason = Some(terminal_reason_for_error(&mapped));
                candidates.push(candidate(
                    boundary,
                    yosoi::BrowserTerminalSignal::ProviderFailed {
                        reason: provider_stop(&mapped, false),
                    },
                )?);
                None
            }
            Phase::Cancelled => {
                candidates.push(candidate(boundary, caller_cancelled()?)?);
                None
            }
            Phase::Deadline => {
                candidates.push(candidate(
                    boundary,
                    yosoi::BrowserTerminalSignal::DeadlineReached,
                )?);
                None
            }
        }
    };

    Ok(ArmedAttempt {
        max_events,
        needs_observation,
        observation_armed_at_micros,
        observation_setup_failed,
        observation,
        navigation_armed_at_micros,
        navigation,
        primary_terminal_reason,
        candidates,
    })
}

async fn run_initialization<T>(
    future: impl Future<Output = Result<T, VoidCrawlAdapterError>>,
    cancellation: &CancellationToken,
    deadline: TokioInstant,
) -> Result<T, VoidCrawlAdapterError> {
    match bounded(future, cancellation, deadline).await {
        Phase::Complete(result) => result,
        Phase::Cancelled => Err(VoidCrawlAdapterError::CancelledBeforeStaging),
        Phase::Deadline => Err(VoidCrawlAdapterError::DeadlineBeforeStaging),
    }
}
