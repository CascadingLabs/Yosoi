//! Bing Direct HTTP result-row parsing and observed `/ck/a` destination decoding.
//!
//! Every extracted field is attached to one repeated `li.b_algo` locator
//! region. The tracking decoder accepts only the retained host/path and the
//! single `u=a1...` URL-safe, unpadded Base64 form. Zero recognized rows are
//! unrecognized page content, never a guessed empty result set.
//! Live release certification still needs real empty/challenge fixtures or
//! separately observed classification evidence.

use std::{collections::HashSet, num::NonZeroU16};

use crate::{
    Document, Policy, locator,
    search::{
        FeatureCoverage, ProviderOutcome, SearchCoverage, SearchHit, SearchHitMetadata,
        SearchIssue, SearchIssueKind, SearchPage, SearchResultUrl, WebCoverage,
    },
};
use thiserror::Error;
use url::Url;

use super::row_contract::{RowContractError, validated_rows};

const PAGE_HOST: &str = "www.bing.com";
const PAGE_PATH: &str = "/search";
const WRAPPER_PATH: &str = "/ck/a";
const URL_OUTPUT: &str = "result_url";
const ROW_SELECTOR: &str = "li.b_algo";
const TITLE_LINK_SELECTOR: &str = "h2 > a[href]";
const SNIPPET_SELECTOR: &str = ".b_caption > p.b_lineclamp2";
const TRACKING_PREFIX: &str = "a1";
const MAX_PROVIDER_PAGE_URL_BYTES: usize = 8_192;
const MAX_TRACKING_VALUE_BYTES: usize = 4_098;
const MAX_ENCODED_DESTINATION_BYTES: usize = 4_096;
const MAX_DECODED_DESTINATION_BYTES: usize = 3_072;

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

#[derive(crate::Contract)]
#[ys(id = "bing_result", description = "One Bing organic result", root = locator::css(ROW_SELECTOR))]
struct BingRow {
    #[ys(id = "result_url", description = "The result destination", locator = locator::css(TITLE_LINK_SELECTOR).attribute("href"))]
    href: String,
    #[ys(id = "result_title", description = "The result title", locator = locator::css(TITLE_LINK_SELECTOR).text())]
    title: Option<String>,
    #[ys(id = "result_snippet", description = "The result summary", locator = locator::css(SNIPPET_SELECTOR).text())]
    snippet: Option<String>,
}

/// Extracts Bing result rows from an already retained Yosoi HTML Document.
///
/// Requests status and transport outcomes are handled by the adapter executor.
/// Empty and challenge page markers are not inferred from a zero-row document;
/// neither was present in the retained Bing fixture evidence.
pub fn parse(
    document: &Document,
    policy: &Policy,
    provider_page_url: &str,
    result_limit: usize,
    max_output_bytes: usize,
) -> Result<ProviderOutcome, BingParseError> {
    if result_limit == 0 {
        return Err(BingParseError::ZeroResultLimit);
    }
    if max_output_bytes == 0 {
        return Err(BingParseError::OutputLimit);
    }
    let page_url = parse_page_url(provider_page_url)?;
    let plan = BingRow::plan().map_err(|_| BingParseError::InvalidPlan)?;
    let located = document.bind(policy).locate(plan);
    let rows = validated_rows(BingRow::extract(&located).validate(), URL_OUTPUT)
        .map_err(map_row_contract_error)?;

    let mut hits = Vec::with_capacity(rows.len().min(result_limit));
    let mut issues = Vec::with_capacity(rows.len().min(result_limit));
    let mut seen_destinations = HashSet::<String>::new();
    let mut partial = false;
    let mut dropped_issues = false;
    let mut output_limited = false;
    let mut output_limit_index = None;
    let mut retained_string_bytes = 0_usize;

    for (ordinal, row) in rows {
        let Some(placement_index) = nonzero_index(ordinal) else {
            partial = true;
            output_limited = true;
            break;
        };
        // Reaching the requested hit count is normal completion for this Policy.
        // It does not mean the retained result is partial or byte limited.
        if hits.len() >= result_limit {
            break;
        }
        let row = match row {
            Ok(row) => row,
            Err(kind) => {
                partial = true;
                record_issue(
                    &mut issues,
                    SearchIssue {
                        placement_index: Some(placement_index),
                        kind,
                    },
                    result_limit,
                    &mut dropped_issues,
                );
                continue;
            }
        };
        let href = row.href.trim();
        if href.is_empty() {
            partial = true;
            record_issue(
                &mut issues,
                SearchIssue {
                    placement_index: Some(placement_index),
                    kind: SearchIssueKind::MissingRequiredField,
                },
                result_limit,
                &mut dropped_issues,
            );
            continue;
        }
        let Ok(url) = decode_destination(href) else {
            partial = true;
            record_issue(
                &mut issues,
                SearchIssue {
                    placement_index: Some(placement_index),
                    kind: SearchIssueKind::InvalidDestination,
                },
                result_limit,
                &mut dropped_issues,
            );
            continue;
        };
        if !seen_destinations.insert(url.as_str().to_owned()) {
            partial = true;
            record_issue(
                &mut issues,
                SearchIssue {
                    placement_index: Some(placement_index),
                    kind: SearchIssueKind::DuplicateDestination,
                },
                result_limit,
                &mut dropped_issues,
            );
            continue;
        }
        let Some(rank) = nonzero_index(ordinal) else {
            partial = true;
            output_limited = true;
            break;
        };
        let title = row.title.as_deref().and_then(nonempty_text);
        let snippet = row.snippet.as_deref().and_then(nonempty_text);
        let row_bytes = url
            .as_str()
            .len()
            .checked_add(title.map_or(0, str::len))
            .and_then(|bytes| bytes.checked_add(snippet.map_or(0, str::len)))
            .ok_or(BingParseError::OutputLimit)?;
        let Some(next_bytes) = retained_string_bytes.checked_add(row_bytes) else {
            return Err(BingParseError::OutputLimit);
        };
        if next_bytes > max_output_bytes {
            if hits.is_empty() {
                return Err(BingParseError::OutputLimit);
            }
            partial = true;
            output_limited = true;
            output_limit_index = Some(placement_index);
            break;
        }
        retained_string_bytes = next_bytes;
        let metadata = SearchHitMetadata {
            title: title.map(str::to_owned),
            snippet: snippet.map(str::to_owned),
            ..SearchHitMetadata::default()
        };
        hits.push(SearchHit::new(url, rank, placement_index).with_metadata(metadata));
    }

    if output_limited || dropped_issues {
        partial = true;
        let issue = SearchIssue {
            placement_index: output_limit_index,
            kind: SearchIssueKind::OutputLimit,
        };
        if issues.len() >= result_limit {
            issues.truncate(result_limit.saturating_sub(1));
        }
        issues.push(issue);
    }

    if hits.is_empty() {
        return Err(BingParseError::NoUsableHits);
    }
    if !hits_match_query(&hits, &page_url) {
        return Err(BingParseError::QueryMismatch);
    }
    let coverage = SearchCoverage::new(
        if partial {
            WebCoverage::Partial
        } else {
            WebCoverage::Complete
        },
        FeatureCoverage::NotCollected,
    );
    Ok(ProviderOutcome::Results(SearchPage::new(
        hits,
        Vec::new(),
        coverage,
        issues,
    )))
}

