//! Find candidate URLs and inspect each provider's bounded, typed outcome.

use crate::policy::Policy;
use crate::request::CancellationToken;
use yosoi_engine::search as implementation;

pub use implementation::{
    FeatureCoverage, ImageResult, LocalPlace, ProviderCharge, ProviderIdentity, ProviderOutcome,
    ProviderResult, RequestAttemptSummary, RequestAttemptTerminal, SearchAttemptDiagnostic,
    SearchCoverage, SearchFailure, SearchFeature, SearchHit, SearchHitMetadata, SearchIssue,
    SearchIssueKind, SearchPage, SearchProfileFacts, SearchQueryError, SearchRequestId,
    SearchResponse, SearchResultUrl, SearchSendError, SearchTermination, SearchUnavailableReason,
    WebCoverage,
};

/// Creates query intent without selecting a provider or performing I/O.
pub fn new(query: impl Into<String>) -> Result<SearchRequest, SearchQueryError> {
    SearchRequest::new(query)
}

/// A query authored independently of provider routing and policy budgets.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SearchRequest {
    inner: implementation::SearchRequest,
}

impl SearchRequest {
    /// Rejects empty or oversized queries before any provider I/O.
    pub fn new(query: impl Into<String>) -> Result<Self, SearchQueryError> {
        implementation::new(query).map(|inner| Self { inner })
    }

    /// Returns the correlation identity for this query.
    pub const fn id(&self) -> SearchRequestId {
        self.inner.id()
    }

    /// Returns the query as authored.
    pub fn query(&self) -> &str {
        self.inner.query()
    }

    /// Borrows a complete policy for provider selection and bounded execution.
    pub fn bind(self, policy: &Policy) -> BoundSearchRequest<'_> {
        BoundSearchRequest {
            inner: self.inner.bind(policy),
        }
    }
}

/// Search intent bound to the caller's policy; execution internals stay private.
#[derive(Debug)]
pub struct BoundSearchRequest<'policy> {
    inner: implementation::BoundSearchRequest<'policy>,
}

impl BoundSearchRequest<'_> {
    /// Returns the query correlation identity.
    pub const fn id(&self) -> SearchRequestId {
        self.inner.request().id()
    }

    /// Returns the query as authored.
    pub fn query(&self) -> &str {
        self.inner.request().query()
    }

    /// Returns the borrowed policy.
    pub const fn policy(&self) -> &Policy {
        self.inner.policy()
    }

    /// Resolves the policy without contacting a provider.
    pub fn validate(&self) -> Result<(), SearchSendError> {
        self.inner.prepare().map(|_| ())
    }

    /// Executes through the package's standard provider adapters.
    pub async fn send(&self) -> Result<SearchResponse, SearchSendError> {
        self.inner.send().await
    }

    /// Executes with caller-controlled cancellation.
    pub async fn send_cancellable(
        &self,
        cancellation: &CancellationToken,
    ) -> Result<SearchResponse, SearchSendError> {
        self.inner.send_cancellable(cancellation).await
    }
}
