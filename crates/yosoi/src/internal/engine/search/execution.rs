//! Bounded execution for policy-selected Search providers.

use crate::internal::respectfulness::{Operation as RespectOperation, resolve_registry};
use crate::policy::{
    respectfulness::{Event as TrafficEvent, EventKind, RespectfulnessError},
    search::{EffectiveProviderRoute, Provider, Routing},
};
use std::{collections::VecDeque, time::Duration};

use crate::internal::policy::policy::AddressableByteLimit;
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;

use crate::internal::engine::search::{
    BoundSearchRequest, ProviderOutcome, ProviderResult, SearchFailure, SearchResponse,
    SearchTermination, SearchUnavailableReason,
};

mod auto;
mod google_redirect;
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
        let mut prepared = self.prepare()?;
        if self.policy().respectfulness.is_some() || self.policy().search.routing == Routing::Auto {
            prepared.registry = resolve_registry(
                self.policy().respectfulness.as_ref(),
                self.registry(),
                cancellation,
                Some(deadline),
            )
            .await?;
        }
        execute_prepared(prepared, deadline, cancellation, self.diagnostic_capture()).await
    }
}

async fn route_jobs(
    prepared: &super::PreparedSearch,
    jobs: &mut VecDeque<ScheduledJob<ProviderJob>>,
    slots: &mut [Option<ProviderResult>],
    cancellation: &CancellationToken,
    deadline: Instant,
) -> Result<Option<Provider>, super::SearchSendError> {
    let effective_search = &prepared.policy_snapshot().effective_policy().search;
    let provider_count = prepared.providers().len();
    let mut selected_provider = None;
    if effective_search.routing == Routing::Auto
        && !cancellation.is_cancelled()
        && Instant::now() < deadline
    {
        let registry = prepared.registry.clone().ok_or_else(|| {
            super::SearchSendError::Respectfulness(RespectfulnessError::Setup {
                message: "Auto Search has no bound registry".to_owned(),
            })
        })?;
        let mut targets = vec![None; provider_count];
        for job in jobs.iter() {
            let target = targets
                .get_mut(job.slot)
                .ok_or(SearchExecutionSetupError::ProviderTarget)?;
            *target = Some(job.payload.provider_target.as_str().to_owned());
        }
        let mut choice = auto::select(
            prepared
                .providers()
                .iter()
                .map(EffectiveProviderRoute::provider)
                .collect(),
            targets,
            prepared.policy_snapshot().policy().respectfulness.clone(),
            registry,
            cancellation,
            deadline,
        )
        .await?;
        for (slot, error) in choice.rejected {
            let route = prepared
                .providers()
                .get(slot)
                .ok_or(SearchExecutionSetupError::ProviderTarget)?;
            let mut result =
                ProviderResult::not_started(route, SearchUnavailableReason::Respectfulness);
            result.respectfulness.push(TrafficEvent {
                kind: EventKind::Rejected,
                groups: Vec::new(),
                registry_id: None,
                status: None,
                error: Some(error),
            });
            *slots
                .get_mut(slot)
                .ok_or(SearchExecutionSetupError::ProviderTarget)? = Some(result);
        }
        if choice.slot.is_some() || (!cancellation.is_cancelled() && Instant::now() < deadline) {
            let mut selected_jobs = VecDeque::new();
            while let Some(mut job) = jobs.pop_front() {
                if choice.slot == Some(job.slot) {
                    selected_provider = Some(job.payload.provider);
                    job.payload.initial_operation = choice.permit.take().map(|permit| {
                        RespectOperation::from_permit(
                            permit,
                            job.payload.provider_target.as_str().to_owned(),
                        )
                    });
                    selected_jobs.push_back(job);
                } else {
                    let slot = slots
                        .get_mut(job.slot)
                        .ok_or(SearchExecutionSetupError::ProviderTarget)?;
                    if slot.is_none() {
                        *slot = Some(ProviderResult::not_started(
                            &job.payload.route,
                            SearchUnavailableReason::NotSelected,
                        ));
                    }
                }
            }
            *jobs = selected_jobs;
        }
    }

    Ok(selected_provider)
}

async fn execute_prepared(
    prepared: super::PreparedSearch,
    deadline: Instant,
    cancellation: &CancellationToken,
    diagnostic_capture: bool,
) -> Result<SearchResponse, super::SearchSendError> {
    let effective_search = &prepared.policy_snapshot().effective_policy().search;
    let provider_count = prepared.providers().len();
    let total_output_limit = effective_search
        .max_retained_content_bytes()
        .as_usize()
        .map_err(|_| SearchExecutionSetupError::OutputBudgetTooSmall)?;
    let per_provider_output_limit = per_provider_output_quota(
        total_output_limit,
        if effective_search.routing == Routing::Auto {
            1
        } else {
            provider_count
        },
    )?;
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

    let selected_provider =
        route_jobs(&prepared, &mut jobs, &mut slots, cancellation, deadline).await?;

    let worker = move |job: ProviderJob, token: CancellationToken| async move {
        execute_provider(job, &token, diagnostic_capture).await
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
        routing: effective_search.routing,
        selected_provider,
        request_id: prepared.request_id(),
        policy_identity: prepared.policy_snapshot().identity(),
        providers,
        termination,
    })
}
