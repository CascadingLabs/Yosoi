//! Brave Direct HTTP result-row parsing from a retained HTML Document.
//!
//! The parser uses one repeated locator region per result card so its URL,
//! title, and snippet cannot be combined across neighboring cards. A page with
//! no recognized rows is an unrecognized document, not an empty result set;
//! empty and challenge markers need captured provider evidence before they can
//! be classified here.
//! Live release certification still needs real empty/challenge fixtures or
//! separately observed classification evidence.

use crate::internal::engine as yosoi_engine;

use std::{collections::HashSet, num::NonZeroU16};

use crate::internal::engine::{
    Document, Policy, locator,
    search::{
        FeatureCoverage, ProviderOutcome, SearchCoverage, SearchHit, SearchHitMetadata,
        SearchIssue, SearchIssueKind, SearchPage, SearchResultUrl, WebCoverage,
    },
};
use thiserror::Error;
use url::Url;

use super::row_contract::{RowContractError, validated_rows};

const PAGE_HOST: &str = "search.brave.com";
const PAGE_PATH: &str = "/search";
const MAX_PROVIDER_PAGE_URL_BYTES: usize = 8_192;
const URL_OUTPUT: &str = "result_url";
const ROW_SELECTOR: &str = ".result-wrapper";
const TITLE_LINK_SELECTOR: &str = ".result-content > a.l1[href]";
const TITLE_SELECTOR: &str = ".result-content > a.l1 .title";
const SNIPPET_SELECTOR: &str = ".generic-snippet > .content";

/// Structural failure while interpreting a retained Brave result document.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum BraveParseError {
    #[error("result limit must be greater than zero")]
    ZeroResultLimit,
    #[error("normalized provider output exceeds the Search byte limit")]
    OutputLimit,
    #[error("provider page URL is invalid or is not the observed Brave search endpoint")]
    InvalidPageUrl,
    #[error("provider locator plan is invalid")]
    InvalidPlan,
    #[error("provider document has no recognized Brave result rows")]
    UnrecognizedPage,
    #[error("provider document has no usable Brave organic results")]
    NoUsableHits,
    #[error("provider document is incomplete for result parsing")]
    IncompleteDocument,
    #[error("provider document could not be located")]
    LocateFailed,
    #[error("provider locator findings do not match the result-row plan")]
    InvalidLocatorResult,
}

#[derive(yosoi_engine::Contract)]
#[ys(crate = "crate::internal::engine")]
#[ys(id = "brave_result", description = "One Brave organic result", root = locator::css(ROW_SELECTOR))]
struct BraveRow {
    #[ys(id = "result_url", description = "The result destination", locator = locator::css(TITLE_LINK_SELECTOR).attribute("href"))]
    href: String,
    #[ys(id = "result_title", description = "The result title", locator = locator::css(TITLE_SELECTOR).text())]
    title: Option<String>,
    #[ys(id = "result_snippet", description = "The result summary", locator = locator::css(SNIPPET_SELECTOR).text())]
    snippet: Option<String>,
}

/// Extracts Brave result rows from an already retained Yosoi HTML Document.
///
/// An unrecognized zero-row page returns `UnrecognizedPage`; it is never
/// silently converted to `ProviderOutcome::Empty`.
pub fn parse(
    document: &Document,
    policy: &Policy,
    provider_page_url: &str,
    result_limit: usize,
    max_output_bytes: usize,
) -> Result<ProviderOutcome, BraveParseError> {
    if result_limit == 0 {
        return Err(BraveParseError::ZeroResultLimit);
    }
    if max_output_bytes == 0 {
        return Err(BraveParseError::OutputLimit);
    }
    let page_url = parse_page_url(provider_page_url)?;
    let plan = BraveRow::plan().map_err(|_| BraveParseError::InvalidPlan)?;
    let located = document.bind(policy).locate(plan);
    let rows = validated_rows(BraveRow::extract(&located).validate(), URL_OUTPUT)
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
        let Ok(destination) = page_url.join(href) else {
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
        let Ok(url) = SearchResultUrl::parse(destination.as_str()) else {
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
        if destination.host_str() == Some(PAGE_HOST) {
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
        }
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
            .ok_or(BraveParseError::OutputLimit)?;
        let Some(next_bytes) = retained_string_bytes.checked_add(row_bytes) else {
            return Err(BraveParseError::OutputLimit);
        };
        if next_bytes > max_output_bytes {
            if hits.is_empty() {
                return Err(BraveParseError::OutputLimit);
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
        return Err(BraveParseError::NoUsableHits);
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

fn parse_page_url(value: &str) -> Result<Url, BraveParseError> {
    if value.len() > MAX_PROVIDER_PAGE_URL_BYTES {
        return Err(BraveParseError::InvalidPageUrl);
    }
    let Ok(url) = Url::parse(value) else {
        return Err(BraveParseError::InvalidPageUrl);
    };
    if url.scheme() != "https"
        || url.host_str() != Some(PAGE_HOST)
        || url.path() != PAGE_PATH
        || has_user_information(&url)
    {
        return Err(BraveParseError::InvalidPageUrl);
    }
    Ok(url)
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

const fn map_row_contract_error(error: RowContractError) -> BraveParseError {
    match error {
        RowContractError::UnrecognizedPage => BraveParseError::UnrecognizedPage,
        RowContractError::IncompleteDocument => BraveParseError::IncompleteDocument,
        RowContractError::LocateFailed => BraveParseError::LocateFailed,
        RowContractError::InvalidLocatorResult => BraveParseError::InvalidLocatorResult,
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
#[path = "brave_tests.rs"]
mod tests;
