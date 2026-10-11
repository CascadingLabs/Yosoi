use std::fmt;

use crate::internal::policy::{
    EffectivePolicyIdentity,
    policy::{
        Acquisition, AcquisitionKind,
        search::{
            EffectiveProviderRoute, Provider, ProviderDefaultsStatus, ProviderDefaultsVersion,
        },
    },
};
use crate::internal::types::CaptureId;

use crate::internal::engine::{BrowserFailureReason, request::RequestId};

use super::{SearchPage, SearchRequestId};

/// Content-free details of the acquisition chosen for one provider.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct SearchProfileFacts {
    pub acquisition: Option<AcquisitionKind>,
    pub defaults_status: ProviderDefaultsStatus,
    pub defaults_version: Option<ProviderDefaultsVersion>,
    pub effective_request_policy: Option<EffectivePolicyIdentity>,
}

/// Exact answering provider and adapter identity, when an adapter actually ran.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ProviderIdentity {
    pub provider: Provider,
    pub endpoint: Option<&'static str>,
    pub adapter_version: Option<&'static str>,
    pub parser_version: Option<&'static str>,
}

/// Secret-safe failure class from the underlying Requests attempt.
#[derive(Clone, Copy, Debug, Eq, PartialEq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SearchAttemptDiagnostic {
    MissingExecutionContext,
    PolicyResolutionFailed,
    DirectHttpTransport,
    DirectHttpBodyFailed,
    DirectHttpFinalizationFailed,
    BrowserCancelled,
    BrowserCancelledCleanupFailed,
    BrowserCleanupFailed,
    BrowserCaptureFailed,
    BrowserFailure(BrowserFailureReason),
    BrowserFinalizationFailed,
    BrowserFeatureDisabled,
    ProjectionFailed,
}

/// A bounded summary of one underlying Requests attempt.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RequestAttemptSummary {
    /// Parent Request for this acquisition, including a recovery Request.
    pub request_id: RequestId,
    pub capture_id: CaptureId,
    pub acquisition: AcquisitionKind,
    pub http_status: Option<u16>,
    /// Exact retained source artifact bytes when a completed Request recorded them.
    pub source_bytes: Option<u64>,
    pub diagnostic: Option<SearchAttemptDiagnostic>,
    pub terminal: RequestAttemptTerminal,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RequestAttemptTerminal {
    Completed,
    Failed,
    NotStarted,
}

/// Provider-reported monetary charge. Public-page scraping currently reports
/// Unknown rather than inventing a zero cost.
#[derive(Clone, Debug, Eq, PartialEq, serde::Serialize)]
#[serde(tag = "status", content = "value", rename_all = "snake_case")]
pub enum ProviderCharge {
    Unknown,
    Known { currency: String, amount: String },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SearchFailure {
    RateLimited,
    Challenge,
    ProviderUnavailable,
    MalformedResponse,
    /// Organic rows did not match a distinctive requested query term.
    QueryMismatch,
    TransportFailure,
    BudgetExhausted,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SearchUnavailableReason {
    DefaultUncertified,
    AdapterUnavailable,
    UnsupportedCapability,
    RequestSetupFailed,
    Cancelled,
    DeadlineReached,
}

/// Terminal interpretation of one selected provider.
#[derive(Clone, Eq, PartialEq, serde::Serialize)]
#[serde(tag = "status", content = "value", rename_all = "snake_case")]
pub enum ProviderOutcome {
    Results(SearchPage),
    Empty,
    Failed(SearchFailure),
    Cancelled,
    NotStarted(SearchUnavailableReason),
}

impl fmt::Debug for ProviderOutcome {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Results(page) => formatter.debug_tuple("Results").field(page).finish(),
            Self::Empty => formatter.write_str("Empty"),
            Self::Failed(failure) => formatter.debug_tuple("Failed").field(failure).finish(),
            Self::Cancelled => formatter.write_str("Cancelled"),
            Self::NotStarted(reason) => formatter.debug_tuple("NotStarted").field(reason).finish(),
        }
    }
}

