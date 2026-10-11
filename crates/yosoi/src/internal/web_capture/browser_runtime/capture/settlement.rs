use super::super::VoidCrawlAdapterError;
use super::snapshots::observation_event_accounting;
use super::termination::{caller_cancelled, candidate};
use super::{Phase, bounded};
use crate::internal::browser as provider;
use crate::internal::web_capture as yosoi;
use std::time::Duration;
use tokio::time::Instant as TokioInstant;
use tokio_util::sync::CancellationToken;

pub(super) async fn wait_for_quiet(
    observation: &mut provider::ObservationScope,
    policy: &yosoi::QuietPeriodPolicy,
    cancellation: &CancellationToken,
    deadline: TokioInstant,
) -> Phase<Result<provider::QuietSettlementProof, provider::QuietWaitError>> {
    let Ok(maximum) = usize::try_from(policy.maximum_relevant_in_flight().get()) else {
        return Phase::Complete(Err(provider::QuietWaitError::ProgressLost));
    };
    bounded(
        observation.wait_for_quiet(
            Duration::from_micros(policy.required_quiet().as_microseconds()),
            maximum,
            deadline,
        ),
        cancellation,
        deadline,
    )
    .await
}

#[allow(
    clippy::needless_pass_by_value,
    reason = "the terminal phase is matched exhaustively and contains no reusable handles"
)]
pub(super) fn push_quiet_failure(
    outcome: Phase<Result<provider::QuietSettlementProof, provider::QuietWaitError>>,
    boundary: yosoi::AttemptBoundary,
    candidates: &mut Vec<yosoi::BrowserTerminalCandidate>,
) -> Result<(), VoidCrawlAdapterError> {
    let signal = match outcome {
        Phase::Cancelled => caller_cancelled()?,
        Phase::Complete(Err(provider::QuietWaitError::RendererCrashed)) => {
            yosoi::BrowserTerminalSignal::ProviderFailed {
                reason: yosoi::BrowserProviderStop::RendererFailure,
            }
        }
        Phase::Deadline | Phase::Complete(Err(provider::QuietWaitError::DeadlineReached)) => {
            yosoi::BrowserTerminalSignal::DeadlineReached
        }
        Phase::Complete(Err(provider::QuietWaitError::ObservationTerminated(
            provider::ObservationTermination::EventLimitReached,
        ))) => yosoi::BrowserTerminalSignal::EventLimitReached,
        Phase::Complete(Err(provider::QuietWaitError::ObservationTerminated(
            provider::ObservationTermination::ProviderDisconnected,
        ))) => yosoi::BrowserTerminalSignal::ProviderFailed {
            reason: yosoi::BrowserProviderStop::BrowserDisconnected,
        },
        Phase::Complete(Err(_)) => yosoi::BrowserTerminalSignal::ProviderFailed {
            reason: yosoi::BrowserProviderStop::PageFailure,
        },
        Phase::Complete(Ok(_)) => return Err(VoidCrawlAdapterError::InvalidStaging),
    };
    candidates.push(candidate(boundary, signal)?);
    Ok(())
}

pub(super) fn settlement_evidence(
    policy: &yosoi::QuietPeriodPolicy,
    proof: &provider::QuietSettlementProof,
    armed_at: u64,
) -> Result<yosoi::SettlementEvidence, VoidCrawlAdapterError> {
    let quiet_since = armed_at
        .checked_add(proof.quiet_since_offset_micros)
        .ok_or(VoidCrawlAdapterError::InvalidStaging)?;
    let satisfied = armed_at
        .checked_add(proof.satisfied_offset_micros)
        .ok_or(VoidCrawlAdapterError::InvalidStaging)?;
    let accounting = observation_event_accounting(&proof.event_accounting)?;
    yosoi::SettlementEvidence::new(
        policy.id().clone(),
        yosoi::CaptureOffset::from_microseconds(quiet_since),
        yosoi::CaptureOffset::from_microseconds(satisfied),
        yosoi::ActivityCount::new(proof.relevant_in_flight),
        accounting,
    )
    .map_err(|_| VoidCrawlAdapterError::InvalidStaging)
}
