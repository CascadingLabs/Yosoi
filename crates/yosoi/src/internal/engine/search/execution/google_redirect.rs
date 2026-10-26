//! Bounded one-hop resolution for Google-owned result wrappers.

use std::{collections::HashMap, future::Future, num::NonZeroU16};

use crate::internal::direct_http::ObservedHeaderValue;
use crate::internal::engine::{
    RequestSendError, Response, ResponseTermination,
    request::{
        execution::{AttemptCaptureFacts, AttemptOutcome},
        new as new_request,
    },
    search::{
        ProviderOutcome, ProviderResult, RequestAttemptSummary, RequestAttemptTerminal,
        SearchCaptureRetention, SearchFailure, SearchIssueKind, SearchResultUrl,
    },
};
use crate::internal::policy::{
    Policy,
    policy::{Acquisition, AddressableByteLimit, DirectHttpRedirects, DocumentRequest, Page},
};
use crate::internal::web_capture::CaptureCompleteness;
use tokio_util::sync::CancellationToken;

use super::super::provider::google::{self, GoogleParsedPage};
use super::response::search_attempt_diagnostic;

/// Google wrapper lookups are serialized and capped even when the Search result limit is larger.
const MAX_GOOGLE_REDIRECT_REQUESTS_PER_SEARCH: usize = 8;
/// A wrapper response only needs a small bounded body to classify a challenge.
const MAX_GOOGLE_REDIRECT_RESPONSE_BYTES: u64 = 16_384;

pub(super) struct GoogleResolution {
    pub(super) destinations: HashMap<NonZeroU16, SearchResultUrl>,
    pub(super) failed_redirects: HashMap<NonZeroU16, SearchIssueKind>,
    pub(super) attempts: Vec<RequestAttemptSummary>,
    pub(super) failure: Option<SearchFailure>,
    pub(super) cancelled: bool,
}

enum RedirectResponse {
    Resolved(SearchResultUrl),
    Failed(SearchFailure),
    Cancelled,
}

struct RedirectAttempt {
    outcome: RedirectResponse,
    attempts: Vec<RequestAttemptSummary>,
}

pub(super) async fn resolve(
    page: &GoogleParsedPage,
    policy: &Policy,
    result_limit: usize,
    cancellation: &CancellationToken,
) -> GoogleResolution {
    let Some(request_policy) = redirect_request_policy(policy) else {
        return GoogleResolution {
            destinations: HashMap::new(),
            failed_redirects: HashMap::new(),
            attempts: Vec::new(),
            failure: Some(SearchFailure::ProviderUnavailable),
            cancelled: false,
        };
    };
    let request_limit = google_redirect_request_limit(result_limit);
    resolve_candidates(
        page,
        request_limit,
        cancellation,
        move |placement, wrapper, token| {
            let request_policy = request_policy.clone();
            async move {
                let request = new_request(wrapper.as_str());
                let response = request
                    .bind(&request_policy)
                    .send_cancellable(&token)
                    .await
                    .map_err(|error| request_error_failure(&error))?;
                Ok(RedirectAttempt {
                    outcome: resolve_response(&wrapper, &response),
                    attempts: attempt_summaries(&response, placement),
                })
            }
        },
    )
    .await
}

async fn resolve_candidates<F, Fut>(
    page: &GoogleParsedPage,
    result_limit: usize,
    cancellation: &CancellationToken,
    mut request: F,
) -> GoogleResolution
where
    F: FnMut(NonZeroU16, url::Url, CancellationToken) -> Fut + Send,
    Fut: Future<Output = Result<RedirectAttempt, SearchFailure>> + Send,
{
    let request_limit = google_redirect_request_limit(result_limit);
    let mut resolution = GoogleResolution {
        destinations: HashMap::new(),
        failed_redirects: HashMap::new(),
        attempts: Vec::new(),
        failure: None,
        cancelled: false,
    };
    mark_limit_skipped_redirects(page, request_limit, &mut resolution.failed_redirects);

    for (placement, wrapper) in page.opaque_redirects().take(request_limit) {
        if cancellation.is_cancelled() {
            resolution.cancelled = true;
            break;
        }
        let attempt = match request(placement, wrapper.clone(), cancellation.clone()).await {
            Ok(attempt) => attempt,
            Err(failure) => {
                resolution
                    .failed_redirects
                    .insert(placement, SearchIssueKind::RedirectResolutionFailed);
                resolution.failure.get_or_insert(failure);
                if cancellation.is_cancelled() {
                    resolution.cancelled = true;
                }
                break;
            }
        };
        resolution.attempts.extend(attempt.attempts);
        match attempt.outcome {
            RedirectResponse::Resolved(destination) => {
                resolution.destinations.insert(placement, destination);
            }
            RedirectResponse::Failed(failure) => {
                resolution.failed_redirects.insert(
                    placement,
                    if failure == SearchFailure::Challenge {
                        SearchIssueKind::RedirectChallenge
                    } else {
                        SearchIssueKind::RedirectResolutionFailed
                    },
                );
                if stop_after_resolution_failure(failure) {
                    resolution.failure = Some(failure);
                    break;
                }
                resolution.failure.get_or_insert(failure);
            }
            RedirectResponse::Cancelled => {
                resolution.cancelled = true;
                break;
            }
        }
        if cancellation.is_cancelled() {
            resolution.cancelled = true;
            break;
        }
    }
    resolution
}

