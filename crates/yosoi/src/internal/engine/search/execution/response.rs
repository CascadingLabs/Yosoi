use crate::internal::policy::{
    Policy,
    policy::{
        Acquisition, AcquisitionKind, DocumentRequest,
        search::{EffectiveProviderRoute, Provider},
    },
};
use crate::internal::web_capture::RequestedWebTarget;

use crate::internal::engine::{
    Document, DocumentOutcome, RequestSendError, Response, ResponseTermination,
    request::execution::{
        AttemptCaptureFacts, AttemptDiagnostic, AttemptDocumentOutcome, AttemptOutcome,
    },
    search::{
        ProviderCharge, ProviderIdentity, ProviderOutcome, ProviderResult, RequestAttemptSummary,
        RequestAttemptTerminal, SearchAttemptDiagnostic, SearchCaptureRetention, SearchFailure,
        SearchParserDiagnostic, SearchProfileFacts, SearchReplayResult, SearchUnavailableReason,
    },
};

use super::super::diagnostics::{
    SearchCapture, SearchReplayPolicy, parse_document, status_failure,
};
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
            resolution_placement: None,
        };
        let parsed = match attempt {
            AttemptOutcome::Completed(result) => {
                let selected_request = selected_provider_document_request(
                    provider,
                    attempt.acquisition(),
                    attempt.status(),
                    result.documents(),
                );
                let selected = selected_request
                    .and_then(|requested| {
                        result
                            .documents()
                            .iter()
                            .find(|document| document.requested() == requested)
                    })
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
                        parser_diagnostic: Some(missing_document_diagnostic(
                            provider,
                            result.documents(),
                        )),
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
                            is_selected_for_parsing(projected.requested(), selected_request);
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
        Provider::DuckDuckGo | Provider::Google => DocumentRequest::RenderedDom,
        Provider::Brave | Provider::Bing => DocumentRequest::ResponseDocument,
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum DocumentProjectionState {
    NotRequested,
    Produced,
    PartialWithDocument,
    PartialWithoutDocument,
    Unavailable,
    Unprojectable,
}

fn document_projection_state(
    requested: DocumentRequest,
    documents: &[AttemptDocumentOutcome],
) -> DocumentProjectionState {
    let Some(projected) = documents
        .iter()
        .find(|document| document.requested() == requested)
    else {
        return DocumentProjectionState::NotRequested;
    };
    match projected.outcome() {
        DocumentOutcome::Produced { .. } => DocumentProjectionState::Produced,
        DocumentOutcome::Partial {
            document: Some(_), ..
        } => DocumentProjectionState::PartialWithDocument,
        DocumentOutcome::Partial { document: None, .. } => {
            DocumentProjectionState::PartialWithoutDocument
        }
        DocumentOutcome::Unavailable { .. } => DocumentProjectionState::Unavailable,
        DocumentOutcome::Unprojectable { .. } => DocumentProjectionState::Unprojectable,
    }
}

fn selected_provider_document_request(
    provider: Provider,
    acquisition: AcquisitionKind,
    status: Option<u16>,
    documents: &[AttemptDocumentOutcome],
) -> Option<DocumentRequest> {
    if provider != Provider::Brave {
        return Some(provider_document_request(provider));
    }
    if status_failure(status).is_some() {
        return None;
    }

    let source = document_projection_state(DocumentRequest::ResponseDocument, documents);
    let rendered_dom = document_projection_state(DocumentRequest::RenderedDom, documents);
    select_brave_document_request(acquisition, status, source, rendered_dom)
}

fn select_brave_document_request(
    acquisition: AcquisitionKind,
    status: Option<u16>,
    source: DocumentProjectionState,
    rendered_dom: DocumentProjectionState,
) -> Option<DocumentRequest> {
    if status_failure(status).is_some() {
        return None;
    }
    if matches!(
        source,
        DocumentProjectionState::Produced | DocumentProjectionState::PartialWithDocument
    ) {
        return Some(DocumentRequest::ResponseDocument);
    }

    let source_unavailable = matches!(
        source,
        DocumentProjectionState::Unavailable
            | DocumentProjectionState::Unprojectable
            | DocumentProjectionState::PartialWithoutDocument
    );
    let browser_acquisition = matches!(acquisition, AcquisitionKind::Browser { .. });
    let rendered_dom_complete = rendered_dom == DocumentProjectionState::Produced;
    if source_unavailable && browser_acquisition && rendered_dom_complete {
        return Some(DocumentRequest::RenderedDom);
    }
    None
}

fn is_selected_for_parsing(requested: DocumentRequest, selected: Option<DocumentRequest>) -> bool {
    selected == Some(requested)
}

fn missing_document_diagnostic(
    provider: Provider,
    documents: &[AttemptDocumentOutcome],
) -> SearchParserDiagnostic {
    let source = document_projection_state(DocumentRequest::ResponseDocument, documents);
    let rendered_dom = document_projection_state(DocumentRequest::RenderedDom, documents);
    match provider {
        Provider::Brave => brave_missing_document_diagnostic(source, rendered_dom),
        Provider::Bing | Provider::DuckDuckGo | Provider::Google => {
            SearchParserDiagnostic::MissingDocument
        }
    }
}

fn brave_missing_document_diagnostic(
    source: DocumentProjectionState,
    rendered_dom: DocumentProjectionState,
) -> SearchParserDiagnostic {
    if [source, rendered_dom].into_iter().any(|state| {
        matches!(
            state,
            DocumentProjectionState::PartialWithDocument
                | DocumentProjectionState::PartialWithoutDocument
        )
    }) {
        SearchParserDiagnostic::IncompleteDocument
    } else {
        SearchParserDiagnostic::MissingDocument
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
        Provider::Google => (
            Some("https://www.google.com/search"),
            Some("google-browser-v1"),
        ),
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
        Provider::Google => "google-rendered-dom-v1",
        Provider::Brave => "brave-source-dom-v1",
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

#[cfg(test)]
mod tests {
    use crate::internal::policy::policy::BrowserMode;

    use super::{
        DocumentProjectionState as State, SearchFailure, SearchParserDiagnostic,
        brave_missing_document_diagnostic, is_selected_for_parsing, select_brave_document_request,
    };
    use crate::internal::policy::policy::{AcquisitionKind, DocumentRequest};

    #[test]
    fn brave_prefers_source_when_both_browser_documents_are_complete() {
        let selected = select_brave_document_request(
            AcquisitionKind::Browser {
                mode: BrowserMode::Headless,
            },
            Some(200),
            State::Produced,
            State::Produced,
        );

        assert_eq!(selected, Some(DocumentRequest::ResponseDocument));
        assert!(is_selected_for_parsing(
            DocumentRequest::ResponseDocument,
            selected
        ));
        assert!(!is_selected_for_parsing(
            DocumentRequest::RenderedDom,
            selected
        ));
    }

    #[test]
    fn brave_uses_produced_rendered_dom_when_browser_source_is_unavailable() {
        let selected = select_brave_document_request(
            AcquisitionKind::Browser {
                mode: BrowserMode::Headless,
            },
            Some(200),
            State::Unavailable,
            State::Produced,
        );

        assert_eq!(selected, Some(DocumentRequest::RenderedDom));
        assert!(!is_selected_for_parsing(
            DocumentRequest::ResponseDocument,
            selected
        ));
        assert!(is_selected_for_parsing(
            DocumentRequest::RenderedDom,
            selected
        ));
    }

    #[test]
    fn brave_uses_produced_rendered_dom_when_browser_source_is_unprojectable() {
        assert_eq!(
            select_brave_document_request(
                AcquisitionKind::Browser {
                    mode: BrowserMode::Headless,
                },
                Some(200),
                State::Unprojectable,
                State::Produced,
            ),
            Some(DocumentRequest::RenderedDom)
        );
    }

    #[test]
    fn brave_uses_produced_rendered_dom_when_partial_source_has_no_document() {
        assert_eq!(
            select_brave_document_request(
                AcquisitionKind::Browser {
                    mode: BrowserMode::Headless
                },
                Some(200),
                State::PartialWithoutDocument,
                State::Produced,
            ),
            Some(DocumentRequest::RenderedDom)
        );
    }

    #[test]
    fn brave_does_not_fallback_to_partial_or_unavailable_rendered_dom() {
        let acquisition = AcquisitionKind::Browser {
            mode: BrowserMode::Headless,
        };
        for rendered_dom in [
            State::PartialWithDocument,
            State::PartialWithoutDocument,
            State::Unavailable,
            State::Unprojectable,
            State::NotRequested,
        ] {
            assert_eq!(
                select_brave_document_request(
                    acquisition,
                    Some(200),
                    State::Unavailable,
                    rendered_dom,
                ),
                None,
                "rendered DOM state {rendered_dom:?} must not be selected as complete"
            );
        }
    }

    #[test]
    fn brave_does_not_fallback_from_direct_http_or_after_http_429() {
        assert_eq!(
            select_brave_document_request(
                AcquisitionKind::DirectHttp,
                Some(200),
                State::Unavailable,
                State::Produced,
            ),
            None
        );
        assert_eq!(
            select_brave_document_request(
                AcquisitionKind::Browser {
                    mode: BrowserMode::Headless,
                },
                Some(429),
                State::Unavailable,
                State::Produced,
            ),
            None
        );
        assert_eq!(
            super::status_failure(Some(429)),
            Some(SearchFailure::RateLimited)
        );
    }

    #[test]
    fn brave_reports_missing_or_incomplete_document_distinctly() {
        assert_eq!(
            brave_missing_document_diagnostic(State::Unavailable, State::Unavailable),
            SearchParserDiagnostic::MissingDocument
        );
        assert_eq!(
            brave_missing_document_diagnostic(State::Unavailable, State::PartialWithoutDocument),
            SearchParserDiagnostic::IncompleteDocument
        );
    }
}
