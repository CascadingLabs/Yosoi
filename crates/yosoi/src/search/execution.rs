//! Bounded execution for policy-selected Search providers.

use std::{
    collections::{HashMap, VecDeque},
    future::Future,
    time::Duration,
};

use thiserror::Error;
use tokio::{
    task::{Id as TaskId, JoinSet},
    time::{Instant, sleep_until},
};
use tokio_util::sync::CancellationToken;
use yosoi_policy::{
    Policy, PolicySnapshot,
    policy::{
        Acquisition, AcquisitionKind, AddressableByteLimit, BrowserMode, DocumentRequest,
        search::{EffectiveProviderRoute, ProfileSelectionKind, Provider},
    },
};
use yosoi_web_capture::RequestedWebTarget;

use crate::request::new as new_request;
use crate::{
    PageRequest, RequestSendError, Response, ResponseTermination,
    request::execution::{AttemptCaptureFacts, AttemptDiagnostic, AttemptOutcome},
};

use super::{
    BoundSearchRequest, FeatureCoverage, PreparedSearch, ProviderCharge, ProviderIdentity,
    ProviderOutcome, ProviderResult, RequestAttemptSummary, RequestAttemptTerminal,
    SearchAttemptDiagnostic, SearchCoverage, SearchFailure, SearchHit, SearchIssue,
    SearchIssueKind, SearchPage, SearchProfileFacts, SearchResponse, SearchResultUrl,
    SearchTermination, SearchUnavailableReason, WebCoverage,
    target::{ProviderTargetError, provider_target},
};

