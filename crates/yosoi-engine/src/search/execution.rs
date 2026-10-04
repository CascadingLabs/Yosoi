//! Bounded execution for policy-selected Search providers.

use std::{collections::VecDeque, time::Duration};

use tokio::time::Instant;
use tokio_util::sync::CancellationToken;
use yosoi_policy::policy::AddressableByteLimit;

use crate::search::{
    BoundSearchRequest, ProviderOutcome, ProviderResult, SearchFailure, SearchResponse,
    SearchTermination, SearchUnavailableReason,
};

mod output;
mod prepare;
mod provider;
mod response;
mod scheduler;
#[cfg(test)]
mod tests;

use output::cap_global_output;
pub use prepare::SearchExecutionSetupError;
use prepare::{ProviderJob, job_uses_browser, per_provider_output_quota, prepare_provider_job};
use provider::execute_provider;
use response::failed_provider;
use scheduler::{ScheduledJob, SchedulerStopReason, SchedulerTermination, run_scheduler};

impl BoundSearchRequest<'_> {
    /// Executes one provider Request for each usable selected provider.
    pub async fn send(&self) -> Result<SearchResponse, super::SearchSendError> {
        let cancellation = CancellationToken::new();
        self.send_cancellable(&cancellation).await
    }

    /// Executes with caller cancellation and one absolute Search deadline.
    pub async fn send_cancellable(
        &self,
        cancellation: &CancellationToken,
    ) -> Result<SearchResponse, super::SearchSendError> {
        let started_at = Instant::now();
        let maximum_elapsed = self.policy().search.maximum_elapsed();
        let deadline = started_at
            .checked_add(Duration::from_micros(maximum_elapsed.as_microseconds()))
            .ok_or(SearchExecutionSetupError::DeadlineUnrepresentable)?;
        let prepared = self.prepare()?;
        execute_prepared(prepared, deadline, cancellation).await
    }
}

async fn execute_prepared(
    prepared: super::PreparedSearch,
    deadline: Instant,
    cancellation: &CancellationToken,
) -> Result<SearchResponse, super::SearchSendError> {
    let effective_search = &prepared.policy_snapshot().effective_policy().search;
    let provider_count = prepared.providers().len();
    let total_output_limit = effective_search
        .max_retained_content_bytes()
        .as_usize()
        .map_err(|_| SearchExecutionSetupError::OutputBudgetTooSmall)?;
    let per_provider_output_limit = per_provider_output_quota(total_output_limit, provider_count)?;
    let output_limit = AddressableByteLimit::try_from(
        u64::try_from(per_provider_output_limit)
            .map_err(|_| SearchExecutionSetupError::OutputBudgetTooSmall)?,
    )
    .map_err(|_| SearchExecutionSetupError::OutputBudgetTooSmall)?;

    let mut slots = Vec::with_capacity(provider_count);
    let mut jobs = VecDeque::with_capacity(provider_count);
    for (slot, route) in prepared.providers().iter().enumerate() {
        let (prebuilt, job) = prepare_provider_job(
            &prepared,
            route,
            output_limit,
            per_provider_output_limit,
            usize::from(effective_search.max_results_per_provider().get()),
        )?;
        slots.push(prebuilt);
        if let Some(job) = job {
            jobs.push_back(ScheduledJob {
                slot,
                uses_browser: job_uses_browser(&job),
                payload: job,
            });
        }
    }

    let worker = |job: ProviderJob, token: CancellationToken| async move {
        execute_provider(job, &token).await
    };
    let mut scheduled = run_scheduler(
        jobs,
        slots,
        effective_search.max_in_flight().get(),
        effective_search.max_browser_in_flight().get(),
        deadline,
        cancellation,
        worker,
    )
    .await;

    let mut providers = Vec::with_capacity(provider_count);
    let scheduler_termination = scheduled.termination;
    for (slot, route) in prepared.providers().iter().enumerate() {
        let result = scheduled.slots.get_mut(slot).and_then(Option::take);
        let result = if let Some(mut result) = result {
            if scheduler_termination == SchedulerTermination::DeadlineReached
                && matches!(result.outcome, ProviderOutcome::Cancelled)
            {
                result.outcome = ProviderOutcome::Failed(SearchFailure::BudgetExhausted);
            }
            result
        } else {
            match scheduled.not_started.get(slot).copied().flatten() {
                Some(SchedulerStopReason::Cancelled) => {
                    ProviderResult::not_started(route, SearchUnavailableReason::Cancelled)
                }
                Some(SchedulerStopReason::DeadlineReached) => {
                    ProviderResult::not_started(route, SearchUnavailableReason::DeadlineReached)
                }
                None => failed_provider(route, SearchFailure::TransportFailure),
            }
        };
        providers.push(result);
    }

    let result_limit =
        usize::try_from(effective_search.max_total_results().get()).unwrap_or(usize::MAX);
    cap_global_output(&mut providers, result_limit, total_output_limit);

    let termination = match scheduler_termination {
        SchedulerTermination::Completed => SearchTermination::Completed,
        SchedulerTermination::Cancelled => SearchTermination::Cancelled,
        SchedulerTermination::DeadlineReached => SearchTermination::DeadlineReached,
    };
    Ok(SearchResponse {
        request_id: prepared.request_id(),
        policy_identity: prepared.policy_snapshot().identity(),
        providers,
        termination,
    })
}
