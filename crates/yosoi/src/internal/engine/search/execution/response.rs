use crate::internal::policy::{
    Policy,
    policy::{
        Acquisition, AcquisitionKind, DocumentRequest,
        search::{EffectiveProviderRoute, Provider},
    },
};
use crate::internal::web_capture::RequestedWebTarget;

use crate::internal::engine::{
    Document, RequestSendError, Response, ResponseTermination,
    request::execution::{AttemptCaptureFacts, AttemptDiagnostic, AttemptOutcome},
    search::{
        ProviderCharge, ProviderIdentity, ProviderOutcome, ProviderResult, RequestAttemptSummary,
        RequestAttemptTerminal, SearchAttemptDiagnostic, SearchCaptureRetention, SearchFailure,
        SearchParserDiagnostic, SearchProfileFacts, SearchReplayResult, SearchUnavailableReason,
    },
};

use super::super::diagnostics::status_failure;
use super::super::diagnostics::{SearchCapture, SearchReplayPolicy, parse_document};
use crate::internal::web_capture::CaptureCompleteness;

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
            captures: Vec::new(),
            outcome: ProviderOutcome::Failed(SearchFailure::MalformedResponse),
            charge: ProviderCharge::Unknown,
        },
    }
}

#[derive(Clone, Copy)]
pub(super) struct ProviderResponseLimits {
    pub(super) results: usize,
    pub(super) output_bytes: usize,
    pub(super) capture_bytes: Option<usize>,
}

