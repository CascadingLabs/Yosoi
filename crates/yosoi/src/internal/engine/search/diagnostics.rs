//! Bounded parser evidence shared by live execution and offline replay.

use std::fmt;

use serde::{Deserialize, Serialize};

use crate::internal::{
    engine::{Document, search::ProviderOutcome},
    policy::{
        Policy,
        policy::{Documents, Locators, Tuning, search::Provider},
    },
    types::CaptureId,
    web_capture::{CaptureCompleteness, CaptureEnvironment},
};

use super::provider::{bing, brave, duckduckgo};

/// Precise parser stage, independent of transport success and provider availability.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SearchParserDiagnostic {
    /// The selected document was absent after acquisition or projection.
    MissingDocument,
    /// The document did not contain a recognized provider page structure.
    UnrecognizedPage,
    /// Required document or locator evidence was incomplete.
    IncompleteDocument,
    /// Recognized rows yielded no valid organic destinations.
    NoUsableHits,
    /// Legacy parser classification for results that failed a query fidelity check.
    QueryMismatch,
    /// A normalized output budget prevented a usable result.
    OutputLimit,
    /// The retained representation is unsupported by this provider parser.
    UnsupportedDocumentClass,
    /// The supplied provider page URL was invalid or outside its expected endpoint.
    InvalidPageUrl,
    /// An invalid result limit, locator query, or locator plan prevented parsing.
    InvalidConfiguration,
    /// Document location failed before usable rows were extracted.
    LocateFailed,
    /// Locator results violated the provider's expected row contract.
    InvalidLocatorResult,
    /// A parser returned a failure without a more precise structural reason.
    Unknown,
}

/// Whether explicit diagnostic capture retained every available document.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SearchCaptureRetention {
    /// Document retention was not requested; content-free diagnostics remain present.
    Disabled,
    /// Every available projected document fit in the diagnostic byte quota.
    Retained,
    /// At least one complete document exceeded the remaining diagnostic byte quota.
    ByteLimit,
    /// No projected document was available to retain.
    MissingDocument,
}

/// A parser result from retained evidence; replay performs no network or browser I/O.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct SearchReplayResult {
    /// Provider interpretation of this single document, before cross-request recovery.
    pub outcome: ProviderOutcome,
    /// Structural failure reason, absent for results, empty pages, or provider blocks.
    pub parser_diagnostic: Option<SearchParserDiagnostic>,
}

/// Content-free parser decision that can be compared across source revisions.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SearchParserDecision {
    /// Single-document result category; acquisition success is a separate fact.
    pub status: SearchParserStatus,
    /// Coarse provider failure when the parser did not produce usable results.
    pub failure: Option<super::SearchFailure>,
    /// Precise structural parser reason when one was recorded.
    pub parser_diagnostic: Option<SearchParserDiagnostic>,
    /// Number of accepted organic hits; zero alone does not establish an empty result.
    pub hit_count: usize,
    /// Whether organic extraction coverage was partial.
    pub partial: bool,
}

/// Terminal category for parsing a single retained document.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SearchParserStatus {
    /// The parser returned usable organic results.
    Results,
    /// The parser recognized an actual empty result page.
    Empty,
    /// The parser or provider reported a classified failure.
    Failed,
    /// Parsing reported cancellation.
    Cancelled,
    /// Parsing did not start.
    NotStarted,
}

impl SearchReplayResult {
    /// Summarizes the decision without query, URL, title, or snippet content.
    pub fn decision(&self) -> SearchParserDecision {
        let (status, failure, hit_count, partial) = match &self.outcome {
            ProviderOutcome::Results(page) => (
                SearchParserStatus::Results,
                None,
                page.hits().len(),
                page.coverage().web() == super::WebCoverage::Partial,
            ),
            ProviderOutcome::Empty => (SearchParserStatus::Empty, None, 0, false),
            ProviderOutcome::Failed(failure) => {
                (SearchParserStatus::Failed, Some(*failure), 0, false)
            }
            ProviderOutcome::Cancelled => (SearchParserStatus::Cancelled, None, 0, false),
            ProviderOutcome::NotStarted(_) => (SearchParserStatus::NotStarted, None, 0, false),
        };
        SearchParserDecision {
            status,
            failure,
            parser_diagnostic: self.parser_diagnostic,
            hit_count,
            partial,
        }
    }
}

