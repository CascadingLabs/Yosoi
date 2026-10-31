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

use super::{
    SearchCapture, SearchCaptureRetention, SearchPage, SearchParserDiagnostic, SearchRequestId,
};
use crate::internal::documents::DocumentClass;

/// Content-free details of the acquisition chosen for one provider.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct SearchProfileFacts {
    /// Selected acquisition route, absent when no route could be resolved.
    pub acquisition: Option<AcquisitionKind>,
    /// Certification state of the provider defaults used for route selection.
    pub defaults_status: ProviderDefaultsStatus,
    /// Version of package-owned defaults, absent for routes without such defaults.
    pub defaults_version: Option<ProviderDefaultsVersion>,
    /// Identity of the resolved Requests policy, absent if no Request was prepared.
    pub effective_request_policy: Option<EffectivePolicyIdentity>,
}

/// Exact answering provider and adapter identity, when an adapter actually ran.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ProviderIdentity {
    /// Provider occupying this authored policy slot.
    pub provider: Provider,
    /// Adapter endpoint label, absent if an adapter did not run.
    pub endpoint: Option<&'static str>,
    /// Adapter implementation version, absent if an adapter did not run.
    pub adapter_version: Option<&'static str>,
    /// Response parser version, absent if an adapter did not run.
    pub parser_version: Option<&'static str>,
}

/// Secret-safe failure class from the underlying Requests attempt.
#[derive(Clone, Copy, Debug, Eq, PartialEq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SearchAttemptDiagnostic {
    /// No executor context was available for the selected acquisition.
    MissingExecutionContext,
    /// Authored policy could not be resolved into an executable request.
    PolicyResolutionFailed,
    /// Direct HTTP acquisition failed at the transport boundary.
    DirectHttpTransport,
    /// The HTTP response body could not be acquired successfully.
    DirectHttpBodyFailed,
    /// HTTP acquisition could not finalize its capture artifacts.
    DirectHttpFinalizationFailed,
    /// Browser acquisition observed caller cancellation.
    BrowserCancelled,
    /// Browser acquisition observed cancellation and then failed cleanup.
    BrowserCancelledCleanupFailed,
    /// Browser resource cleanup failed after acquisition.
    BrowserCleanupFailed,
    /// Browser acquisition failed without a more specific failure classification.
    BrowserCaptureFailed,
    /// Browser acquisition failed with the supplied typed failure reason.
    BrowserFailure(BrowserFailureReason),
    /// Browser acquisition could not finalize its capture artifacts.
    BrowserFinalizationFailed,
    /// The selected browser acquisition requires a feature absent from this build.
    BrowserFeatureDisabled,
    /// Acquired content could not be projected into the requested document outputs.
    ProjectionFailed,
}

/// A bounded summary of one underlying Requests attempt.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RequestAttemptSummary {
    /// Parent Request for this acquisition, including a recovery Request.
    pub request_id: RequestId,
    /// Identity allocated to this acquisition's capture.
    pub capture_id: CaptureId,
    /// Acquisition mechanism selected by the resolved policy.
    pub acquisition: AcquisitionKind,
    /// Observed HTTP status, absent if no status was recorded.
    pub http_status: Option<u16>,
    /// Exact retained source artifact bytes when a completed Request recorded them.
    pub source_bytes: Option<u64>,
    /// Bounded underlying failure classification, absent when none was recorded.
    pub diagnostic: Option<SearchAttemptDiagnostic>,
    /// Structural parser failure, separate from acquisition failures and provider blocks.
    pub parser_diagnostic: Option<SearchParserDiagnostic>,
    /// Representation selected for provider parsing, when available.
    pub document_class: Option<DocumentClass>,
    /// Retained bytes of the document selected for parsing, when available.
    pub document_bytes: Option<u64>,
    /// Whether the capture was complete, independent of parser success.
    pub capture_complete: Option<bool>,
    /// Explicit diagnostic document retention state.
    pub capture_retention: SearchCaptureRetention,
    /// Whether the acquisition finished, failed, or never started.
    pub terminal: RequestAttemptTerminal,
}

/// Execution state of an acquisition, independent of provider parsing success.
#[derive(Clone, Copy, Debug, Eq, PartialEq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RequestAttemptTerminal {
    /// Acquisition completed; the provider response may still be unusable.
    Completed,
    /// Acquisition started and returned a typed failure.
    Failed,
    /// Acquisition was skipped before starting, for example after cancellation.
    NotStarted,
}

/// Provider-reported monetary charge. Public-page scraping currently reports
/// Unknown rather than inventing a zero cost.
#[derive(Clone, Debug, Eq, PartialEq, serde::Serialize)]
#[serde(tag = "status", content = "value", rename_all = "snake_case")]
pub enum ProviderCharge {
    /// No monetary charge was reported; this is not evidence of zero cost.
    Unknown,
    /// The provider reported a monetary amount without conversion or estimation.
    Known {
        /// Provider-reported currency identifier.
        currency: String,
        /// Provider-reported amount kept as text to avoid floating-point rounding.
        amount: String,
    },
}