fn mark_limit_skipped_redirects(
    page: &GoogleParsedPage,
    request_limit: usize,
    issues: &mut HashMap<NonZeroU16, SearchIssueKind>,
) {
    for (index, (placement, _wrapper)) in page.opaque_redirects().enumerate() {
        if index >= request_limit {
            issues.insert(placement, SearchIssueKind::RedirectResolutionLimit);
        }
    }
}

fn google_redirect_request_limit(result_limit: usize) -> usize {
    result_limit.min(MAX_GOOGLE_REDIRECT_REQUESTS_PER_SEARCH)
}

pub(super) fn apply(
    mut result: ProviderResult,
    page: GoogleParsedPage,
    resolution: GoogleResolution,
    result_limit: usize,
    output_limit: usize,
) -> ProviderResult {
    result.attempts.extend(resolution.attempts);
    let outcome = page.finish(
        &resolution.destinations,
        &resolution.failed_redirects,
        result_limit,
        output_limit,
    );
    result.outcome = match outcome {
        Ok(outcome) => outcome,
        Err(google::GoogleParseError::NoUsableHits) if resolution.cancelled => {
            ProviderOutcome::Cancelled
        }
        Err(google::GoogleParseError::NoUsableHits) => ProviderOutcome::Failed(
            resolution
                .failure
                .unwrap_or(SearchFailure::MalformedResponse),
        ),
        Err(error) => ProviderOutcome::Failed(match error {
            google::GoogleParseError::OutputLimit => SearchFailure::BudgetExhausted,
            _ => SearchFailure::MalformedResponse,
        }),
    };
    result
}

fn redirect_request_policy(policy: &Policy) -> Option<Policy> {
    let response_limit = AddressableByteLimit::try_from(MAX_GOOGLE_REDIRECT_RESPONSE_BYTES).ok()?;
    let mut request_policy = policy.clone();
    request_policy.page = Page::new(vec![
        Acquisition::DirectHttp.documents([DocumentRequest::ResponseDocument]),
    ])
    .ok()?;
    request_policy.request.direct_http_redirects = DirectHttpRedirects::Disabled;
    request_policy.request.source.content_coded_bytes = response_limit;
    request_policy.request.source.representation_bytes = response_limit;
    request_policy.request.source.unicode_utf8_bytes = response_limit;
    Some(request_policy)
}

const fn request_error_failure(error: &RequestSendError) -> SearchFailure {
    match error {
        RequestSendError::StandardSetup(_) => SearchFailure::ProviderUnavailable,
        RequestSendError::Preparation(_) => SearchFailure::MalformedResponse,
    }
}

const fn stop_after_resolution_failure(failure: SearchFailure) -> bool {
    matches!(
        failure,
        SearchFailure::RateLimited
            | SearchFailure::Challenge
            | SearchFailure::ProviderUnavailable
            | SearchFailure::TransportFailure
    )
}

