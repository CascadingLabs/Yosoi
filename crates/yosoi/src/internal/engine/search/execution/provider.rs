use crate::internal::engine::request::{execution::AttemptOutcome, new as new_request};
use crate::internal::engine::search::{
    ProviderOutcome, ProviderResult, SearchFailure, SearchIssueKind, SearchProfileFacts,
};
use crate::internal::policy::Policy;
use crate::internal::policy::policy::{DocumentRequest, ProfileSelectionKind, search::Provider};
use crate::internal::web_capture::RequestedWebTarget;
use tokio_util::sync::CancellationToken;

use super::prepare::ProviderJob;
use super::response::{
    ProviderResponseLimits, provider_result_from_response, request_error_result,
};

pub(super) async fn execute_provider(
    job: ProviderJob,
    cancellation: &CancellationToken,
    diagnostic_capture: bool,
) -> ProviderResult {
    if job.provider == Provider::Google {
        return execute_google(job, cancellation, diagnostic_capture).await;
    }
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
    let result = provider_result_from_response(
        provider,
        &policy,
        &provider_target,
        ProviderResponseLimits {
            results: result_limit,
            output_bytes: output_limit,
            capture_bytes: diagnostic_capture.then_some(output_limit),
        },
        profile,
        &response,
    );
    if !should_attempt_bing_recovery(
        provider,
        route.profile_selection_kind(),
        &result.outcome,
        &query,
        cancellation.is_cancelled(),
    ) {
        return result;
    }
    let Some(shorter_query) = super::super::provider::bing::recovery_query(&query) else {
        return result;
    };
    let Ok(recovery_target) = super::super::target::provider_target(Provider::Bing, &shorter_query)
    else {
        return result;
    };
    execute_bing_recovery(
        result,
        &policy,
        profile,
        &provider_target,
        &query,
        recovery_target.as_str(),
        &recovery_target,
        shorter_query,
        result_limit,
        output_limit,
        diagnostic_capture,
        cancellation,
    )
    .await
}

pub(super) fn should_attempt_bing_recovery(
    provider: Provider,
    selection: ProfileSelectionKind,
    outcome: &ProviderOutcome,
    query: &str,
    cancelled: bool,
) -> bool {
    if provider != Provider::Bing || selection != ProfileSelectionKind::Current || cancelled {
        return false;
    }
    match outcome {
        ProviderOutcome::Failed(SearchFailure::QueryMismatch) => true,
        ProviderOutcome::Results(page) => {
            page.issues()
                .iter()
                .any(|issue| issue.kind == SearchIssueKind::QueryRelevanceUnknown)
                && super::super::provider::bing::has_clear_topic_loss(page.hits(), query)
        }
        ProviderOutcome::Empty
        | ProviderOutcome::Failed(_)
        | ProviderOutcome::Cancelled
        | ProviderOutcome::NotStarted(_) => false,
    }
}