pub(super) fn provider_result_from_response(
    provider: Provider,
    policy: &Policy,
    target: &RequestedWebTarget,
    limits: ProviderResponseLimits,
    profile: SearchProfileFacts,
    response: &Response,
) -> ProviderResult {
    let ProviderResponseLimits {
        results: result_limit,
        output_bytes: output_limit,
        capture_bytes: capture_limit,
    } = limits;
    let mut attempts = Vec::with_capacity(response.attempts().len());
    let mut captures = Vec::new();
    let mut capture_remaining = capture_limit.unwrap_or(0);
    let mut any_attempt_started = false;
    let mut parser_ran = false;
    let mut first_failure = None;
    let mut selected_outcome = None;
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
        let facts = match attempt {
            AttemptOutcome::Completed(result) => Some(result.capture_facts()),
            AttemptOutcome::Failed(failure) => failure.capture_facts(),
            AttemptOutcome::NotStarted(_) => None,
        };
        let mut summary = RequestAttemptSummary {
            request_id: response.request_id(),
            capture_id: attempt.capture_id(),
            acquisition: attempt.acquisition(),
            http_status: attempt.status(),
            source_bytes: facts.and_then(AttemptCaptureFacts::source_bytes),
            diagnostic: match attempt {
                AttemptOutcome::Failed(failure) => {
                    Some(search_attempt_diagnostic(failure.diagnostic()))
                }
                AttemptOutcome::Completed(_) | AttemptOutcome::NotStarted(_) => None,
            },
            parser_diagnostic: None,
            document_class: None,
            document_bytes: None,
            capture_complete: facts
                .map(|facts| facts.completeness() == CaptureCompleteness::Complete),
            capture_retention: if capture_limit.is_some() {
                SearchCaptureRetention::MissingDocument
            } else {
                SearchCaptureRetention::Disabled
            },
            terminal,
        };
        let parsed = match attempt {
            AttemptOutcome::Completed(result) => {
                let selected = result
                    .documents()
                    .iter()
                    .find(|document| document.requested() == provider_document_request(provider))
                    .and_then(|document| document.outcome().document());
                summary.document_class = selected.map(Document::class);
                summary.document_bytes = selected.map(Document::byte_len);
                let parsed = match (status_failure(attempt.status()), selected) {
                    (Some(failure), _) => SearchReplayResult {
                        outcome: ProviderOutcome::Failed(failure),
                        parser_diagnostic: None,
                    },
                    (None, Some(document)) => {
                        parser_ran = true;
                        parse_document(
                            provider,
                            document,
                            policy,
                            target.as_str(),
                            result_limit,
                            output_limit,
                        )
                    }
                    (None, None) => SearchReplayResult {
                        outcome: ProviderOutcome::Failed(SearchFailure::MalformedResponse),
                        parser_diagnostic: Some(SearchParserDiagnostic::MissingDocument),
                    },
                };
                summary.parser_diagnostic = parsed.parser_diagnostic;
                if capture_limit.is_some() {
                    for projected in result.documents() {
                        let Some(document) = projected.outcome().document() else {
                            continue;
                        };
                        let Ok(bytes) = usize::try_from(document.byte_len()) else {
                            summary.capture_retention = SearchCaptureRetention::ByteLimit;
                            continue;
                        };
                        if bytes > capture_remaining {
                            summary.capture_retention = SearchCaptureRetention::ByteLimit;
                            continue;
                        }
                        capture_remaining = capture_remaining.saturating_sub(bytes);
                        if summary.capture_retention != SearchCaptureRetention::ByteLimit {
                            summary.capture_retention = SearchCaptureRetention::Retained;
                        }
                        let selected_for_parsing =
                            projected.requested() == provider_document_request(provider);
                        let observed =
                            if selected_for_parsing || status_failure(attempt.status()).is_some() {
                                parsed.clone()
                            } else {
                                parse_document(
                                    provider,
                                    document,
                                    policy,
                                    target.as_str(),
                                    result_limit,
                                    output_limit,
                                )
                            };
                        captures.push(SearchCapture {
                            document: document.clone(),
                            provider,
                            profile,
                            adapter_version: provider_adapter_identity(
                                provider,
                                Some(attempt.acquisition()),
                            )
                            .1,
                            parser_version: provider_parser_version(provider),
                            request_id: response.request_id().to_string(),
                            capture_id: attempt.capture_id(),
                            provider_page_url: target.as_str().to_owned(),
                            original_provider_page_url: target.as_str().to_owned(),
                            final_url: result
                                .capture_facts()
                                .final_target()
                                .map(|url| url.as_str().to_owned()),
                            http_status: attempt.status(),
                            completeness: result.capture_facts().completeness(),
                            environment: result.capture_facts().environment().clone(),
                            replay_policy: SearchReplayPolicy::from_policy(
                                policy,
                                result_limit,
                                output_limit,
                            ),
                            selected_for_parsing,
                            observed,
                        });
                    }
                }
                parsed.outcome
            }
            AttemptOutcome::Failed(failure) => ProviderOutcome::Failed(
                status_failure(attempt.status())
                    .unwrap_or_else(|| search_failure_for_attempt(failure.diagnostic())),
            ),
            AttemptOutcome::NotStarted(_) => {
                ProviderOutcome::Failed(SearchFailure::TransportFailure)
            }
        };
        match parsed {
            outcome @ (ProviderOutcome::Results(_) | ProviderOutcome::Empty) => {
                if selected_outcome.is_none() {
                    selected_outcome = Some(outcome);
                }
            }
            ProviderOutcome::Failed(failure) => {
                first_failure.get_or_insert(failure);
            }
            ProviderOutcome::Cancelled => {
                first_failure.get_or_insert(SearchFailure::TransportFailure);
            }
            ProviderOutcome::NotStarted(_) => {
                first_failure.get_or_insert(SearchFailure::MalformedResponse);
            }
        }
        attempts.push(summary);
    }
    let outcome = selected_outcome.unwrap_or_else(|| {
        if response.termination() == ResponseTermination::Cancelled {
            ProviderOutcome::Cancelled
        } else {
            ProviderOutcome::Failed(first_failure.unwrap_or(SearchFailure::MalformedResponse))
        }
    });
    let (endpoint, adapter_version) = if any_attempt_started {
        provider_adapter_identity(provider, profile.acquisition)
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
        captures,
        outcome,
        charge: ProviderCharge::Unknown,
    }
}

const fn provider_document_request(provider: Provider) -> DocumentRequest {
    match provider {
        Provider::DuckDuckGo => DocumentRequest::RenderedDom,
        Provider::Brave | Provider::Bing => DocumentRequest::ResponseDocument,
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

const fn provider_adapter_identity(
    provider: Provider,
    acquisition: Option<AcquisitionKind>,
) -> (Option<&'static str>, Option<&'static str>) {
    match provider {
        Provider::Brave => (
            Some("https://search.brave.com/search"),
            Some(match acquisition {
                Some(AcquisitionKind::Browser { .. }) => "brave-browser-v1",
                _ => "brave-direct-http-v1",
            }),
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
        captures: Vec::new(),
        outcome: ProviderOutcome::Failed(failure),
        charge: ProviderCharge::Unknown,
    }
}