/// Secret-free parsing policy needed to reproduce the original bounded decision.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SearchReplayPolicy {
    /// Document parser resource bounds used by the provider Request.
    pub documents: Documents,
    /// Locator evaluation resource bounds used by the provider Request.
    pub locators: Locators,
    /// Parser tuning used by the provider Request.
    pub tuning: Tuning,
    /// Maximum retained organic results in this parser invocation.
    pub result_limit: usize,
    /// Maximum retained normalized output bytes in this parser invocation.
    pub output_limit: usize,
}

impl SearchReplayPolicy {
    pub(crate) const fn from_policy(
        policy: &Policy,
        result_limit: usize,
        output_limit: usize,
    ) -> Self {
        Self {
            documents: policy.documents,
            locators: policy.locators,
            tuning: policy.tuning,
            result_limit,
            output_limit,
        }
    }
}

/// One explicitly retained projected document, with no cookies or transport configuration.
///
/// URLs and document bytes contain query/page content. Retention is opt-in and is
/// bounded separately from normalized output by the Search output byte quota.
#[derive(Clone)]
pub struct SearchCapture {
    pub(crate) document: Document,
    pub(crate) provider: Provider,
    #[allow(
        dead_code,
        reason = "Retained by the SDK capture facade, which is not compiled in the engine-only benchmark harness."
    )]
    pub(crate) profile: super::SearchProfileFacts,
    #[allow(
        dead_code,
        reason = "Retained by the SDK capture facade, which is not compiled in the engine-only benchmark harness."
    )]
    pub(crate) adapter_version: Option<&'static str>,
    #[allow(
        dead_code,
        reason = "Retained by the SDK capture facade, which is not compiled in the engine-only benchmark harness."
    )]
    pub(crate) parser_version: &'static str,
    pub(crate) request_id: String,
    pub(crate) capture_id: CaptureId,
    #[allow(
        dead_code,
        reason = "Retained by the SDK capture facade, which is not compiled in the engine-only benchmark harness."
    )]
    pub(crate) provider_page_url: String,
    pub(crate) original_provider_page_url: String,
    #[allow(
        dead_code,
        reason = "Retained by the SDK capture facade, which is not compiled in the engine-only benchmark harness."
    )]
    pub(crate) final_url: Option<String>,
    #[allow(
        dead_code,
        reason = "Retained by the SDK capture facade, which is not compiled in the engine-only benchmark harness."
    )]
    pub(crate) http_status: Option<u16>,
    #[allow(
        dead_code,
        reason = "Retained by the SDK capture facade, which is not compiled in the engine-only benchmark harness."
    )]
    pub(crate) completeness: CaptureCompleteness,
    #[allow(
        dead_code,
        reason = "Retained by the SDK capture facade, which is not compiled in the engine-only benchmark harness."
    )]
    pub(crate) environment: CaptureEnvironment,
    #[allow(
        dead_code,
        reason = "Retained by the SDK capture facade, which is not compiled in the engine-only benchmark harness."
    )]
    pub(crate) replay_policy: SearchReplayPolicy,
    pub(crate) selected_for_parsing: bool,
    pub(crate) observed: SearchReplayResult,
}

impl fmt::Debug for SearchCapture {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("SearchCapture")
            .field("provider", &self.provider)
            .field("request_id", &self.request_id)
            .field("capture_id", &self.capture_id)
            .field("document", &self.document)
            .field("selected_for_parsing", &self.selected_for_parsing)
            .field("observed", &self.observed)
            .finish_non_exhaustive()
    }
}