/// Detects the observed Bing degradation where a full query is echoed but
/// organic rows are about a different, single term. A short result sample,
/// one-word query, operator query, or non-ASCII query remains unclassified.
fn hits_match_query(hits: &[SearchHit], page_url: &Url) -> bool {
    if hits.len() < 3 {
        return true;
    }
    let Some(query) = page_url
        .query_pairs()
        .find(|(name, _)| name == "q")
        .map(|(_, value)| value)
    else {
        return true;
    };
    let Some(anchor) = query_anchor(&query) else {
        return true;
    };
    let singular = anchor.strip_suffix('s').filter(|value| value.len() >= 5);
    hits_contain_anchor(hits, &anchor, singular)
}

fn hits_contain_anchor(hits: &[SearchHit], anchor: &str, singular: Option<&str>) -> bool {
    hits.iter().take(5).any(|hit| {
        [hit.title(), hit.snippet(), Some(hit.url().as_str())]
            .into_iter()
            .flatten()
            .any(|value| {
                let normalized = value.to_ascii_lowercase();
                normalized.contains(anchor)
                    || singular.is_some_and(|word| normalized.contains(word))
            })
    })
}

/// A recovered page must still mention a distinctive term from the caller's
/// original query; a one-word recovery query cannot skip this check.
pub fn recovered_page_matches_query(page: &SearchPage, original_query: &str) -> bool {
    let Some(anchor) = query_anchor(original_query) else {
        return false;
    };
    let singular = anchor.strip_suffix('s').filter(|value| value.len() >= 5);
    hits_contain_anchor(page.hits(), &anchor, singular)
}

/// Produces one shorter Bing query after a detected off-query response. This
/// preserves distinctive ASCII words and refuses operators and quoted terms.
pub fn recovery_query(query: &str) -> Option<String> {
    let words = query.split_ascii_whitespace().collect::<Vec<_>>();
    if words.len() < 2
        || words
            .iter()
            .any(|word| !word.bytes().all(|byte| byte.is_ascii_alphabetic()))
    {
        return None;
    }
    let content = words
        .iter()
        .copied()
        .filter(|word| {
            !matches!(
                word.to_ascii_lowercase().as_str(),
                "a" | "an"
                    | "the"
                    | "of"
                    | "for"
                    | "in"
                    | "on"
                    | "at"
                    | "to"
                    | "is"
                    | "are"
                    | "was"
                    | "were"
                    | "what"
                    | "how"
                    | "who"
                    | "when"
                    | "where"
                    | "why"
                    | "does"
                    | "do"
                    | "can"
                    | "make"
                    | "history"
                    | "scientific"
                    | "name"
            )
        })
        .collect::<Vec<_>>();
    if content.is_empty() || content.len() == words.len() {
        return None;
    }
    Some(content.join(" "))
}

fn query_anchor(query: &str) -> Option<String> {
    if !query.is_ascii() || query.contains([':', '"']) {
        return None;
    }
    let words = query
        .split(|character: char| !character.is_ascii_alphanumeric())
        .filter(|word| !word.is_empty())
        .collect::<Vec<_>>();
    if words.len() < 2 {
        return None;
    }
    words
        .iter()
        .rev()
        .take(2)
        .filter(|word| word.len() >= 6)
        .max_by_key(|word| word.len())
        .map(|word| word.to_ascii_lowercase())
}