#[allow(clippy::too_many_arguments)]
pub(super) async fn execute_bing_recovery(
    mut result: ProviderResult,
    policy: &Policy,
    profile: SearchProfileFacts,
    original_provider_target: &RequestedWebTarget,
    original_query: &str,
    recovery_request_target: &str,
    recovery_provider_target: &RequestedWebTarget,
    recovery_query: String,
    result_limit: usize,
    output_limit: usize,
    diagnostic_capture: bool,
    cancellation: &CancellationToken,
) -> ProviderResult {
    let original_has_results = matches!(result.outcome, ProviderOutcome::Results(_));
    result.recovery_query = Some(recovery_query);
    let recovery_request = new_request(recovery_request_target);
    let Ok(recovery_response) = recovery_request
        .bind(policy)
        .send_cancellable(cancellation)
        .await
    else {
        return result;
    };
    let retained_bytes = result
        .captures
        .iter()
        .try_fold(0_usize, |total, capture| {
            usize::try_from(capture.document.byte_len())
                .ok()
                .and_then(|bytes| total.checked_add(bytes))
        })
        .unwrap_or(output_limit);
    let mut recovered = provider_result_from_response(
        Provider::Bing,
        policy,
        recovery_provider_target,
        ProviderResponseLimits {
            results: result_limit,
            output_bytes: output_limit,
            capture_bytes: diagnostic_capture
                .then_some(output_limit.saturating_sub(retained_bytes)),
        },
        profile,
        &recovery_response,
    );
    for capture in &mut recovered.captures {
        original_provider_target
            .as_str()
            .clone_into(&mut capture.original_provider_page_url);
    }
    result.captures.extend(recovered.captures);
    result.attempts.extend(recovered.attempts);
    match recovered.outcome {
        ProviderOutcome::Results(page)
            if !page
                .issues()
                .iter()
                .any(|issue| issue.kind == SearchIssueKind::QueryRelevanceUnknown)
                && super::super::provider::bing::recovered_page_matches_query(
                    &page,
                    original_query,
                ) =>
        {
            result.outcome = ProviderOutcome::Results(page.with_query_relaxation(result_limit));
        }
        ProviderOutcome::Failed(
            failure @ (SearchFailure::RateLimited | SearchFailure::Challenge),
        ) if !original_has_results => {
            result.outcome = ProviderOutcome::Failed(failure);
        }
        ProviderOutcome::Cancelled if !original_has_results => {
            result.outcome = ProviderOutcome::Cancelled;
        }
        _ => {}
    }
    result
}

async fn execute_google(
    job: ProviderJob,
    cancellation: &CancellationToken,
    diagnostic_capture: bool,
) -> ProviderResult {
    let ProviderJob {
        route,
        request,
        policy,
        provider_target,
        result_limit,
        output_limit,
        profile,
        ..
    } = job;
    let response = match request.bind(&policy).send_cancellable(cancellation).await {
        Ok(response) => response,
        Err(error) => return request_error_result(&route, profile, &error),
    };
    let mut result = provider_result_from_response(
        Provider::Google,
        &policy,
        &provider_target,
        ProviderResponseLimits {
            results: result_limit,
            output_bytes: output_limit,
            capture_bytes: diagnostic_capture.then_some(output_limit),
        },
        profile,
        &response,
    );
    match &result.outcome {
        ProviderOutcome::Results(_) | ProviderOutcome::Failed(SearchFailure::MalformedResponse) => {
        }
        ProviderOutcome::Empty
        | ProviderOutcome::Failed(_)
        | ProviderOutcome::Cancelled
        | ProviderOutcome::NotStarted(_) => return result,
    }

    let Some(document) = response
        .attempts()
        .iter()
        .find_map(|attempt| match attempt {
            AttemptOutcome::Completed(result) => result
                .documents()
                .iter()
                .find(|document| document.requested() == DocumentRequest::RenderedDom)
                .and_then(|document| document.outcome().document()),
            AttemptOutcome::Failed(_) | AttemptOutcome::NotStarted(_) => None,
        })
    else {
        return result;
    };
    let parsed = match super::super::provider::google::parse_rows(
        document,
        &policy,
        provider_target.as_str(),
        result_limit,
    ) {
        Ok(super::super::provider::google::GoogleParsedDocument::Challenge) => {
            result.outcome = ProviderOutcome::Failed(SearchFailure::Challenge);
            return result;
        }
        Ok(super::super::provider::google::GoogleParsedDocument::Results(page)) => page,
        Err(error) => {
            result.outcome = ProviderOutcome::Failed(match error {
                super::super::provider::google::GoogleParseError::OutputLimit => {
                    SearchFailure::BudgetExhausted
                }
                _ => SearchFailure::MalformedResponse,
            });
            return result;
        }
    };
    let resolution =
        super::google_redirect::resolve(&parsed, &policy, result_limit, cancellation).await;
    super::google_redirect::apply(result, parsed, resolution, result_limit, output_limit)
}