fn resolve_response(requested: &url::Url, response: &Response) -> RedirectResponse {
    if response.termination() == ResponseTermination::Cancelled
        && response
            .attempts()
            .iter()
            .all(|attempt| !matches!(attempt, AttemptOutcome::Completed(_)))
    {
        return RedirectResponse::Cancelled;
    }

    let Some(attempt) = response.attempts().first() else {
        return RedirectResponse::Failed(SearchFailure::MalformedResponse);
    };
    let status = attempt.status();
    if status == Some(429) {
        return RedirectResponse::Failed(SearchFailure::RateLimited);
    }
    if matches!(status, Some(401 | 403)) {
        return RedirectResponse::Failed(SearchFailure::Challenge);
    }

    match attempt {
        AttemptOutcome::Completed(result) => {
            if result
                .response_body()
                .is_some_and(google::response_is_challenge)
            {
                return RedirectResponse::Failed(SearchFailure::Challenge);
            }
            if !matches!(status, Some(301 | 302 | 303 | 307 | 308)) {
                return RedirectResponse::Failed(if status.is_some_and(|value| value >= 500) {
                    SearchFailure::ProviderUnavailable
                } else {
                    SearchFailure::MalformedResponse
                });
            }
            let location = result
                .response_facts()
                .and_then(|facts| match facts.location() {
                    ObservedHeaderValue::Value(value) => Some(value.as_str()),
                    _ => None,
                });
            location.map_or(
                RedirectResponse::Failed(SearchFailure::MalformedResponse),
                |value| resolve_location(requested, value),
            )
        }
        AttemptOutcome::Failed(failure) => RedirectResponse::Failed(
            super::response::search_failure_for_attempt(failure.diagnostic()),
        ),
        AttemptOutcome::NotStarted(_) => RedirectResponse::Cancelled,
    }
}

fn resolve_location(requested: &url::Url, location: &str) -> RedirectResponse {
    if google::is_google_challenge_redirect(requested, location) {
        return RedirectResponse::Failed(SearchFailure::Challenge);
    }
    google::redirect_destination(requested, location).map_or(
        RedirectResponse::Failed(SearchFailure::MalformedResponse),
        RedirectResponse::Resolved,
    )
}

fn attempt_summaries(response: &Response, placement: NonZeroU16) -> Vec<RequestAttemptSummary> {
    response
        .attempts()
        .iter()
        .map(|attempt| {
            let (source_bytes, diagnostic, terminal, capture_complete) = match attempt {
                AttemptOutcome::Completed(result) => (
                    result.capture_facts().source_bytes(),
                    None,
                    RequestAttemptTerminal::Completed,
                    Some(result.capture_facts().completeness() == CaptureCompleteness::Complete),
                ),
                AttemptOutcome::Failed(failure) => (
                    failure
                        .capture_facts()
                        .and_then(AttemptCaptureFacts::source_bytes),
                    Some(search_attempt_diagnostic(failure.diagnostic())),
                    RequestAttemptTerminal::Failed,
                    failure
                        .capture_facts()
                        .map(|facts| facts.completeness() == CaptureCompleteness::Complete),
                ),
                AttemptOutcome::NotStarted(_) => {
                    (None, None, RequestAttemptTerminal::NotStarted, None)
                }
            };
            RequestAttemptSummary {
                request_id: response.request_id(),
                capture_id: attempt.capture_id(),
                acquisition: attempt.acquisition(),
                http_status: attempt.status(),
                source_bytes,
                diagnostic,
                parser_diagnostic: None,
                document_class: None,
                document_bytes: None,
                capture_complete,
                capture_retention: SearchCaptureRetention::Disabled,
                terminal,
                resolution_placement: Some(placement),
            }
        })
        .collect()
}