/// Decodes only the `www.bing.com/ck/a?u=a1...` shape observed in the saved pages.
pub fn decode_destination(value: &str) -> Result<SearchResultUrl, BingDestinationError> {
    if value.len() > MAX_PROVIDER_PAGE_URL_BYTES {
        return Err(BingDestinationError::TrackingUrlTooLong);
    }
    let url = Url::parse(value).map_err(|_| BingDestinationError::InvalidWrapperUrl)?;
    if url.scheme() != "https"
        || url.host_str() != Some(PAGE_HOST)
        || url.path() != WRAPPER_PATH
        || url.port().is_some()
        || has_user_information(&url)
        || url.fragment().is_some()
    {
        return Err(BingDestinationError::UnsupportedWrapper);
    }

    let mut destination_value = None;
    for (name, parameter_value) in url.query_pairs() {
        if name == "u" {
            if destination_value.is_some() {
                return Err(BingDestinationError::DestinationParameterCount);
            }
            destination_value = Some(parameter_value.into_owned());
        }
    }
    let destination_value =
        destination_value.ok_or(BingDestinationError::DestinationParameterCount)?;
    if destination_value.len() > MAX_TRACKING_VALUE_BYTES {
        return Err(BingDestinationError::DestinationTooLong);
    }
    let encoded = destination_value
        .strip_prefix(TRACKING_PREFIX)
        .ok_or(BingDestinationError::UnsupportedPrefix)?;
    if encoded.is_empty() {
        return Err(BingDestinationError::InvalidBase64Url);
    }
    if encoded.len() > MAX_ENCODED_DESTINATION_BYTES {
        return Err(BingDestinationError::DestinationTooLong);
    }
    let decoded = decode_unpadded_url_safe_base64(encoded)?;
    if decoded.len() > MAX_DECODED_DESTINATION_BYTES {
        return Err(BingDestinationError::DestinationTooLong);
    }
    let destination_text =
        String::from_utf8(decoded).map_err(|_| BingDestinationError::InvalidUtf8)?;
    if destination_text.trim() != destination_text
        || destination_text
            .bytes()
            .any(|byte| byte.is_ascii_whitespace() || byte.is_ascii_control())
    {
        return Err(BingDestinationError::InvalidDestination);
    }
    let destination =
        Url::parse(&destination_text).map_err(|_| BingDestinationError::InvalidDestination)?;
    if !matches!(destination.scheme(), "http" | "https") || destination.host_str().is_none() {
        return Err(BingDestinationError::InvalidDestination);
    }
    if has_user_information(&destination) {
        return Err(BingDestinationError::DestinationHasCredentials);
    }
    SearchResultUrl::parse(destination.as_str())
        .map_err(|_| BingDestinationError::InvalidDestination)
}

fn has_user_information(url: &Url) -> bool {
    if !url.username().is_empty() || url.password().is_some() {
        return true;
    }
    let Some((_, remainder)) = url.as_str().split_once("://") else {
        return true;
    };
    remainder
        .split(['/', '?', '#'])
        .next()
        .is_none_or(|authority| authority.contains('@'))
}

fn decode_unpadded_url_safe_base64(value: &str) -> Result<Vec<u8>, BingDestinationError> {
    let bytes = value.as_bytes();
    if bytes.is_empty() || bytes.len() > MAX_ENCODED_DESTINATION_BYTES || bytes.len() % 4 == 1 {
        return Err(BingDestinationError::InvalidBase64Url);
    }
    let output_capacity = bytes
        .len()
        .checked_mul(3)
        .map(|length| length / 4)
        .ok_or(BingDestinationError::DestinationTooLong)?;
    if output_capacity > MAX_DECODED_DESTINATION_BYTES {
        return Err(BingDestinationError::DestinationTooLong);
    }
    let mut output = Vec::with_capacity(output_capacity);
    let (groups, remainder) = bytes.as_chunks::<4>();
    for group in groups {
        let [first, second, third, fourth] = *group;
        let first = base64url_value(first).ok_or(BingDestinationError::InvalidBase64Url)?;
        let second = base64url_value(second).ok_or(BingDestinationError::InvalidBase64Url)?;
        let third = base64url_value(third).ok_or(BingDestinationError::InvalidBase64Url)?;
        let fourth = base64url_value(fourth).ok_or(BingDestinationError::InvalidBase64Url)?;
        let block = (u32::from(first) << 18)
            | (u32::from(second) << 12)
            | (u32::from(third) << 6)
            | u32::from(fourth);
        output.push(
            u8::try_from((block >> 16) & 0xff)
                .map_err(|_| BingDestinationError::InvalidBase64Url)?,
        );
        output.push(
            u8::try_from((block >> 8) & 0xff)
                .map_err(|_| BingDestinationError::InvalidBase64Url)?,
        );
        output
            .push(u8::try_from(block & 0xff).map_err(|_| BingDestinationError::InvalidBase64Url)?);
    }
    match remainder {
        [] => {}
        [first, second] => {
            let first = base64url_value(*first).ok_or(BingDestinationError::InvalidBase64Url)?;
            let second = base64url_value(*second).ok_or(BingDestinationError::InvalidBase64Url)?;
            if second & 0x0f != 0 {
                return Err(BingDestinationError::InvalidBase64Url);
            }
            let block = (u16::from(first) << 6) | u16::from(second);
            output.push(
                u8::try_from(block >> 4).map_err(|_| BingDestinationError::InvalidBase64Url)?,
            );
        }
        [first, second, third] => {
            let first = base64url_value(*first).ok_or(BingDestinationError::InvalidBase64Url)?;
            let second = base64url_value(*second).ok_or(BingDestinationError::InvalidBase64Url)?;
            let third = base64url_value(*third).ok_or(BingDestinationError::InvalidBase64Url)?;
            if third & 0x03 != 0 {
                return Err(BingDestinationError::InvalidBase64Url);
            }
            let block = (u32::from(first) << 12) | (u32::from(second) << 6) | u32::from(third);
            output.push(
                u8::try_from((block >> 10) & 0xff)
                    .map_err(|_| BingDestinationError::InvalidBase64Url)?,
            );
            output.push(
                u8::try_from((block >> 2) & 0xff)
                    .map_err(|_| BingDestinationError::InvalidBase64Url)?,
            );
        }
        _ => return Err(BingDestinationError::InvalidBase64Url),
    }
    Ok(output)
}

