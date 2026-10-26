//! Provider-neutral Search request and result vocabulary.
//!
//! Search execution composes the existing Requests lifecycle. Provider
//! selection and acquisition limits belong to the complete Policy value.

mod diagnostics;
mod execution;
mod outcome;
mod preparation;
mod provider;
mod query;
mod result;
mod target;

pub use diagnostics::{
    SearchCapture, SearchCaptureRetention, SearchParserDecision, SearchParserDiagnostic,
    SearchParserStatus, SearchReplayPolicy, SearchReplayResult, parse_document, status_failure,
};
pub use execution::SearchExecutionSetupError;
pub use outcome::{
    ProviderCharge, ProviderIdentity, ProviderOutcome, ProviderResult, RequestAttemptSummary,
    RequestAttemptTerminal, SearchAttemptDiagnostic, SearchFailure, SearchProfileFacts,
    SearchResponse, SearchTermination, SearchUnavailableReason,
};
pub use preparation::{PreparedSearch, SearchSendError};
pub use query::{BoundSearchRequest, SearchQueryError, SearchRequest, SearchRequestId};
pub use result::{
    FeatureCoverage, ImageResult, LocalPlace, SearchCoverage, SearchFeature, SearchHit,
    SearchHitMetadata, SearchIssue, SearchIssueKind, SearchPage, SearchResultUrl, WebCoverage,
};

/// Creates one query intent without selecting a provider or performing I/O.
pub fn new(query: impl Into<String>) -> Result<SearchRequest, SearchQueryError> {
    SearchRequest::new(query)
}