/// Provider-level reason that a started search did not yield usable results.
#[derive(Clone, Copy, Debug, Eq, PartialEq, serde::Deserialize, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SearchFailure {
    /// The provider reported throttling or a rate-limit response.
    RateLimited,
    /// The response was classified as an access challenge rather than search results.
    Challenge,
    /// The provider or required acquisition adapter was unavailable.
    ProviderUnavailable,
    /// Acquired content could not be interpreted as a valid provider response.
    MalformedResponse,
    /// Organic rows did not match a distinctive requested query term.
    QueryMismatch,
    /// Acquisition failed before usable provider content could be parsed.
    TransportFailure,
    /// A parser or shared output resource budget prevented a usable result.
    BudgetExhausted,
}

/// Reason an authored provider slot did not start a search Request.
#[derive(Clone, Copy, Debug, Eq, PartialEq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SearchUnavailableReason {
    /// Package-owned defaults have not been certified for this provider route.
    DefaultUncertified,
    /// No supported adapter is available for the selected provider.
    AdapterUnavailable,
    /// The requested provider capability is unsupported by the selected adapter.
    UnsupportedCapability,
    /// Request preparation or adapter setup failed before execution began.
    RequestSetupFailed,
    /// Caller cancellation was observed before the slot started.
    Cancelled,
    /// The shared search deadline expired before the slot started.
    DeadlineReached,
}

/// Terminal interpretation of one selected provider.
#[derive(Clone, Eq, PartialEq, serde::Serialize)]
#[serde(tag = "status", content = "value", rename_all = "snake_case")]
pub enum ProviderOutcome {
    /// Usable normalized results; inspect page coverage for extraction limitations.
    Results(SearchPage),
    /// The provider response contained no accepted results.
    Empty,
    /// Started provider work ended without a usable response for the supplied reason.
    Failed(SearchFailure),
    /// Started provider work observed caller cancellation.
    Cancelled,
    /// No provider Request started; the reason explains why the slot was retained.
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
    pub(in crate::internal::engine) captures: Vec<SearchCapture>,
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
            captures: Vec::new(),
            outcome: ProviderOutcome::NotStarted(reason),
            charge: ProviderCharge::Unknown,
        }
    }

    /// Returns the provider selected for this authored policy slot.
    pub const fn provider(&self) -> Provider {
        self.identity.provider
    }

    /// Returns the recorded provider and adapter identities without response content.
    pub const fn identity(&self) -> ProviderIdentity {
        self.identity
    }

    /// Returns route-selection and effective-policy facts for this slot.
    pub const fn profile(&self) -> SearchProfileFacts {
        self.profile
    }

    /// Returns the underlying Request identity, or `None` if no Request started.
    pub const fn request_id(&self) -> Option<RequestId> {
        self.request_id
    }

    /// Borrows the shorter query used for off-query recovery, when attempted.
    ///
    /// This may contain user query content and should not be logged as a diagnostic.
    pub fn recovery_query(&self) -> Option<&str> {
        self.recovery_query.as_deref()
    }

    /// Borrows underlying acquisition summaries, including recovery Request attempts.
    pub fn attempts(&self) -> &[RequestAttemptSummary] {
        &self.attempts
    }

    /// Borrows opt-in bounded evidence, including original and recovery documents.
    ///
    /// Empty captures do not establish absence: inspect each attempt's retention state.
    pub fn captures(&self) -> &[SearchCapture] {
        &self.captures
    }

    /// Borrows the terminal provider interpretation; acquisition success alone is insufficient.
    pub const fn outcome(&self) -> &ProviderOutcome {
        &self.outcome
    }

    /// Borrows reported monetary charge facts; unknown charges are not zero charges.
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
            .field("capture_count", &self.captures.len())
            .field("outcome", &self.outcome)
            .field("charge", &self.charge)
            .finish()
    }
}

/// Scheduler termination for the whole search, independent of provider success.
#[derive(Clone, Copy, Debug, Eq, PartialEq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SearchTermination {
    /// Scheduling ended without observing cancellation or exhausting its deadline.
    /// Individual providers can still have failures or incomplete results.
    Completed,
    /// Scheduling observed caller cancellation; retained provider outcomes remain available.
    Cancelled,
    /// Scheduling stopped at the shared deadline; not all providers necessarily ran.
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
    /// Returns the identity assigned to this cross-provider search.
    pub const fn request_id(&self) -> SearchRequestId {
        self.request_id
    }

    /// Returns the resolved search policy identity used for this execution.
    pub const fn policy_identity(&self) -> EffectivePolicyIdentity {
        self.policy_identity
    }

    /// Borrows one result per selected provider in authored policy order.
    ///
    /// Slots that failed or never started remain present; completion order does
    /// not reorder the collection.
    pub fn providers(&self) -> &[ProviderResult] {
        &self.providers
    }

    /// Returns the scheduler's stopping condition, not a claim of provider success.
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