const fn base64url_value(byte: u8) -> Option<u8> {
    match byte {
        b'A'..=b'Z' => byte.checked_sub(b'A'),
        b'a'..=b'z' => match byte.checked_sub(b'a') {
            Some(value) => value.checked_add(26),
            None => None,
        },
        b'0'..=b'9' => match byte.checked_sub(b'0') {
            Some(value) => value.checked_add(52),
            None => None,
        },
        b'-' => Some(62),
        b'_' => Some(63),
        _ => None,
    }
}

fn parse_page_url(value: &str) -> Result<Url, BingParseError> {
    if value.len() > MAX_PROVIDER_PAGE_URL_BYTES {
        return Err(BingParseError::InvalidPageUrl);
    }
    let Ok(url) = Url::parse(value) else {
        return Err(BingParseError::InvalidPageUrl);
    };
    if url.scheme() != "https"
        || url.host_str() != Some(PAGE_HOST)
        || url.path() != PAGE_PATH
        || has_user_information(&url)
    {
        return Err(BingParseError::InvalidPageUrl);
    }
    Ok(url)
}

const fn map_row_contract_error(error: RowContractError) -> BingParseError {
    match error {
        RowContractError::UnrecognizedPage => BingParseError::UnrecognizedPage,
        RowContractError::IncompleteDocument => BingParseError::IncompleteDocument,
        RowContractError::LocateFailed => BingParseError::LocateFailed,
        RowContractError::InvalidLocatorResult => BingParseError::InvalidLocatorResult,
    }
}

fn nonzero_index(ordinal: u64) -> Option<NonZeroU16> {
    let value = u16::try_from(ordinal).ok()?;
    NonZeroU16::new(value)
}

fn nonempty_text(value: &str) -> Option<&str> {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed)
    }
}

fn record_issue(
    issues: &mut Vec<SearchIssue>,
    issue: SearchIssue,
    limit: usize,
    dropped: &mut bool,
) {
    if issues.len() < limit {
        issues.push(issue);
    } else {
        *dropped = true;
    }
}

#[cfg(test)]
mod tests {
    use std::{error::Error, io, num::NonZeroU16, path::PathBuf};

    use serde_json::Value;
    use sha2::{Digest, Sha256};

    use super::{
        BingDestinationError, BingParseError, decode_destination, parse, query_anchor,
        recovered_page_matches_query, recovery_query,
    };
    use crate::{
        Document, Policy,
        search::{
            FeatureCoverage, ProviderOutcome, SearchCoverage, SearchHit, SearchHitMetadata,
            SearchIssueKind, SearchPage, SearchResultUrl, WebCoverage,
        },
    };

    const ROW: &str =
        include_str!("../../../tests/fixtures/search-providers/fixtures/bing-organic-row.html");
    const MULTIROW: &str =
        include_str!("../../../tests/fixtures/search-providers/fixtures/bing-multirow.html");
    const SNIPPETLESS_ROWS: &str = include_str!(
        "../../../tests/fixtures/search-providers/fixtures/bing-safari26-snippetless-rows.html"
    );
    const SPONSORED_CONTROL: &str = include_str!(
        "../../../tests/fixtures/search-providers/fixtures/bing-synthetic-sponsored-control.html"
    );
    const MISSING_HREF_CONTROL: &str = include_str!(
        "../../../tests/fixtures/search-providers/fixtures/bing-synthetic-missing-href.html"
    );
    const OBSERVATIONS: &str =
        include_str!("../../../tests/fixtures/search-providers/observations.json");
    const DECODER_VECTORS: &str =
        include_str!("../../../tests/fixtures/search-providers/bing-ck-a-negative-vectors.json");

    fn vectors() -> Result<Vec<Value>, Box<dyn Error>> {
        let value: Value = serde_json::from_str(DECODER_VECTORS)?;
        value
            .get("vectors")
            .and_then(Value::as_array)
            .cloned()
            .ok_or_else(|| io::Error::other("decoder vector list is missing").into())
    }

    fn positive_vectors() -> Result<Vec<(String, String)>, Box<dyn Error>> {
        vectors()?
            .into_iter()
            .filter(|value| value.get("kind").and_then(Value::as_str) == Some("positive"))
            .map(|value| {
                let encoded = value
                    .get("u")
                    .and_then(Value::as_str)
                    .ok_or_else(|| io::Error::other("synthetic positive u value is missing"))?;
                let target = value
                    .get("expected")
                    .and_then(Value::as_str)
                    .and_then(|value| value.strip_prefix("accept: "))
                    .ok_or_else(|| io::Error::other("synthetic positive target is missing"))?;
                Ok((encoded.to_owned(), target.to_owned()))
            })
            .collect()
    }

    fn replace_two_redacted_wrappers(
        markup: &str,
        first_u: &str,
        second_u: &str,
    ) -> Result<String, Box<dyn Error>> {
        let mut parts = markup.split("u=REDACTED");
        let first = parts
            .next()
            .ok_or_else(|| io::Error::other("first redacted wrapper is missing"))?;
        let middle = parts
            .next()
            .ok_or_else(|| io::Error::other("second redacted wrapper is missing"))?;
        let last = parts
            .next()
            .ok_or_else(|| io::Error::other("row fixture has too few wrappers"))?;
        if parts.next().is_some() {
            return Err(io::Error::other("row fixture has more than two wrappers").into());
        }
        Ok(format!("{first}u={first_u}{middle}u={second_u}{last}"))
    }

