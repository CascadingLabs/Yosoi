//! Bing Direct HTTP result-row parsing and observed `/ck/a` destination decoding.
//!
//! Every extracted field is attached to one repeated `li.b_algo` locator
//! region. The tracking decoder accepts only the retained host/path and the
//! single `u=a1...` URL-safe, unpadded Base64 form. Zero recognized rows are
//! unrecognized page content, never a guessed empty result set.
//! Live release certification still needs real empty/challenge fixtures or
//! separately observed classification evidence.

use thiserror::Error;

mod common;
mod destination;
mod parse;
mod recovery;
#[cfg(test)]
#[path = "bing_tests.rs"]
mod tests;

pub use destination::decode_destination;
pub use parse::parse;
pub use recovery::{recovered_page_matches_query, recovery_query};

const PAGE_HOST: &str = "www.bing.com";
const PAGE_PATH: &str = "/search";
const MAX_PROVIDER_PAGE_URL_BYTES: usize = 8_192;

/// Structural failure while interpreting a retained Bing result document.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum BingParseError {
    #[error("result limit must be greater than zero")]
    ZeroResultLimit,
    #[error("normalized provider output exceeds the Search byte limit")]
    OutputLimit,
    #[error("provider page URL is invalid or is not the observed Bing search endpoint")]
    InvalidPageUrl,
    #[error("provider locator plan is invalid")]
    InvalidPlan,
    #[error("provider document has no recognized Bing result rows")]
    UnrecognizedPage,
    #[error("provider result rows do not match a distinctive requested query term")]
    QueryMismatch,
    #[error("provider document has no usable Bing organic results")]
    NoUsableHits,
    #[error("provider document is incomplete for result parsing")]
    IncompleteDocument,
    #[error("provider document could not be located")]
    LocateFailed,
    #[error("provider locator findings do not match the result-row plan")]
    InvalidLocatorResult,
}

/// Rejection reason for one Bing tracking URL; values and opaque tokens are not retained.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum BingDestinationError {
    #[error("tracking URL is invalid")]
    InvalidWrapperUrl,
    #[error("tracking URL is not the observed HTTPS www.bing.com /ck/a wrapper")]
    UnsupportedWrapper,
    #[error("tracking URL must contain exactly one u parameter")]
    DestinationParameterCount,
    #[error("tracking URL exceeds the configured byte limit")]
    TrackingUrlTooLong,
    #[error("tracking destination is too long")]
    DestinationTooLong,
    #[error("tracking destination does not use the observed a1 prefix")]
    UnsupportedPrefix,
    #[error("tracking destination is not canonical unpadded URL-safe Base64")]
    InvalidBase64Url,
    #[error("tracking destination is not UTF-8")]
    InvalidUtf8,
    #[error("decoded tracking destination is not an absolute HTTP(S) URL")]
    InvalidDestination,
    #[error("decoded tracking destination contains user information")]
    DestinationHasCredentials,
}
