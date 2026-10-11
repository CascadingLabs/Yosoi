use crate::internal::policy::{
    Policy,
    policy::{
        Acquisition, DocumentRequest,
        search::{EffectiveProviderRoute, Provider},
    },
};
use crate::internal::web_capture::RequestedWebTarget;

use crate::internal::engine::{
    RequestSendError, Response, ResponseTermination,
    request::execution::{AttemptCaptureFacts, AttemptDiagnostic, AttemptOutcome},
    search::{
        ProviderCharge, ProviderIdentity, ProviderOutcome, ProviderResult, RequestAttemptSummary,
        RequestAttemptTerminal, SearchAttemptDiagnostic, SearchFailure, SearchProfileFacts,
        SearchUnavailableReason,
    },
};

use super::super::provider::{bing, brave, duckduckgo};

pub(super) fn request_error_result(
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

pub(super) fn provider_result_from_response(
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
                    Provider::Brave => brave::parse(
                        document,
                        policy,
                        target.as_str(),
                        result_limit,
                        output_limit,
                    )
                    .map_err(|error| {
                        search_parse_failure(matches!(error, brave::BraveParseError::OutputLimit))
                    }),
                    Provider::Bing => bing::parse(
                        document,
                        policy,
                        target.as_str(),
                        result_limit,
                        output_limit,
                    )
                    .map_err(|error| match error {
                        bing::BingParseError::OutputLimit => SearchFailure::BudgetExhausted,
                        bing::BingParseError::QueryMismatch => SearchFailure::QueryMismatch,
                        _ => SearchFailure::MalformedResponse,
                    }),
                    Provider::DuckDuckGo => duckduckgo::parse(
                        document,
                        policy,
                        target.as_str(),
                        result_limit,
                        output_limit,
                    )
                    .map_err(|error| {
                        search_parse_failure(matches!(
                            error,
                            duckduckgo::DuckDuckGoParseError::OutputLimit
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

pub(super) const fn search_parse_failure(output_limited: bool) -> SearchFailure {
    if output_limited {
        SearchFailure::BudgetExhausted
    } else {
        SearchFailure::MalformedResponse
    }
}

pub(super) const fn search_attempt_diagnostic(
    diagnostic: AttemptDiagnostic,
) -> SearchAttemptDiagnostic {
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
        AttemptDiagnostic::BrowserFailure(reason) => {
            SearchAttemptDiagnostic::BrowserFailure(reason)
        }
        AttemptDiagnostic::BrowserFinalizationFailed => {
            SearchAttemptDiagnostic::BrowserFinalizationFailed
        }
        AttemptDiagnostic::BrowserFeatureDisabled => {
            SearchAttemptDiagnostic::BrowserFeatureDisabled
        }
        AttemptDiagnostic::ProjectionFailed => SearchAttemptDiagnostic::ProjectionFailed,
    }
}

pub(super) const fn search_failure_for_attempt(diagnostic: AttemptDiagnostic) -> SearchFailure {
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
        | AttemptDiagnostic::BrowserFailure(_)
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

pub(super) fn failed_provider(
    route: &EffectiveProviderRoute,
    failure: SearchFailure,
) -> ProviderResult {
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
