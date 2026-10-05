use crate::request::new as new_request;
use crate::search::{ProviderOutcome, ProviderResult, SearchFailure};
use tokio_util::sync::CancellationToken;
use yosoi_policy::policy::{ProfileSelectionKind, search::Provider};

use super::prepare::ProviderJob;
use super::response::{provider_result_from_response, request_error_result};

pub(super) async fn execute_provider(
    job: ProviderJob,
    cancellation: &CancellationToken,
) -> ProviderResult {
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
    let Some(shorter_query) = super::super::provider::bing::recovery_query(&query) else {
        return result;
    };
    let Ok(recovery_target) = super::super::target::provider_target(Provider::Bing, &shorter_query)
    else {
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
            if super::super::provider::bing::recovered_page_matches_query(&page, &query) =>
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