/// One provider slot, kept in authored Policy order even when work completes
/// in another order.
pub struct ProviderResult {
    pub(in crate::internal::engine) identity: ProviderIdentity,
    pub(in crate::internal::engine) profile: SearchProfileFacts,
    pub(in crate::internal::engine) request_id: Option<RequestId>,
    /// Shorter provider query attempted after a detected off-query response.
    pub(in crate::internal::engine) recovery_query: Option<String>,
    pub(in crate::internal::engine) attempts: Vec<RequestAttemptSummary>,
    pub(in crate::internal::engine) outcome: ProviderOutcome,
    pub(in crate::internal::engine) charge: ProviderCharge,
}

impl ProviderResult {
    /// Retains one authored provider slot when no Request was started.
    pub(in crate::internal::engine) fn not_started(
        route: &EffectiveProviderRoute,
        reason: SearchUnavailableReason,
    ) -> Self {
        let acquisition = route
            .page()
            .and_then(|page| page.acquisitions.first())
            .map(Acquisition::kind);
        Self {
            identity: ProviderIdentity {
                provider: route.provider(),
                endpoint: None,
                adapter_version: None,
                parser_version: None,
            },
            profile: SearchProfileFacts {
                acquisition,
                defaults_status: route.defaults_status(),
                defaults_version: route.defaults_version(),
                effective_request_policy: None,
            },
            request_id: None,
            recovery_query: None,
            attempts: Vec::new(),
            outcome: ProviderOutcome::NotStarted(reason),
            charge: ProviderCharge::Unknown,
        }
    }

    pub const fn provider(&self) -> Provider {
        self.identity.provider
    }

    pub const fn identity(&self) -> ProviderIdentity {
        self.identity
    }

    pub const fn profile(&self) -> SearchProfileFacts {
        self.profile
    }

    pub const fn request_id(&self) -> Option<RequestId> {
        self.request_id
    }

    pub fn recovery_query(&self) -> Option<&str> {
        self.recovery_query.as_deref()
    }

    pub fn attempts(&self) -> &[RequestAttemptSummary] {
        &self.attempts
    }

    pub const fn outcome(&self) -> &ProviderOutcome {
        &self.outcome
    }

    pub const fn charge(&self) -> &ProviderCharge {
        &self.charge
    }
}

impl fmt::Debug for ProviderResult {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ProviderResult")
            .field("identity", &self.identity)
            .field("profile", &self.profile)
            .field("request_id", &self.request_id)
            .field("recovery_attempted", &self.recovery_query.is_some())
            .field("attempt_count", &self.attempts.len())
            .field("outcome", &self.outcome)
            .field("charge", &self.charge)
            .finish()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SearchTermination {
    Completed,
    Cancelled,
    DeadlineReached,
}

/// The result of one query across all providers selected by Policy.
pub struct SearchResponse {
    pub(in crate::internal::engine) request_id: SearchRequestId,
    pub(in crate::internal::engine) policy_identity: EffectivePolicyIdentity,
    pub(in crate::internal::engine) providers: Vec<ProviderResult>,
    pub(in crate::internal::engine) termination: SearchTermination,
}

impl SearchResponse {
    pub const fn request_id(&self) -> SearchRequestId {
        self.request_id
    }

    pub const fn policy_identity(&self) -> EffectivePolicyIdentity {
        self.policy_identity
    }

    pub fn providers(&self) -> &[ProviderResult] {
        &self.providers
    }

    pub const fn termination(&self) -> SearchTermination {
        self.termination
    }
}

impl fmt::Debug for SearchResponse {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("SearchResponse")
            .field("request_id", &self.request_id)
            .field("policy_identity", &self.policy_identity)
            .field("provider_count", &self.providers.len())
            .field("termination", &self.termination)
            .finish()
    }
}