/// A structural Search setup failure detected before provider Requests start.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum SearchExecutionSetupError {
    #[error("Search output budget cannot provide a nonzero quota to every selected provider")]
    OutputBudgetTooSmall,
    #[error("Search deadline cannot be represented by the runtime clock")]
    DeadlineUnrepresentable,
    #[error("Search provider target could not be prepared")]
    ProviderTarget,
    #[error("Search child Request policy could not be prepared")]
    ChildRequestPolicy,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum SchedulerStopReason {
    Cancelled,
    DeadlineReached,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum SchedulerTermination {
    Completed,
    Cancelled,
    DeadlineReached,
}

struct ScheduledJob<J> {
    slot: usize,
    uses_browser: bool,
    payload: J,
}

struct SchedulerResult<T> {
    slots: Vec<Option<T>>,
    not_started: Vec<Option<SchedulerStopReason>>,
    termination: SchedulerTermination,
}

struct ProviderJob {
    route: EffectiveProviderRoute,
    provider: Provider,
    request: PageRequest,
    policy: Policy,
    provider_target: RequestedWebTarget,
    query: String,
    result_limit: usize,
    output_limit: usize,
    profile: SearchProfileFacts,
}

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
    prepared: PreparedSearch,
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

    let max_in_flight = effective_search.max_in_flight().get();
    let max_browser_in_flight = effective_search.max_browser_in_flight().get();
    let worker = |job: ProviderJob, token: CancellationToken| async move {
        execute_provider(job, &token).await
    };
    let mut scheduled = run_scheduler(
        jobs,
        slots,
        max_in_flight,
        max_browser_in_flight,
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
            let reason = scheduled.not_started.get(slot).copied().flatten();
            match reason {
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

fn per_provider_output_quota(
    total_limit: usize,
    provider_count: usize,
) -> Result<usize, SearchExecutionSetupError> {
    let quota = total_limit
        .checked_div(provider_count)
        .filter(|quota| *quota > 0)
        .ok_or(SearchExecutionSetupError::OutputBudgetTooSmall)?;
    Ok(quota)
}

fn prepare_provider_job(
    prepared: &PreparedSearch,
    route: &EffectiveProviderRoute,
    output_limit: AddressableByteLimit,
    output_limit_usize: usize,
    result_limit: usize,
) -> Result<(Option<ProviderResult>, Option<ProviderJob>), SearchExecutionSetupError> {
    if route.profile_selection_kind() == ProfileSelectionKind::Current && route.profile().is_none()
    {
        return Ok((
            Some(ProviderResult::not_started(
                route,
                SearchUnavailableReason::DefaultUncertified,
            )),
            None,
        ));
    }

    let Some(page) = route.page() else {
        return Ok((
            Some(ProviderResult::not_started(
                route,
                SearchUnavailableReason::DefaultUncertified,
            )),
            None,
        ));
    };
    if page.acquisitions.is_empty() {
        return Ok((
            Some(ProviderResult::not_started(
                route,
                SearchUnavailableReason::UnsupportedCapability,
            )),
            None,
        ));
    }
    #[cfg(not(feature = "browser"))]
    if page
        .acquisitions
        .iter()
        .any(|acquisition| matches!(acquisition.kind(), AcquisitionKind::Browser { .. }))
    {
        return Ok((
            Some(ProviderResult::not_started(
                route,
                SearchUnavailableReason::UnsupportedCapability,
            )),
            None,
        ));
    }
    if page.acquisitions.len() != 1 {
        return Ok((
            Some(ProviderResult::not_started(
                route,
                SearchUnavailableReason::UnsupportedCapability,
            )),
            None,
        ));
    }
    let Some(acquisition) = page.acquisitions.first() else {
        return Ok((
            Some(ProviderResult::not_started(
                route,
                SearchUnavailableReason::UnsupportedCapability,
            )),
            None,
        ));
    };
    if acquisition
        .exact_documents()
        .is_some_and(|documents| !documents.contains(&DocumentRequest::ResponseDocument))
    {
        return Ok((
            Some(ProviderResult::not_started(
                route,
                SearchUnavailableReason::UnsupportedCapability,
            )),
            None,
        ));
    }

    if route.provider() == Provider::DuckDuckGo && !is_supported_duckduckgo_acquisition(acquisition)
    {
        return Ok((
            Some(ProviderResult::not_started(
                route,
                SearchUnavailableReason::UnsupportedCapability,
            )),
            None,
        ));
    }

    let policy = prepared
        .request_policy_for(route, output_limit)
        .ok_or(SearchExecutionSetupError::ChildRequestPolicy)?;
    let child_snapshot = PolicySnapshot::from_policy(&policy)
        .map_err(|_| SearchExecutionSetupError::ChildRequestPolicy)?;
    let target =
        provider_target(route.provider(), prepared.query()).map_err(map_provider_target_error)?;
    let request = new_request(target.as_str());
    request
        .clone()
        .bind(&policy)
        .prepare()
        .map_err(|_| SearchExecutionSetupError::ChildRequestPolicy)?;

    let acquisition = page.acquisitions.first().map(Acquisition::kind);
    let profile = SearchProfileFacts {
        acquisition,
        defaults_status: route.defaults_status(),
        defaults_version: route.defaults_version(),
        effective_request_policy: Some(child_snapshot.identity()),
    };
    Ok((
        None,
        Some(ProviderJob {
            route: route.clone(),
            provider: route.provider(),
            request,
            policy,
            provider_target: target,
            query: prepared.query().to_owned(),
            result_limit,
            output_limit: output_limit_usize,
            profile,
        }),
    ))
}

const fn map_provider_target_error(_: ProviderTargetError) -> SearchExecutionSetupError {
    SearchExecutionSetupError::ProviderTarget
}

fn job_uses_browser(job: &ProviderJob) -> bool {
    job.policy
        .page
        .acquisitions
        .iter()
        .any(|acquisition| matches!(acquisition.kind(), AcquisitionKind::Browser { .. }))
}

fn is_supported_duckduckgo_acquisition(acquisition: &Acquisition) -> bool {
    matches!(
        acquisition.kind(),
        AcquisitionKind::Browser {
            mode: BrowserMode::Headless
        }
    ) && acquisition.exact_documents().is_some_and(|documents| {
        documents
            == [
                DocumentRequest::ResponseDocument,
                DocumentRequest::RenderedDom,
            ]
    })
}

async fn execute_provider(job: ProviderJob, cancellation: &CancellationToken) -> ProviderResult {
    let ProviderJob {
        route,
        provider,
        request,
        policy,
        provider_target,
        query,
        result_limit,
        output_limit,
        profile,
    } = job;
    let bound = request.bind(&policy);
    let response = match bound.send_cancellable(cancellation).await {
        Ok(response) => response,
        Err(error) => return request_error_result(&route, profile, &error),
    };
    let mut result = provider_result_from_response(
        provider,
        &policy,
        &provider_target,
        result_limit,
        output_limit,
        profile,
        &response,
    );
    if provider != Provider::Bing
        || route.profile_selection_kind() != ProfileSelectionKind::Current
        || !matches!(
            result.outcome,
            ProviderOutcome::Failed(SearchFailure::QueryMismatch)
        )
        || cancellation.is_cancelled()
    {
        return result;
    }
    let Some(shorter_query) = super::provider::bing::recovery_query(&query) else {
        return result;
    };
    let Ok(recovery_target) = super::target::provider_target(Provider::Bing, &shorter_query) else {
        return result;
    };
    let recovery_request = new_request(recovery_target.as_str());
    let Ok(recovery_response) = recovery_request
        .bind(&policy)
        .send_cancellable(cancellation)
        .await
    else {
        return result;
    };
    let recovered = provider_result_from_response(
        provider,
        &policy,
        &recovery_target,
        result_limit,
        output_limit,
        profile,
        &recovery_response,
    );
    result.attempts.extend(recovered.attempts);
    result.recovery_query = Some(shorter_query);
    match recovered.outcome {
        ProviderOutcome::Results(page)
            if super::provider::bing::recovered_page_matches_query(&page, &query) =>
        {
            result.outcome = ProviderOutcome::Results(page.with_query_relaxation(result_limit));
        }
        ProviderOutcome::Failed(
            failure @ (SearchFailure::RateLimited | SearchFailure::Challenge),
        ) => {
            result.outcome = ProviderOutcome::Failed(failure);
        }
        ProviderOutcome::Cancelled => result.outcome = ProviderOutcome::Cancelled,
        _ => {}
    }
    result
}

fn request_error_result(
    route: &EffectiveProviderRoute,
    profile: SearchProfileFacts,
    error: &RequestSendError,
) -> ProviderResult {
    match error {
        RequestSendError::StandardSetup(_) => {
            ProviderResult::not_started(route, SearchUnavailableReason::RequestSetupFailed)
        }
        RequestSendError::Preparation(_) => ProviderResult {
            identity: ProviderIdentity {
                provider: route.provider(),
                endpoint: None,
                adapter_version: None,
                parser_version: None,
            },
            profile,
            request_id: None,
            recovery_query: None,
            attempts: Vec::new(),
            outcome: ProviderOutcome::Failed(SearchFailure::MalformedResponse),
            charge: ProviderCharge::Unknown,
        },
    }
}

fn provider_result_from_response(
    provider: Provider,
    policy: &Policy,
    target: &RequestedWebTarget,
    result_limit: usize,
    output_limit: usize,
    profile: SearchProfileFacts,
    response: &Response,
) -> ProviderResult {
    let mut attempts = Vec::with_capacity(response.attempts().len());
    let mut any_attempt_started = false;
    for attempt in response.attempts() {
        let terminal = match attempt {
            AttemptOutcome::Completed(_) => {
                any_attempt_started = true;
                RequestAttemptTerminal::Completed
            }
            AttemptOutcome::Failed(failure) => {
                any_attempt_started |= !matches!(
                    failure.diagnostic(),
                    AttemptDiagnostic::MissingExecutionContext
                        | AttemptDiagnostic::PolicyResolutionFailed
                        | AttemptDiagnostic::BrowserFeatureDisabled
                );
                RequestAttemptTerminal::Failed
            }
            AttemptOutcome::NotStarted(_) => RequestAttemptTerminal::NotStarted,
        };
        attempts.push(RequestAttemptSummary {
            request_id: response.request_id(),
            capture_id: attempt.capture_id(),
            acquisition: attempt.acquisition(),
            http_status: attempt.status(),
            source_bytes: match attempt {
                AttemptOutcome::Completed(result) => result.capture_facts().source_bytes(),
                AttemptOutcome::Failed(failure) => failure
                    .capture_facts()
                    .and_then(AttemptCaptureFacts::source_bytes),
                AttemptOutcome::NotStarted(_) => None,
            },
            diagnostic: match attempt {
                AttemptOutcome::Failed(failure) => {
                    Some(search_attempt_diagnostic(failure.diagnostic()))
                }
                AttemptOutcome::Completed(_) | AttemptOutcome::NotStarted(_) => None,
            },
            terminal,
        });
    }

    let mut parser_ran = false;
    let outcome = interpret_response(
        provider,
        policy,
        target,
        result_limit,
        output_limit,
        response,
        &mut parser_ran,
    );
    let (endpoint, adapter_version) = if any_attempt_started {
        provider_adapter_identity(provider)
    } else {
        (None, None)
    };
    ProviderResult {
        identity: ProviderIdentity {
            provider,
            endpoint,
            adapter_version,
            parser_version: if parser_ran {
                Some(provider_parser_version(provider))
            } else {
                None
            },
        },
        profile,
        request_id: Some(response.request_id()),
        recovery_query: None,
        attempts,
        outcome,
        charge: ProviderCharge::Unknown,
    }
}

fn interpret_response(
    provider: Provider,
    policy: &Policy,
    target: &RequestedWebTarget,
    result_limit: usize,
    output_limit: usize,
    response: &Response,
    parser_ran: &mut bool,
) -> ProviderOutcome {
    let mut first_failure = None;
    for attempt in response.attempts() {
        if let Some(failure) = status_failure(attempt.status()) {
            first_failure.get_or_insert(failure);
            continue;
        }
        match attempt {
            AttemptOutcome::Completed(result) => {
                let document = result
                    .documents()
                    .iter()
                    .find(|document| document.requested() == provider_document_request(provider))
                    .and_then(|document| document.outcome().document());
                let Some(document) = document else {
                    first_failure.get_or_insert(SearchFailure::MalformedResponse);
                    continue;
                };
                *parser_ran = true;
                let parsed = match provider {
                    Provider::Brave => super::provider::brave::parse(
                        document,
                        policy,
                        target.as_str(),
                        result_limit,
                        output_limit,
                    )
                    .map_err(|error| {
                        search_parse_failure(matches!(
                            error,
                            super::provider::brave::BraveParseError::OutputLimit
                        ))
                    }),
                    Provider::Bing => super::provider::bing::parse(
                        document,
                        policy,
                        target.as_str(),
                        result_limit,
                        output_limit,
                    )
                    .map_err(|error| match error {
                        super::provider::bing::BingParseError::OutputLimit => {
                            SearchFailure::BudgetExhausted
                        }
                        super::provider::bing::BingParseError::QueryMismatch => {
                            SearchFailure::QueryMismatch
                        }
                        _ => SearchFailure::MalformedResponse,
                    }),
                    Provider::DuckDuckGo => super::provider::duckduckgo::parse(
                        document,
                        policy,
                        target.as_str(),
                        result_limit,
                        output_limit,
                    )
                    .map_err(|error| {
                        search_parse_failure(matches!(
                            error,
                            super::provider::duckduckgo::DuckDuckGoParseError::OutputLimit
                        ))
                    }),
                };
                match parsed {
                    Ok(outcome @ ProviderOutcome::Results(_)) => return outcome,
                    Ok(ProviderOutcome::Empty) => return ProviderOutcome::Empty,
                    Ok(ProviderOutcome::Failed(failure)) | Err(failure) => {
                        first_failure.get_or_insert(failure);
                    }
                    Ok(ProviderOutcome::Cancelled) => {
                        first_failure.get_or_insert(SearchFailure::TransportFailure);
                    }
                    Ok(ProviderOutcome::NotStarted(_)) => {
                        first_failure.get_or_insert(SearchFailure::MalformedResponse);
                    }
                }
            }
            AttemptOutcome::Failed(failure) => {
                first_failure
                    .get_or_insert_with(|| search_failure_for_attempt(failure.diagnostic()));
            }
            AttemptOutcome::NotStarted(_) => {
                first_failure.get_or_insert(SearchFailure::TransportFailure);
            }
        }
    }

    if response.termination() == ResponseTermination::Cancelled {
        return ProviderOutcome::Cancelled;
    }
    ProviderOutcome::Failed(first_failure.unwrap_or(SearchFailure::MalformedResponse))
}

const fn provider_document_request(provider: Provider) -> DocumentRequest {
    match provider {
        Provider::DuckDuckGo => DocumentRequest::RenderedDom,
        Provider::Brave | Provider::Bing => DocumentRequest::ResponseDocument,
    }
}

const fn search_parse_failure(output_limited: bool) -> SearchFailure {
    if output_limited {
        SearchFailure::BudgetExhausted
    } else {
        SearchFailure::MalformedResponse
    }
}

const fn search_attempt_diagnostic(diagnostic: AttemptDiagnostic) -> SearchAttemptDiagnostic {
    match diagnostic {
        AttemptDiagnostic::MissingExecutionContext => {
            SearchAttemptDiagnostic::MissingExecutionContext
        }
        AttemptDiagnostic::PolicyResolutionFailed => {
            SearchAttemptDiagnostic::PolicyResolutionFailed
        }
        AttemptDiagnostic::DirectHttpTransport(_) => SearchAttemptDiagnostic::DirectHttpTransport,
        AttemptDiagnostic::DirectHttpBodyFailed => SearchAttemptDiagnostic::DirectHttpBodyFailed,
        AttemptDiagnostic::DirectHttpFinalizationFailed => {
            SearchAttemptDiagnostic::DirectHttpFinalizationFailed
        }
        AttemptDiagnostic::BrowserCancelled => SearchAttemptDiagnostic::BrowserCancelled,
        AttemptDiagnostic::BrowserCancelledCleanupFailed => {
            SearchAttemptDiagnostic::BrowserCancelledCleanupFailed
        }
        AttemptDiagnostic::BrowserCleanupFailed => SearchAttemptDiagnostic::BrowserCleanupFailed,
        AttemptDiagnostic::BrowserCaptureFailed => SearchAttemptDiagnostic::BrowserCaptureFailed,
        AttemptDiagnostic::BrowserFinalizationFailed => {
            SearchAttemptDiagnostic::BrowserFinalizationFailed
        }
        AttemptDiagnostic::BrowserFeatureDisabled => {
            SearchAttemptDiagnostic::BrowserFeatureDisabled
        }
        AttemptDiagnostic::ProjectionFailed => SearchAttemptDiagnostic::ProjectionFailed,
    }
}

const fn search_failure_for_attempt(diagnostic: AttemptDiagnostic) -> SearchFailure {
    match diagnostic {
        AttemptDiagnostic::MissingExecutionContext
        | AttemptDiagnostic::PolicyResolutionFailed
        | AttemptDiagnostic::BrowserFeatureDisabled => SearchFailure::ProviderUnavailable,
        AttemptDiagnostic::DirectHttpTransport(_)
        | AttemptDiagnostic::DirectHttpBodyFailed
        | AttemptDiagnostic::DirectHttpFinalizationFailed
        | AttemptDiagnostic::BrowserCancelled
        | AttemptDiagnostic::BrowserCancelledCleanupFailed
        | AttemptDiagnostic::BrowserCleanupFailed
        | AttemptDiagnostic::BrowserCaptureFailed
        | AttemptDiagnostic::BrowserFinalizationFailed => SearchFailure::TransportFailure,
        AttemptDiagnostic::ProjectionFailed => SearchFailure::MalformedResponse,
    }
}

fn status_failure(status: Option<u16>) -> Option<SearchFailure> {
    let status = status?;
    if status == 429 {
        Some(SearchFailure::RateLimited)
    } else if status == 401 || status == 403 {
        Some(SearchFailure::Challenge)
    } else if !(200..300).contains(&status) {
        Some(SearchFailure::ProviderUnavailable)
    } else {
        None
    }
}

const fn provider_adapter_identity(
    provider: Provider,
) -> (Option<&'static str>, Option<&'static str>) {
    match provider {
        Provider::Brave => (
            Some("https://search.brave.com/search"),
            Some("brave-direct-http-v1"),
        ),
        Provider::Bing => (
            Some("https://www.bing.com/search"),
            Some("bing-direct-http-v2"),
        ),
        Provider::DuckDuckGo => (
            Some("https://duckduckgo.com/"),
            Some("duckduckgo-browser-v1"),
        ),
    }
}

const fn provider_parser_version(provider: Provider) -> &'static str {
    match provider {
        Provider::Brave => "brave-html-v1",
        Provider::Bing => "bing-html-v2",
        Provider::DuckDuckGo => "duckduckgo-rendered-dom-v1",
    }
}

fn failed_provider(route: &EffectiveProviderRoute, failure: SearchFailure) -> ProviderResult {
    ProviderResult {
        identity: ProviderIdentity {
            provider: route.provider(),
            endpoint: None,
            adapter_version: None,
            parser_version: None,
        },
        profile: SearchProfileFacts {
            acquisition: route
                .page()
                .and_then(|page| page.acquisitions.first())
                .map(Acquisition::kind),
            defaults_status: route.defaults_status(),
            defaults_version: route.defaults_version(),
            effective_request_policy: None,
        },
        request_id: None,
        recovery_query: None,
        attempts: Vec::new(),
        outcome: ProviderOutcome::Failed(failure),
        charge: ProviderCharge::Unknown,
    }
}

fn cap_global_output(
    providers: &mut [ProviderResult],
    total_result_limit: usize,
    total_output_limit: usize,
) {
    let mut retained_results = 0_usize;
    let mut retained_bytes = 0_usize;
    for provider in providers {
        let ProviderOutcome::Results(page) = &provider.outcome else {
            continue;
        };

        let page_fits_results =
            page.hits().len() <= total_result_limit.saturating_sub(retained_results);
        let page_bytes = page.retained_string_bytes();
        let page_fits_bytes = page_bytes
            .and_then(|bytes| retained_bytes.checked_add(bytes))
            .is_some_and(|bytes| bytes <= total_output_limit);
        if page_fits_results && page_fits_bytes {
            retained_results = retained_results
                .checked_add(page.hits().len())
                .unwrap_or(total_result_limit);
            retained_bytes = page_bytes
                .and_then(|bytes| retained_bytes.checked_add(bytes))
                .unwrap_or(total_output_limit);
            continue;
        }

        let mut hits = Vec::with_capacity(page.hits().len());
        let mut web_limited = false;
        let mut feature_limited = false;
        for hit in page.hits() {
            if retained_results >= total_result_limit {
                web_limited = true;
                break;
            }
            let Some(hit_bytes) = hit_retained_string_bytes(hit) else {
                web_limited = true;
                break;
            };
            let Some(next_bytes) = retained_bytes.checked_add(hit_bytes) else {
                web_limited = true;
                break;
            };
            if next_bytes > total_output_limit {
                web_limited = true;
                break;
            }
            let Some(next_results) = retained_results.checked_add(1) else {
                web_limited = true;
                break;
            };
            retained_results = next_results;
            retained_bytes = next_bytes;
            hits.push(hit.clone());
        }

        let mut features = Vec::with_capacity(page.features().len());
        for feature in page.features() {
            let Some(feature_bytes) = feature_retained_string_bytes(feature) else {
                feature_limited = true;
                break;
            };
            let Some(next_bytes) = retained_bytes.checked_add(feature_bytes) else {
                feature_limited = true;
                break;
            };
            if next_bytes > total_output_limit {
                feature_limited = true;
                break;
            }
            retained_bytes = next_bytes;
            features.push(feature.clone());
        }

        let mut issues = page.issues().to_vec();
        let limited = web_limited || feature_limited;
        if limited
            && !issues
                .iter()
                .any(|issue| issue.kind == SearchIssueKind::OutputLimit)
        {
            issues.push(SearchIssue {
                placement_index: None,
                kind: SearchIssueKind::OutputLimit,
            });
        }
        let coverage = SearchCoverage::new(
            if web_limited {
                WebCoverage::Partial
            } else {
                page.coverage().web()
            },
            if feature_limited {
                FeatureCoverage::Partial
            } else {
                page.coverage().rich_features()
            },
        );
        if hits.is_empty() && features.is_empty() && limited {
            provider.outcome = ProviderOutcome::Failed(SearchFailure::BudgetExhausted);
            continue;
        }
        provider.outcome =
            ProviderOutcome::Results(SearchPage::new(hits, features, coverage, issues));
    }
}

fn hit_retained_string_bytes(hit: &SearchHit) -> Option<usize> {
    let metadata = hit.metadata();
    let mut bytes = hit.url().as_str().len();
    for value in [
        metadata.title.as_deref(),
        metadata.snippet.as_deref(),
        metadata.display_url.as_deref(),
        metadata.publisher.as_deref(),
        metadata.published_at.as_deref(),
        metadata.thumbnail_url.as_ref().map(SearchResultUrl::as_str),
    ]
    .into_iter()
    .flatten()
    {
        bytes = bytes.checked_add(value.len())?;
    }
    Some(bytes)
}

fn feature_retained_string_bytes(feature: &super::SearchFeature) -> Option<usize> {
    match feature {
        super::SearchFeature::Sponsored {
            destination, label, ..
        } => destination
            .as_str()
            .len()
            .checked_add(label.as_deref().map_or(0, str::len)),
        super::SearchFeature::Answer {
            text, citations, ..
        } => citations.iter().try_fold(text.len(), |total, url| {
            total.checked_add(url.as_str().len())
        }),
        super::SearchFeature::ImageGallery { images, .. } => {
            images.iter().try_fold(0_usize, |total, image| {
                total
                    .checked_add(image.image_url.as_str().len())
                    .and_then(|value| value.checked_add(image.source_page_url.as_str().len()))
            })
        }
        super::SearchFeature::LocalPack {
            places, map_url, ..
        } => places.iter().try_fold(
            map_url.as_ref().map_or(0, |url| url.as_str().len()),
            |total, place| {
                total
                    .checked_add(place.name.len())
                    .and_then(|value| value.checked_add(place.place_url.as_str().len()))
            },
        ),
    }
}

async fn run_scheduler<J, T, F, Fut>(
    jobs: VecDeque<ScheduledJob<J>>,
    slots: Vec<Option<T>>,
    max_in_flight: usize,
    max_browser_in_flight: usize,
    deadline: Instant,
    caller_cancellation: &CancellationToken,
    worker: F,
) -> SchedulerResult<T>
where
    J: Send + 'static,
    T: Send + 'static,
    F: Fn(J, CancellationToken) -> Fut + Clone + Send + Sync + 'static,
    Fut: Future<Output = T> + Send + 'static,
{
    let slot_count = slots.len();
    let mut result = SchedulerResult {
        slots,
        not_started: vec![None; slot_count],
        termination: SchedulerTermination::Completed,
    };
    let mut queued = jobs;
    let mut running = JoinSet::new();
    let mut active = HashMap::<TaskId, bool>::new();
    let operation_cancellation = caller_cancellation.child_token();
    let mut stop_reason = None;

    loop {
        if stop_reason.is_none() {
            if caller_cancellation.is_cancelled() {
                stop_reason = Some(SchedulerStopReason::Cancelled);
            } else if Instant::now() >= deadline {
                stop_reason = Some(SchedulerStopReason::DeadlineReached);
            }
            if let Some(reason) = stop_reason {
                operation_cancellation.cancel();
                mark_queued_not_started(&mut queued, &mut result, reason);
            }
        }

        if stop_reason.is_none() {
            while running.len() < max_in_flight {
                if caller_cancellation.is_cancelled() {
                    stop_reason = Some(SchedulerStopReason::Cancelled);
                    operation_cancellation.cancel();
                    mark_queued_not_started(
                        &mut queued,
                        &mut result,
                        SchedulerStopReason::Cancelled,
                    );
                    break;
                }
                if Instant::now() >= deadline {
                    stop_reason = Some(SchedulerStopReason::DeadlineReached);
                    operation_cancellation.cancel();
                    mark_queued_not_started(
                        &mut queued,
                        &mut result,
                        SchedulerStopReason::DeadlineReached,
                    );
                    break;
                }
                let browser_count = active.values().filter(|is_browser| **is_browser).count();
                let eligible = queued
                    .iter()
                    .position(|job| !job.uses_browser || browser_count < max_browser_in_flight);
                let Some(eligible) = eligible else {
                    break;
                };
                let Some(job) = queued.remove(eligible) else {
                    break;
                };
                let token = operation_cancellation.child_token();
                let run_worker = worker.clone();
                let slot = job.slot;
                let uses_browser = job.uses_browser;
                let abort_handle = running.spawn(async move {
                    let value = run_worker(job.payload, token).await;
                    (slot, uses_browser, value)
                });
                active.insert(abort_handle.id(), uses_browser);
            }
        }

        if running.is_empty() {
            if stop_reason.is_none() && !queued.is_empty() {
                // A nonzero browser limit and no active jobs make every queued
                // job eligible; this branch only protects against bad bounds.
                mark_queued_not_started(
                    &mut queued,
                    &mut result,
                    SchedulerStopReason::DeadlineReached,
                );
                stop_reason = Some(SchedulerStopReason::DeadlineReached);
                result.termination = SchedulerTermination::DeadlineReached;
            }
            break;
        }

        // Do not abort a started Request while cancellation settles. Each
        // child profile has a positive maximum_elapsed; Direct HTTP uses that
        // attempt deadline, and browser capture reserves its bounded cleanup
        // grace after the attempt deadline. Joining lets those paths finish.
        tokio::select! {
            biased;
            () = caller_cancellation.cancelled(), if stop_reason.is_none() => {
                stop_reason = Some(SchedulerStopReason::Cancelled);
                result.termination = SchedulerTermination::Cancelled;
                operation_cancellation.cancel();
                mark_queued_not_started(&mut queued, &mut result, SchedulerStopReason::Cancelled);
            }
            () = sleep_until(deadline), if stop_reason.is_none() => {
                stop_reason = Some(SchedulerStopReason::DeadlineReached);
                result.termination = SchedulerTermination::DeadlineReached;
                operation_cancellation.cancel();
                mark_queued_not_started(&mut queued, &mut result, SchedulerStopReason::DeadlineReached);
            }
            joined = running.join_next_with_id() => {
                match joined {
                    Some(Ok((task_id, (slot, _uses_browser, value)))) => {
                        active.remove(&task_id);
                        if let Some(destination) = result.slots.get_mut(slot) {
                            *destination = Some(value);
                        }
                    }
                    Some(Err(error)) => {
                        active.remove(&error.id());
                    }
                    None => {}
                }
            }
        }
    }

    if let Some(reason) = stop_reason {
        result.termination = match reason {
            SchedulerStopReason::Cancelled => SchedulerTermination::Cancelled,
            SchedulerStopReason::DeadlineReached => SchedulerTermination::DeadlineReached,
        };
    }
    result
}

fn mark_queued_not_started<J, T>(
    queued: &mut VecDeque<ScheduledJob<J>>,
    result: &mut SchedulerResult<T>,
    reason: SchedulerStopReason,
) {
    while let Some(job) = queued.pop_front() {
        if let Some(slot) = result.not_started.get_mut(job.slot) {
            *slot = Some(reason);
        }
    }
}

#[cfg(test)]
mod tests {
    use std::{collections::HashMap, error::Error, io, sync::Arc, time::Duration};

    use tokio::{
        sync::{Mutex, mpsc, oneshot},
        time::Instant,
    };

    use super::{
        ScheduledJob, SchedulerStopReason, SchedulerTermination,
        is_supported_duckduckgo_acquisition, per_provider_output_quota, run_scheduler,
        search_parse_failure,
    };

    #[test]
    fn provider_output_limit_is_reported_as_budget_exhausted() {
        assert_eq!(
            search_parse_failure(true),
            super::super::SearchFailure::BudgetExhausted
        );
        assert_eq!(
            search_parse_failure(false),
            super::super::SearchFailure::MalformedResponse
        );
    }

    #[test]
    fn browser_capture_failure_is_transport_not_provider_markup() {
        let diagnostic = super::AttemptDiagnostic::BrowserCaptureFailed;
        assert_eq!(
            super::search_failure_for_attempt(diagnostic),
            super::SearchFailure::TransportFailure
        );
        assert_eq!(
            super::search_attempt_diagnostic(diagnostic),
            super::SearchAttemptDiagnostic::BrowserCaptureFailed
        );
    }

    #[test]
    fn duckduckgo_requires_headless_browser_and_both_documents() {
        use yosoi_policy::policy::{Acquisition, BrowserMode, DocumentRequest};

        let supported = Acquisition::Browser(BrowserMode::Headless).documents([
            DocumentRequest::ResponseDocument,
            DocumentRequest::RenderedDom,
        ]);
        assert!(is_supported_duckduckgo_acquisition(&supported));

        let source_only = Acquisition::Browser(BrowserMode::Headless)
            .documents([DocumentRequest::ResponseDocument]);
        assert!(!is_supported_duckduckgo_acquisition(&source_only));

        let headful = Acquisition::Browser(BrowserMode::Headful).documents([
            DocumentRequest::ResponseDocument,
            DocumentRequest::RenderedDom,
        ]);
        assert!(!is_supported_duckduckgo_acquisition(&headful));
    }

    #[cfg(not(feature = "browser"))]
    #[test]
    fn browser_disabled_build_keeps_duckduckgo_in_unsupported_slot() -> Result<(), Box<dyn Error>> {
        use yosoi_policy::policy::{
            Acquisition, AddressableByteLimit, BrowserMode, DocumentRequest, Page, Request,
            search::{Provider, ProviderRequestProfile, ProviderSelection, Search},
        };
        use yosoi_policy::{Documents, Policy};

        let acquisition = Acquisition::Browser(BrowserMode::Headless).documents([
            DocumentRequest::ResponseDocument,
            DocumentRequest::RenderedDom,
        ]);
        let profile = ProviderRequestProfile::new(
            Page::new(vec![acquisition])?,
            Request::default(),
            Documents::default(),
        )?;
        let mut search = Search::default();
        search.providers = vec![ProviderSelection::exact(Provider::DuckDuckGo, profile)];
        let policy = Policy {
            search,
            ..Policy::default()
        };
        let prepared = crate::search::new("bounded fixture query")?
            .bind(&policy)
            .prepare()?;
        let route = prepared
            .providers()
            .first()
            .ok_or_else(|| io::Error::other("missing DuckDuckGo route"))?;
        let (result, job) = super::prepare_provider_job(
            &prepared,
            route,
            AddressableByteLimit::try_from(1_024_u64)?,
            1_024,
            10,
        )?;

        let result = result.ok_or_else(|| io::Error::other("missing provider slot"))?;
        assert!(matches!(
            result.outcome(),
            super::ProviderOutcome::NotStarted(
                super::SearchUnavailableReason::UnsupportedCapability
            )
        ));
        assert!(job.is_none());
        Ok(())
    }

    #[test]
    fn global_byte_budget_is_divided_without_exceeding_total() -> Result<(), Box<dyn Error>> {
        let quota = per_provider_output_quota(10, 3)?;
        assert_eq!(quota, 3);
        assert!(quota.checked_mul(3).is_some_and(|retained| retained <= 10));
        assert!(per_provider_output_quota(2, 3).is_err());
        Ok(())
    }

    #[tokio::test]
    async fn completion_order_does_not_change_response_slots() -> Result<(), Box<dyn Error>> {
        let (started_tx, mut started_rx) = mpsc::unbounded_channel();
        let (mut release_tx, release_rx) = release_gates(3);
        let gates = Arc::new(Mutex::new(release_rx));
        let worker = {
            let gates = Arc::clone(&gates);
            move |job: usize, cancellation: tokio_util::sync::CancellationToken| {
                let gates = Arc::clone(&gates);
                let started_tx = started_tx.clone();
                async move {
                    let _ = started_tx.send(job);
                    let receiver = gates.lock().await.remove(&job);
                    if let Some(receiver) = receiver {
                        tokio::select! {
                            _ = cancellation.cancelled() => job,
                            _ = receiver => job,
                        }
                    } else {
                        job
                    }
                }
            }
        };
        let jobs = (0..3)
            .map(|slot| ScheduledJob {
                slot,
                uses_browser: false,
                payload: slot,
            })
            .collect();
        let slots = std::iter::repeat_with(|| None).take(3).collect();
        let cancellation = tokio_util::sync::CancellationToken::new();
        let deadline = Instant::now()
            .checked_add(Duration::from_secs(20))
            .ok_or_else(|| io::Error::other("test deadline overflow"))?;
        let scheduler_cancellation = cancellation.clone();
        let scheduler = tokio::spawn(async move {
            run_scheduler(jobs, slots, 2, 1, deadline, &scheduler_cancellation, worker).await
        });

        let first = started_rx
            .recv()
            .await
            .ok_or_else(|| io::Error::other("first task did not start"))?;
        let second = started_rx
            .recv()
            .await
            .ok_or_else(|| io::Error::other("second task did not start"))?;
        release_job(&mut release_tx, second)?;
        let third = started_rx
            .recv()
            .await
            .ok_or_else(|| io::Error::other("queued task did not start after a slot freed"))?;
        assert_eq!(third, 2);
        release_job(&mut release_tx, third)?;
        release_job(&mut release_tx, first)?;

        let scheduled = scheduler
            .await
            .map_err(|_| io::Error::other("scheduler task failed"))?;
        assert_eq!(scheduled.termination, SchedulerTermination::Completed);
        assert_eq!(scheduled.slots, vec![Some(0), Some(1), Some(2)]);
        Ok(())
    }

    #[tokio::test]
    async fn cancellation_keeps_queued_slot_and_drains_active_task() -> Result<(), Box<dyn Error>> {
        let (started_tx, mut started_rx) = mpsc::unbounded_channel();
        let worker = move |job: usize, cancellation: tokio_util::sync::CancellationToken| {
            let started_tx = started_tx.clone();
            async move {
                let _ = started_tx.send(job);
                cancellation.cancelled().await;
                job + 10
            }
        };
        let jobs = (0..2)
            .map(|slot| ScheduledJob {
                slot,
                uses_browser: false,
                payload: slot,
            })
            .collect();
        let slots = std::iter::repeat_with(|| None).take(2).collect();
        let cancellation = tokio_util::sync::CancellationToken::new();
        let deadline = Instant::now()
            .checked_add(Duration::from_secs(20))
            .ok_or_else(|| io::Error::other("test deadline overflow"))?;
        let scheduler_cancellation = cancellation.clone();
        let scheduler = tokio::spawn(async move {
            run_scheduler(jobs, slots, 1, 1, deadline, &scheduler_cancellation, worker).await
        });
        let started = started_rx
            .recv()
            .await
            .ok_or_else(|| io::Error::other("active task did not start"))?;
        assert_eq!(started, 0);
        cancellation.cancel();
        let scheduled = scheduler
            .await
            .map_err(|_| io::Error::other("scheduler task failed"))?;
        assert_eq!(scheduled.termination, SchedulerTermination::Cancelled);
        assert_eq!(scheduled.slots, vec![Some(10), None]);
        assert_eq!(
            scheduled.not_started.get(1).copied().flatten(),
            Some(SchedulerStopReason::Cancelled)
        );
        Ok(())
    }

    #[test]
    fn aggregate_output_cap_keeps_order_and_marks_truncation() -> Result<(), Box<dyn Error>> {
        use std::num::NonZeroU16;

        use super::{
            FeatureCoverage, ProviderCharge, ProviderIdentity, ProviderOutcome, ProviderResult,
            SearchCoverage, SearchFailure, SearchHit, SearchIssueKind, SearchPage,
            SearchProfileFacts, WebCoverage, cap_global_output,
        };
        use crate::search::SearchResultUrl;
        use yosoi_policy::policy::search::Provider;

        fn provider_with_urls<const N: usize>(
            provider: Provider,
            urls: [&str; N],
        ) -> Result<ProviderResult, Box<dyn Error>> {
            let mut hits = Vec::with_capacity(N);
            for (index, value) in urls.into_iter().enumerate() {
                let rank_value = u16::try_from(index + 1)?;
                let rank = NonZeroU16::new(rank_value)
                    .ok_or_else(|| io::Error::other("test rank must be positive"))?;
                hits.push(SearchHit::new(SearchResultUrl::parse(value)?, rank, rank));
            }
            Ok(ProviderResult {
                identity: ProviderIdentity {
                    provider,
                    endpoint: None,
                    adapter_version: None,
                    parser_version: None,
                },
                profile: SearchProfileFacts {
                    acquisition: None,
                    defaults_status: yosoi_policy::policy::ProviderDefaultsStatus::Exact,
                    defaults_version: None,
                    effective_request_policy: None,
                },
                request_id: None,
                recovery_query: None,
                attempts: Vec::new(),
                outcome: ProviderOutcome::Results(SearchPage::new(
                    hits,
                    Vec::new(),
                    SearchCoverage::new(WebCoverage::Complete, FeatureCoverage::NotCollected),
                    Vec::new(),
                )),
                charge: ProviderCharge::Unknown,
            })
        }

        let first = provider_with_urls(
            Provider::Brave,
            ["https://a.example/", "https://b.example/"],
        )?;
        let second = provider_with_urls(Provider::Bing, ["https://c.example/"])?;
        let mut providers = vec![first, second];

        cap_global_output(&mut providers, 10, 20);

        let first = providers
            .first()
            .ok_or_else(|| io::Error::other("missing Brave slot"))?;
        let ProviderOutcome::Results(page) = &first.outcome else {
            return Err(io::Error::other("expected a partial Brave page").into());
        };
        assert_eq!(page.hits().len(), 1);
        assert_eq!(page.coverage().web(), WebCoverage::Partial);
        assert_eq!(page.retained_string_bytes(), Some(18));
        assert!(
            page.issues()
                .iter()
                .any(|issue| issue.kind == SearchIssueKind::OutputLimit)
        );

        let second = providers
            .get(1)
            .ok_or_else(|| io::Error::other("missing Bing slot"))?;
        assert!(matches!(
            &second.outcome,
            ProviderOutcome::Failed(SearchFailure::BudgetExhausted)
        ));
        Ok(())
    }

    fn release_gates(
        count: usize,
    ) -> (
        HashMap<usize, oneshot::Sender<()>>,
        HashMap<usize, oneshot::Receiver<()>>,
    ) {
        let mut senders = HashMap::with_capacity(count);
        let mut receivers = HashMap::with_capacity(count);
        for slot in 0..count {
            let (sender, receiver) = oneshot::channel();
            senders.insert(slot, sender);
            receivers.insert(slot, receiver);
        }
        (senders, receivers)
    }

    fn release_job(
        senders: &mut HashMap<usize, oneshot::Sender<()>>,
        job: usize,
    ) -> Result<(), Box<dyn Error>> {
        let sender = senders
            .remove(&job)
            .ok_or_else(|| io::Error::other("missing release gate"))?;
        sender
            .send(())
            .map_err(|_| io::Error::other("release receiver was closed"))?;
        Ok(())
    }
}