#[cfg(test)]
mod tests {
    #![expect(
        clippy::panic_in_result_fn,
        reason = "assertions report resolver regressions"
    )]

    use super::{
        RedirectAttempt, RedirectResponse, attempt_summaries, google_redirect_request_limit,
        mark_limit_skipped_redirects, redirect_request_policy, resolve, resolve_candidates,
        resolve_location,
    };
    use crate::internal::{
        direct_http::ObservedHeaderValue,
        engine::{
            AttemptOutcome, Document,
            request::new as new_request,
            search::{ProviderOutcome, SearchFailure, SearchIssueKind, SearchResultUrl},
        },
        policy::{
            Policy,
            policy::{AcquisitionKind, DirectHttpRedirects, DocumentRequest},
        },
        test_support::direct_http_fixture::{
            FixtureService, Protocol, Response as FixtureResponse,
        },
    };
    use std::{
        collections::HashMap,
        error::Error,
        fmt::Write as _,
        num::NonZeroU16,
        sync::{
            Arc,
            atomic::{AtomicUsize, Ordering},
        },
    };
    use tokio_util::sync::CancellationToken;

    #[test]
    fn per_search_redirect_work_respects_result_limit_and_fixed_cap() {
        assert_eq!(google_redirect_request_limit(0), 0);
        assert_eq!(google_redirect_request_limit(5), 5);
        assert_eq!(google_redirect_request_limit(12), 8);
    }

    #[test]
    fn over_cap_rows_get_a_limit_issue_without_claiming_a_request() -> Result<(), Box<dyn Error>> {
        let page = parsed_wrapper_page(9, 12)?;
        let mut issues = HashMap::new();
        mark_limit_skipped_redirects(&page, 8, &mut issues);
        let ninth = NonZeroU16::new(9).ok_or("invalid placement")?;
        let eighth = NonZeroU16::new(8).ok_or("invalid placement")?;
        assert_eq!(issues.len(), 1);
        assert_eq!(
            issues.get(&ninth),
            Some(&SearchIssueKind::RedirectResolutionLimit)
        );
        assert!(!issues.contains_key(&eighth));

        let mut destinations = HashMap::new();
        for index in 1_u16..=8 {
            let placement = NonZeroU16::new(index).ok_or("invalid placement")?;
            let destination = SearchResultUrl::parse(&format!("https://example.org/{index}"))?;
            destinations.insert(placement, destination);
        }
        let ProviderOutcome::Results(results) = page.finish(&destinations, &issues, 12, 16_384)?
        else {
            return Err("expected partial results at the resolver cap".into());
        };
        assert_eq!(results.hits().len(), 8);
        assert!(results.issues().iter().any(|issue| {
            issue.placement_index == Some(ninth)
                && issue.kind == SearchIssueKind::RedirectResolutionLimit
        }));
        Ok(())
    }

    #[test]
    fn redirect_location_classifier_stops_only_for_observed_google_challenge_paths()
    -> Result<(), Box<dyn Error>> {
        let requested = url::Url::parse("https://www.google.com/goto?url=opaque")?;
        assert!(matches!(
            resolve_location(&requested, "https://www.google.com/sorry/index"),
            RedirectResponse::Failed(SearchFailure::Challenge)
        ));
        assert!(matches!(
            resolve_location(&requested, "https://www.google.com/search?q=another"),
            RedirectResponse::Failed(SearchFailure::MalformedResponse)
        ));
        assert!(matches!(
            resolve_location(&requested, "https://example.org/article"),
            RedirectResponse::Resolved(destination)
                if destination.as_str() == "https://example.org/article"
        ));
        Ok(())
    }

    #[tokio::test]
    async fn rate_limit_and_challenge_stop_the_request_loop_after_one_attempt()
    -> Result<(), Box<dyn Error>> {
        for failure in [SearchFailure::RateLimited, SearchFailure::Challenge] {
            let page = parsed_wrapper_page(3, 5)?;
            let request_count = Arc::new(AtomicUsize::new(0));
            let counted = Arc::clone(&request_count);
            let resolution = resolve_candidates(
                &page,
                3,
                &CancellationToken::new(),
                move |_placement, _wrapper, _token| {
                    let counted = Arc::clone(&counted);
                    async move {
                        counted.fetch_add(1, Ordering::SeqCst);
                        Ok(RedirectAttempt {
                            outcome: RedirectResponse::Failed(failure),
                            attempts: Vec::new(),
                        })
                    }
                },
            )
            .await;
            assert_eq!(request_count.load(Ordering::SeqCst), 1);
            assert_eq!(resolution.failure, Some(failure));
        }
        Ok(())
    }

    fn parsed_wrapper_page(
        row_count: usize,
        result_limit: usize,
    ) -> Result<super::super::super::provider::google::GoogleParsedPage, Box<dyn Error>> {
        let mut html = String::from("<html><body>");
        for index in 1..=row_count {
            write!(
                &mut html,
                "<div class=\"tF2Cxc\"><div class=\"yuRUbf\"><a class=\"zReHs\" href=\"/goto?url=opaque{index}\"><h3>Wrapped {index}</h3></a></div><div class=\"VwiC3b\">Summary</div></div>"
            )?;
        }
        html.push_str("</body></html>");
        let document = Document::observed_dom(
            "google-wrapper",
            1,
            html.as_bytes().to_vec(),
            &Policy::default(),
        )?;
        match super::super::super::provider::google::parse_rows(
            &document,
            &Policy::default(),
            "https://www.google.com/search?q=rust",
            result_limit,
        )? {
            super::super::super::provider::google::GoogleParsedDocument::Results(page) => Ok(page),
            super::super::super::provider::google::GoogleParsedDocument::Challenge => {
                Err("unexpected challenge fixture".into())
            }
        }
    }

    #[tokio::test]
    async fn cancelled_search_token_prevents_first_wrapper_request() -> Result<(), Box<dyn Error>> {
        let page = parsed_wrapper_page(1, 5)?;
        let token = CancellationToken::new();
        token.cancel();
        let resolution = resolve(&page, &Policy::default(), 5, &token).await;
        assert!(resolution.cancelled);
        assert!(
            resolution.attempts.is_empty(),
            "unexpected resolver attempt count: {}",
            resolution.attempts.len()
        );
        assert!(
            resolution.destinations.is_empty(),
            "unexpected resolved destination count: {}",
            resolution.destinations.len()
        );
        Ok(())
    }

    #[test]
    fn redirect_policy_uses_one_bounded_direct_http_acquisition() -> Result<(), Box<dyn Error>> {
        let policy = redirect_request_policy(&Policy::default())
            .ok_or("resolver request policy was invalid")?;
        assert!(matches!(
            policy.request.direct_http_redirects,
            DirectHttpRedirects::Disabled
        ));
        let acquisition = policy
            .page
            .acquisitions
            .first()
            .ok_or("resolver acquisition was missing")?;
        assert_eq!(acquisition.kind(), AcquisitionKind::DirectHttp);
        assert_eq!(
            acquisition.exact_documents(),
            Some(&[DocumentRequest::ResponseDocument][..])
        );
        assert_eq!(policy.request.source.content_coded_bytes.get(), 16_384);
        assert_eq!(policy.request.source.representation_bytes.get(), 16_384);
        assert_eq!(policy.request.source.unicode_utf8_bytes.get(), 16_384);
        Ok(())
    }

    #[tokio::test]
    async fn redirect_request_reads_one_loopback_location_without_following_it()
    -> Result<(), Box<dyn Error + Send + Sync>> {
        let service = FixtureService::start(
            Protocol::Http,
            [
                (
                    "/goto".to_owned(),
                    FixtureResponse::redirect("/destination"),
                ),
                (
                    "/destination".to_owned(),
                    FixtureResponse::bytes(200, Some("text/plain"), b"destination"),
                ),
            ],
        )
        .await;
        let url = service.url("/goto");
        let request_policy = redirect_request_policy(&Policy::default())
            .ok_or("resolver request policy was invalid")?;
        let response = new_request(&url)
            .bind(&request_policy)
            .send_cancellable(&CancellationToken::new())
            .await?;

        assert_eq!(response.attempts().len(), 1);
        let attempt = response
            .attempts()
            .first()
            .ok_or("missing redirect attempt")?;
        assert_eq!(attempt.status(), Some(302));
        let AttemptOutcome::Completed(result) = attempt else {
            return Err("disabled redirect did not retain the first response".into());
        };
        let facts = result
            .response_facts()
            .ok_or("missing bounded response facts")?;
        assert_eq!(facts.final_url().as_str(), url.as_str());
        assert!(matches!(
            facts.location(),
            ObservedHeaderValue::Value(value)
                if value.as_str() == "/destination"
        ));
        assert!(result.capture_archive_ref().is_none());
        let requests = service.requests().await;
        assert_eq!(requests.len(), 1);
        assert_eq!(
            requests.first().map(|request| request.path.as_str()),
            Some("/goto")
        );

        let placement = NonZeroU16::new(3).ok_or("invalid test placement")?;
        let mapped = attempt_summaries(&response, placement)
            .into_iter()
            .next()
            .ok_or("missing resolver attempt summary")?;
        assert_eq!(mapped.resolution_placement, Some(placement));
        let mapped_json = serde_json::to_value(mapped)?;
        assert_eq!(mapped_json["resolution_placement"], 3);

        let mut ordinary = mapped;
        ordinary.resolution_placement = None;
        let ordinary_json = serde_json::to_value(ordinary)?;
        assert!(ordinary_json.get("resolution_placement").is_none());
        service.shutdown().await;
        Ok(())
    }
}