    fn retained_capture_record(name: &str) -> Result<(String, String, usize, u16), Box<dyn Error>> {
        let observations: Value = serde_json::from_str(OBSERVATIONS)?;
        let record = observations
            .get("provenance")
            .and_then(|value| value.get("captures"))
            .and_then(|value| value.get(name))
            .ok_or_else(|| io::Error::other("capture provenance entry is missing"))?;
        let artifact = record
            .get("artifact")
            .and_then(Value::as_str)
            .ok_or_else(|| io::Error::other("capture artifact name is missing"))?;
        let hash = record
            .get("sha256")
            .and_then(Value::as_str)
            .ok_or_else(|| io::Error::other("capture hash is missing"))?;
        let bytes = record
            .get("bytes")
            .and_then(Value::as_u64)
            .and_then(|value| usize::try_from(value).ok())
            .ok_or_else(|| io::Error::other("capture byte count is missing"))?;
        let status = record
            .get("status")
            .and_then(Value::as_u64)
            .and_then(|value| u16::try_from(value).ok())
            .ok_or_else(|| io::Error::other("capture status is missing"))?;
        Ok((artifact.to_owned(), hash.to_owned(), bytes, status))
    }

    fn load_retained_capture(name: &str) -> Result<(Vec<u8>, u16), Box<dyn Error>> {
        let (artifact, expected_hash, expected_bytes, status) = retained_capture_record(name)?;
        let directory = std::env::var_os("YS_SEARCH_CAPTURE_DIR")
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("/tmp"));
        let bytes = std::fs::read(directory.join(&artifact))?;
        let observed_hash = format!("{:x}", Sha256::digest(&bytes));
        if bytes.len() != expected_bytes || observed_hash != expected_hash {
            return Err(
                io::Error::other("retained capture does not match manifest provenance").into(),
            );
        }
        Ok((bytes, status))
    }

    #[test]
    fn synthetic_positive_vector_decodes_and_populates_one_row() -> Result<(), Box<dyn Error>> {
        let values = vectors()?;
        let positive = values
            .iter()
            .find(|value| value.get("kind").and_then(Value::as_str) == Some("positive"))
            .ok_or_else(|| io::Error::other("synthetic positive vector is missing"))?;
        let encoded = positive
            .get("u")
            .and_then(Value::as_str)
            .ok_or_else(|| io::Error::other("synthetic positive u value is missing"))?;
        let expected = positive
            .get("expected")
            .and_then(Value::as_str)
            .and_then(|value| value.strip_prefix("accept: "))
            .ok_or_else(|| io::Error::other("synthetic positive target is missing"))?;
        let wrapper = format!("https://www.bing.com/ck/a?u={encoded}");
        assert_eq!(decode_destination(&wrapper)?.as_str(), expected);

        let markup = ROW.replace("u=REDACTED", &format!("u={encoded}"));
        let document = Document::html("bing-fixture.html", markup.into_bytes())?;
        let outcome = parse(
            &document,
            &Policy::default(),
            "https://www.bing.com/search?q=fixture",
            10,
            16 * 1024 * 1024,
        )?;
        let ProviderOutcome::Results(page) = outcome else {
            return Err(io::Error::other("expected a parsed Bing result page").into());
        };
        let hit = page
            .hits()
            .first()
            .ok_or_else(|| io::Error::other("sanitized Bing row produced no hit"))?;
        assert_eq!(hit.url().as_str(), expected);
        assert_eq!(hit.title(), Some("[redacted captured title]"));
        assert_eq!(hit.snippet(), Some("[redacted captured snippet]"));
        assert_eq!(hit.organic_rank().get(), 1);
        assert_eq!(hit.placement_index().get(), 1);
        assert!(page.issues().is_empty());
        Ok(())
    }

    #[test]
    fn synthetic_negative_vectors_are_rejected() -> Result<(), Box<dyn Error>> {
        for vector in vectors()?
            .iter()
            .filter(|value| value.get("kind").and_then(Value::as_str) == Some("negative"))
        {
            let name = vector
                .get("name")
                .and_then(Value::as_str)
                .ok_or_else(|| io::Error::other("negative vector name is missing"))?;
            let encoded = vector
                .get("u")
                .and_then(Value::as_str)
                .ok_or_else(|| io::Error::other("negative vector u value is missing"))?;
            let wrapper = format!("https://www.bing.com/ck/a?u={encoded}");
            assert!(
                decode_destination(&wrapper).is_err(),
                "vector {name} was accepted"
            );
        }
        Ok(())
    }

    #[test]
    fn decoder_rejects_unknown_wrapper_shapes_and_destination_credentials()
    -> Result<(), Box<dyn Error>> {
        let positive = vectors()?
            .into_iter()
            .find(|value| value.get("kind").and_then(Value::as_str) == Some("positive"))
            .ok_or_else(|| io::Error::other("synthetic positive vector is missing"))?;
        let encoded = positive
            .get("u")
            .and_then(Value::as_str)
            .ok_or_else(|| io::Error::other("synthetic positive u value is missing"))?;
        let bad_wrappers = [
            format!("https://bing.com/ck/a?u={encoded}"),
            format!("https://www.bing.com/other?u={encoded}"),
            format!("http://www.bing.com/ck/a?u={encoded}"),
            format!("https://www.bing.com/ck/a?u={encoded}&u={encoded}"),
            format!("https://www.bing.com/ck/a?u={encoded}#fragment"),
        ];
        for wrapper in bad_wrappers {
            assert!(decode_destination(&wrapper).is_err());
        }
        let credentials =
            "https://www.bing.com/ck/a?u=a1aHR0cHM6Ly91c2VyOnBhc3NAZXhhbXBsZS5vcmcvcGF0aA";
        assert_eq!(
            decode_destination(credentials),
            Err(BingDestinationError::DestinationHasCredentials)
        );
        Ok(())
    }

    #[test]
    fn query_anchor_favors_distinctive_tail_terms() {
        assert_eq!(
            query_anchor("history of cotton candy").as_deref(),
            Some("cotton")
        );
        assert_eq!(
            query_anchor("how to make sourdough bread").as_deref(),
            Some("sourdough")
        );
        assert_eq!(query_anchor("what is a quokka").as_deref(), Some("quokka"));
        assert_eq!(query_anchor("rust").as_deref(), None);
        assert_eq!(
            query_anchor("site:example.org cotton candy").as_deref(),
            None
        );
    }

    #[test]
    fn off_query_organic_rows_are_rejected_without_discarding_relevant_rows()
    -> Result<(), Box<dyn Error>> {
        fn row(encoded: &str, title: &str) -> String {
            format!(
                r#"<li class="b_algo"><h2><a href="https://www.bing.com/ck/a?u={encoded}">{title}</a></h2><div class="b_caption"><p class="b_lineclamp2">Automation platform</p></div></li>"#
            )
        }
        let first = row("a1aHR0cHM6Ly9leGFtcGxlLm9yZy9tYWtlLTE", "Make automation");
        let second = row("a1aHR0cHM6Ly9leGFtcGxlLm9yZy9tYWtlLTI", "Make workflows");
        let third = row("a1aHR0cHM6Ly9leGFtcGxlLm9yZy9tYWtlLTM", "Make software");
        let page_url = "https://www.bing.com/search?q=how+to+make+sourdough+bread";
        let unrelated = Document::html(
            "bing-off-query.html",
            format!("{first}{second}{third}").into_bytes(),
        )?;
        assert!(matches!(
            parse(
                &unrelated,
                &Policy::default(),
                page_url,
                5,
                16 * 1024 * 1024
            ),
            Err(BingParseError::QueryMismatch)
        ));

        let relevant = Document::html(
            "bing-relevant.html",
            format!(
                "{first}{second}{}",
                row(
                    "a1aHR0cHM6Ly9leGFtcGxlLm9yZy9zb3VyZG91Z2gtMQ",
                    "Sourdough bread recipe"
                )
            )
            .into_bytes(),
        )?;
        assert!(matches!(
            parse(&relevant, &Policy::default(), page_url, 5, 16 * 1024 * 1024),
            Ok(ProviderOutcome::Results(_))
        ));
        Ok(())
    }

    #[test]
    fn recovery_query_preserves_distinctive_terms_and_refuses_operators() {
        assert_eq!(
            recovery_query("how to make sourdough bread"),
            Some("sourdough bread".to_owned())
        );
        assert_eq!(
            recovery_query("history of paper airplanes"),
            Some("paper airplanes".to_owned())
        );
        assert_eq!(
            recovery_query("scientific name for sunflower"),
            Some("sunflower".to_owned())
        );
        assert_eq!(
            recovery_query("what is a quokka"),
            Some("quokka".to_owned())
        );
        assert_eq!(recovery_query("site:example.com sourdough bread"), None);
        assert_eq!(recovery_query("\"history of paper airplanes\""), None);
    }

    #[test]
    fn recovered_single_word_page_must_match_the_original_query() -> Result<(), Box<dyn Error>> {
        let rank = NonZeroU16::MIN;
        let page_for = |url: &str, title: &str| -> Result<SearchPage, Box<dyn Error>> {
            let hit = SearchHit::new(SearchResultUrl::parse(url)?, rank, rank).with_metadata(
                SearchHitMetadata {
                    title: Some(title.to_owned()),
                    ..SearchHitMetadata::default()
                },
            );
            Ok(SearchPage::new(
                vec![hit],
                Vec::new(),
                SearchCoverage::new(WebCoverage::Complete, FeatureCoverage::NotCollected),
                Vec::new(),
            ))
        };
        let relevant = page_for("https://example.org/quokka", "Quokka facts")?;
        let unrelated = page_for("https://make.com/", "Make automation")?;
        assert!(recovered_page_matches_query(&relevant, "what is a quokka"));
        assert!(!recovered_page_matches_query(
            &unrelated,
            "what is a quokka"
        ));
        Ok(())
    }

    #[test]
    #[ignore = "requires the retained local HTTP-200 off-query Bing page; no network I/O"]
    fn replay_retained_off_query_page() -> Result<(), Box<dyn Error>> {
        let path = std::env::var_os("YS_BING_OFF_QUERY_CAPTURE_PATH")
            .map(PathBuf::from)
            .ok_or_else(|| io::Error::other("YS_BING_OFF_QUERY_CAPTURE_PATH is required"))?;
        let bytes = std::fs::read(path)?;
        assert_eq!(
            format!("{:x}", Sha256::digest(&bytes)),
            "8a9b6cdf7c7e1961d9649100582542b508ac106bd7353bed0ef7c4cce96a6154"
        );
        let document = Document::html("bing-retained-off-query.html", bytes)?;
        assert!(matches!(
            parse(
                &document,
                &Policy::default(),
                "https://www.bing.com/search?q=how+to+make+sourdough+bread",
                5,
                16 * 1024 * 1024,
            ),
            Err(BingParseError::QueryMismatch)
        ));
        Ok(())
    }

    #[test]
    fn zero_rows_are_unrecognized_not_empty() -> Result<(), Box<dyn Error>> {
        let document = Document::html(
            "bing-empty-fixture.html",
            b"<html><body></body></html>".to_vec(),
        )?;
        assert!(matches!(
            parse(
                &document,
                &Policy::default(),
                "https://www.bing.com/search?q=fixture",
                10,
                16 * 1024 * 1024,
            ),
            Err(BingParseError::UnrecognizedPage)
        ));
        Ok(())
    }

    #[test]
    fn redacted_non_replayable_wrapper_is_not_a_result() -> Result<(), Box<dyn Error>> {
        let document = Document::html("bing-redacted-row.html", ROW.as_bytes().to_vec())?;
        assert!(matches!(
            parse(
                &document,
                &Policy::default(),
                "https://www.bing.com/search?q=fixture",
                10,
                16 * 1024 * 1024,
            ),
            Err(BingParseError::NoUsableHits)
        ));
        Ok(())
    }

    #[test]
    fn first_hit_cannot_exceed_normalized_byte_budget() -> Result<(), Box<dyn Error>> {
        let values = vectors()?;
        let positive = values
            .iter()
            .find(|value| value.get("kind").and_then(Value::as_str) == Some("positive"))
            .ok_or_else(|| io::Error::other("synthetic positive vector is missing"))?;
        let encoded = positive
            .get("u")
            .and_then(Value::as_str)
            .ok_or_else(|| io::Error::other("synthetic positive u value is missing"))?;
        let markup = ROW.replace("u=REDACTED", &format!("u={encoded}"));
        let document = Document::html("bing-byte-limit.html", markup.into_bytes())?;
        assert!(matches!(
            parse(
                &document,
                &Policy::default(),
                "https://www.bing.com/search?q=fixture",
                10,
                1,
            ),
            Err(BingParseError::OutputLimit)
        ));
        Ok(())
    }

    #[test]
    fn rejected_duplicate_keeps_later_rank_and_row_fields() -> Result<(), Box<dyn Error>> {
        let values = vectors()?;
        let positive = values
            .iter()
            .find(|value| value.get("kind").and_then(Value::as_str) == Some("positive"))
            .ok_or_else(|| io::Error::other("synthetic positive vector is missing"))?;
        let encoded = positive
            .get("u")
            .and_then(Value::as_str)
            .ok_or_else(|| io::Error::other("synthetic positive u value is missing"))?;
        let first = ROW.replace("u=REDACTED", &format!("u={encoded}"));
        let duplicate = first.replace("[redacted captured title]", "synthetic duplicate title");
        // Synthetic URL-safe Base64 for https://example.org/other.
        let third = ROW
            .replace("u=REDACTED", "u=a1aHR0cHM6Ly9leGFtcGxlLm9yZy9vdGhlcg")
            .replace("[redacted captured title]", "synthetic third title")
            .replace("[redacted captured snippet]", "synthetic third snippet");
        let document = Document::html(
            "bing-three-rows.html",
            format!("{first}{duplicate}{third}").into_bytes(),
        )?;
        let outcome = parse(
            &document,
            &Policy::default(),
            "https://www.bing.com/search?q=fixture",
            10,
            16 * 1024 * 1024,
        )?;
        let ProviderOutcome::Results(page) = outcome else {
            return Err(io::Error::other("expected Bing results").into());
        };
        assert_eq!(page.hits().len(), 2);
        let last = page
            .hits()
            .get(1)
            .ok_or_else(|| io::Error::other("missing third-ranked result"))?;
        assert_eq!(last.url().as_str(), "https://example.org/other");
        assert_eq!(last.title(), Some("synthetic third title"));
        assert_eq!(last.snippet(), Some("synthetic third snippet"));
        assert_eq!(last.organic_rank().get(), 3);
        assert!(page.issues().iter().any(|issue| {
            issue.placement_index.is_some_and(|index| index.get() == 2)
                && issue.kind == SearchIssueKind::DuplicateDestination
        }));
        assert_eq!(page.coverage().web(), WebCoverage::Partial);
        Ok(())
    }

    #[test]
    fn captured_multirow_fixture_keeps_fields_with_their_source_row() -> Result<(), Box<dyn Error>>
    {
        let targets = positive_vectors()?;
        let first = targets
            .first()
            .ok_or_else(|| io::Error::other("first synthetic URL target is missing"))?;
        let second = targets
            .get(1)
            .ok_or_else(|| io::Error::other("second synthetic URL target is missing"))?;
        let markup = replace_two_redacted_wrappers(&MULTIROW, &first.0, &second.0)?;
        let document = Document::html("bing-multirow.html", markup.into_bytes())?;
        let outcome = parse(
            &document,
            &Policy::default(),
            "https://www.bing.com/search?q=fixture",
            10,
            16 * 1024 * 1024,
        )?;
        let ProviderOutcome::Results(page) = outcome else {
            return Err(io::Error::other("expected captured Bing rows").into());
        };
        assert_eq!(page.hits().len(), 2);
        let first_hit = page
            .hits()
            .first()
            .ok_or_else(|| io::Error::other("missing first captured Bing row"))?;
        let second_hit = page
            .hits()
            .get(1)
            .ok_or_else(|| io::Error::other("missing second captured Bing row"))?;
        assert_eq!(first_hit.url().as_str(), first.1);
        assert_eq!(first_hit.title(), Some("[redacted captured title row 1]"));
        assert_eq!(
            first_hit.snippet(),
            Some("[redacted captured snippet row 1]")
        );
        assert_eq!(second_hit.url().as_str(), second.1);
        assert_eq!(second_hit.title(), Some("[redacted captured title row 2]"));
        assert_eq!(
            second_hit.snippet(),
            Some("[redacted captured snippet row 2]")
        );
        assert_eq!(first_hit.placement_index().get(), 1);
        assert_eq!(second_hit.placement_index().get(), 2);
        let capped = parse(
            &document,
            &Policy::default(),
            "https://www.bing.com/search?q=fixture",
            1,
            16 * 1024 * 1024,
        )?;
        let ProviderOutcome::Results(capped_page) = capped else {
            return Err(io::Error::other("expected one capped organic result").into());
        };
        assert_eq!(capped_page.hits().len(), 1);
        assert_eq!(capped_page.coverage().web(), super::WebCoverage::Complete);
        assert!(capped_page.issues().is_empty());
        Ok(())
    }

    #[test]
    fn captured_snippetless_layout_keeps_valid_rows_with_optional_snippets()
    -> Result<(), Box<dyn Error>> {
        let targets = positive_vectors()?;
        let first = targets
            .first()
            .ok_or_else(|| io::Error::other("first synthetic URL target is missing"))?;
        let second = targets
            .get(1)
            .ok_or_else(|| io::Error::other("second synthetic URL target is missing"))?;
        let markup = replace_two_redacted_wrappers(&SNIPPETLESS_ROWS, &first.0, &second.0)?;
        let document = Document::html("bing-snippetless-rows.html", markup.into_bytes())?;
        let outcome = parse(
            &document,
            &Policy::default(),
            "https://www.bing.com/search?q=fixture",
            10,
            16 * 1024 * 1024,
        )?;
        let ProviderOutcome::Results(page) = outcome else {
            return Err(io::Error::other("expected captured snippetless Bing rows").into());
        };
        assert_eq!(page.hits().len(), 2);
        assert!(page.hits().iter().all(|hit| hit.snippet().is_none()));
        Ok(())
    }

    #[test]
    fn synthetic_sponsored_control_is_not_selected_as_a_result_row() -> Result<(), Box<dyn Error>> {
        let document = Document::html(
            "bing-synthetic-sponsored-control.html",
            SPONSORED_CONTROL.as_bytes().to_vec(),
        )?;
        assert!(matches!(
            parse(
                &document,
                &Policy::default(),
                "https://www.bing.com/search?q=fixture",
                10,
                16 * 1024 * 1024,
            ),
            Err(BingParseError::UnrecognizedPage)
        ));
        Ok(())
    }

    #[test]
    fn synthetic_missing_href_row_is_not_usable() -> Result<(), Box<dyn Error>> {
        let document = Document::html(
            "bing-synthetic-missing-href.html",
            MISSING_HREF_CONTROL.as_bytes().to_vec(),
        )?;
        assert!(matches!(
            parse(
                &document,
                &Policy::default(),
                "https://www.bing.com/search?q=fixture",
                10,
                16 * 1024 * 1024,
            ),
            Err(BingParseError::NoUsableHits)
        ));
        Ok(())
    }

    #[test]
    #[ignore = "requires retained local CAS-502 pages; this replay performs no network I/O"]
    fn replay_retained_brave_bing_captures_serially() -> Result<(), Box<dyn Error>> {
        use crate::search::provider::brave;

        let captures = [
            ("brave_standard_http", "brave", 20_usize),
            ("bing_standard_http", "bing", 10_usize),
            ("bing_safari26_http", "bing", 10_usize),
            ("brave_safari26_http", "rate_limited", 0_usize),
        ];
        for (capture_name, provider, expected_hits) in captures {
            let (bytes, status) = load_retained_capture(capture_name)?;
            if provider == "rate_limited" {
                assert_eq!(status, 429);
                eprintln!(
                    "local_search_replay capture={capture_name} bytes={} status={status} classification=rate_limited source=status_manifest parsed=false sha256_verified=true",
                    bytes.len()
                );
                continue;
            }
            assert_eq!(status, 200);
            let document = Document::html(capture_name, bytes.clone())?;
            let outcome = match provider {
                "brave" => brave::parse(
                    &document,
                    &Policy::default(),
                    "https://search.brave.com/search",
                    32,
                    16 * 1024 * 1024,
                )?,
                "bing" => parse(
                    &document,
                    &Policy::default(),
                    "https://www.bing.com/search",
                    32,
                    16 * 1024 * 1024,
                )?,
                _ => return Err(io::Error::other("unknown local replay provider").into()),
            };
            let ProviderOutcome::Results(page) = outcome else {
                return Err(
                    io::Error::other("local successful capture did not parse as results").into(),
                );
            };
            let validated_urls = page
                .hits()
                .iter()
                .filter(|hit| SearchResultUrl::parse(hit.url().as_str()).is_ok())
                .count();
            let invalid_destinations = page
                .issues()
                .iter()
                .filter(|issue| issue.kind == SearchIssueKind::InvalidDestination)
                .count();
            assert_eq!(page.hits().len(), expected_hits);
            assert_eq!(validated_urls, expected_hits);
            assert_eq!(invalid_destinations, 0);
            eprintln!(
                "local_search_replay capture={capture_name} bytes={} status={status} classification=results expected_rows={expected_hits} hits={} validated_http_urls={validated_urls} invalid_destination_issues={invalid_destinations} issue_count={} coverage={:?} sha256_verified=true",
                bytes.len(),
                page.hits().len(),
                page.issues().len(),
                page.coverage().web(),
            );
        }
        Ok(())
    }
}
