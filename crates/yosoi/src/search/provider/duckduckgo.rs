//! DuckDuckGo regular-web result rows from a retained RenderedDom Document.
//!
//! The adapter uses the Search-owned Browser Requests profile. It keeps ad
//! rows in the shared locator regions so organic ranks and page placements
//! remain distinct. An unknown page with no recognized result rows is a parse
//! failure, never an invented empty result page.

use thiserror::Error;

mod common;
mod locations;
mod parse;
#[cfg(test)]
#[path = "duckduckgo_tests.rs"]
mod tests;

pub use parse::parse;

const PAGE_HOST: &str = "duckduckgo.com";
const PAGE_PATH: &str = "/";
const MAX_PROVIDER_PAGE_URL_BYTES: usize = 8_192;
const REGION_ID: &str = "duckduckgo_result_row";
const ROW_KIND_OUTPUT: &str = "row_kind";
const URL_OUTPUT: &str = "result_url";
const TITLE_OUTPUT: &str = "result_title";
const ROW_SECTION_OUTPUT: &str = "result_section";
const ROW_SELECTOR: &str = "article[data-testid=\"result\"], article[data-testid=\"ad\"]";
const TITLE_LINK_SELECTOR: &str = "a[data-testid=\"result-title-a\"]";
const ROW_SECTION_SELECTOR: &str = "article[data-testid=\"result\"] > div";
const EMPTY_MESSAGE_SELECTOR: &str = "section[data-testid=\"mainline\"] p";
const EMPTY_MESSAGE_MARKER: &str = "No results found for";
const CHALLENGE_SELECTOR: &str = "div.anomaly-modal__title";
const CHALLENGE_MARKER: &str = "Unfortunately, bots use DuckDuckGo too.";

/// Structural failure while interpreting a retained DuckDuckGo result page.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum DuckDuckGoParseError {
    #[error("result limit must be greater than zero")]
    ZeroResultLimit,
    #[error("normalized provider output exceeds the Search byte limit")]
    OutputLimit,
    #[error("provider page URL is invalid or is not the observed DuckDuckGo endpoint")]
    InvalidPageUrl,
    #[error("DuckDuckGo parsing requires a rendered-DOM document")]
    UnsupportedDocumentClass,
    #[error("provider locator query is invalid")]
    InvalidQuery,
    #[error("provider locator plan is invalid")]
    InvalidPlan,
    #[error("provider document has no recognized DuckDuckGo result rows")]
    UnrecognizedPage,
    #[error("provider document is incomplete for result parsing")]
    IncompleteDocument,
    #[error("provider document could not be located")]
    LocateFailed,
    #[error("provider locator findings do not match the result-row plan")]
    InvalidLocatorResult,
    #[error("provider document has no usable organic DuckDuckGo results")]
    NoUsableHits,
}