/// Runs the same provider parser used by live Search on one immutable document.
pub fn parse_document(
    provider: Provider,
    document: &Document,
    policy: &Policy,
    provider_page_url: &str,
    result_limit: usize,
    output_limit: usize,
) -> SearchReplayResult {
    use SearchParserDiagnostic as D;
    let parsed = match provider {
        Provider::Brave => brave::parse(
            document,
            policy,
            provider_page_url,
            result_limit,
            output_limit,
        )
        .map_err(|error| match error {
            brave::BraveParseError::ZeroResultLimit | brave::BraveParseError::InvalidPlan => {
                D::InvalidConfiguration
            }
            brave::BraveParseError::OutputLimit => D::OutputLimit,
            brave::BraveParseError::InvalidPageUrl => D::InvalidPageUrl,
            brave::BraveParseError::UnsupportedDocumentClass => D::UnsupportedDocumentClass,
            brave::BraveParseError::UnrecognizedPage => D::UnrecognizedPage,
            brave::BraveParseError::NoUsableHits => D::NoUsableHits,
            brave::BraveParseError::IncompleteDocument => D::IncompleteDocument,
            brave::BraveParseError::LocateFailed => D::LocateFailed,
            brave::BraveParseError::InvalidLocatorResult => D::InvalidLocatorResult,
        }),
        Provider::Bing => bing::parse(
            document,
            policy,
            provider_page_url,
            result_limit,
            output_limit,
        )
        .map_err(|error| match error {
            bing::BingParseError::ZeroResultLimit | bing::BingParseError::InvalidPlan => {
                D::InvalidConfiguration
            }
            bing::BingParseError::OutputLimit => D::OutputLimit,
            bing::BingParseError::InvalidPageUrl => D::InvalidPageUrl,
            bing::BingParseError::UnrecognizedPage => D::UnrecognizedPage,
            bing::BingParseError::NoUsableHits => D::NoUsableHits,
            bing::BingParseError::IncompleteDocument => D::IncompleteDocument,
            bing::BingParseError::LocateFailed => D::LocateFailed,
            bing::BingParseError::InvalidLocatorResult => D::InvalidLocatorResult,
        }),
        Provider::DuckDuckGo => duckduckgo::parse(
            document,
            policy,
            provider_page_url,
            result_limit,
            output_limit,
        )
        .map_err(|error| match error {
            duckduckgo::DuckDuckGoParseError::ZeroResultLimit
            | duckduckgo::DuckDuckGoParseError::InvalidPlan
            | duckduckgo::DuckDuckGoParseError::InvalidQuery => D::InvalidConfiguration,
            duckduckgo::DuckDuckGoParseError::OutputLimit => D::OutputLimit,
            duckduckgo::DuckDuckGoParseError::InvalidPageUrl => D::InvalidPageUrl,
            duckduckgo::DuckDuckGoParseError::UnsupportedDocumentClass => {
                D::UnsupportedDocumentClass
            }
            duckduckgo::DuckDuckGoParseError::UnrecognizedPage => D::UnrecognizedPage,
            duckduckgo::DuckDuckGoParseError::NoUsableHits => D::NoUsableHits,
            duckduckgo::DuckDuckGoParseError::IncompleteDocument => D::IncompleteDocument,
            duckduckgo::DuckDuckGoParseError::LocateFailed => D::LocateFailed,
            duckduckgo::DuckDuckGoParseError::InvalidLocatorResult => D::InvalidLocatorResult,
        }),
    };
    match parsed {
        Ok(outcome) => SearchReplayResult {
            outcome,
            parser_diagnostic: None,
        },
        Err(diagnostic) => SearchReplayResult {
            outcome: ProviderOutcome::Failed(match diagnostic {
                D::OutputLimit => super::SearchFailure::BudgetExhausted,
                D::QueryMismatch => super::SearchFailure::QueryMismatch,
                _ => super::SearchFailure::MalformedResponse,
            }),
            parser_diagnostic: Some(diagnostic),
        },
    }
}

/// Interprets a recorded HTTP status without inspecting document content.
pub fn status_failure(status: Option<u16>) -> Option<super::SearchFailure> {
    match status? {
        429 => Some(super::SearchFailure::RateLimited),
        401 | 403 => Some(super::SearchFailure::Challenge),
        status if !(200..300).contains(&status) => Some(super::SearchFailure::ProviderUnavailable),
        _ => None,
    }
}
