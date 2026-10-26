//! Google web result extraction from captured rendered DOM.
//!
//! Result rows are grouped through Contracts. Unknown/opaque redirect destinations
//! are rejected rather than invented from truncated display URLs.

use crate::internal::documents::{DocumentClass, LocateOutcome, Plan, ProjectedValue, css, output};
use crate::internal::engine as yosoi_engine;

use std::{
    collections::{HashMap, HashSet},
    num::NonZeroU16,
};

use crate::internal::engine::{
    Document, Policy, locator,
    search::{
        FeatureCoverage, ProviderOutcome, SearchCoverage, SearchFailure, SearchHit,
        SearchHitMetadata, SearchIssue, SearchIssueKind, SearchPage, SearchResultUrl, WebCoverage,
    },
};
use thiserror::Error;
use url::Url;

use super::row_contract::{RowContractError, validated_rows};

const PAGE_HOST: &str = "www.google.com";
const PAGE_PATH: &str = "/search";
const MAX_PROVIDER_PAGE_URL_BYTES: usize = 8_192;
const MAX_OPAQUE_REDIRECT_URL_BYTES: usize = 4_096;
const GOOGLE_WEB_SEARCH_HOSTS: [&str; 2] = ["google.com", "www.google.com"];
const GOOGLE_RESULT_INTERMEDIARY_DOMAINS: [&str; 2] = ["googleadservices.com", "g.co"];
const URL_OUTPUT: &str = "result_url";
const ROW_SELECTOR: &str = ".tF2Cxc";
const TITLE_LINK_SELECTOR: &str = ".yuRUbf a.zReHs[href]";
const TITLE_SELECTOR: &str = ".yuRUbf h3";
const SNIPPET_SELECTOR: &str = ".VwiC3b";

/// Structural failure while interpreting a retained Google result document.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum GoogleParseError {
    #[error("result limit must be greater than zero")]
    ZeroResultLimit,
    #[error("Google parsing requires a rendered DOM document")]
    UnsupportedDocumentClass,
    #[error("normalized provider output exceeds the Search byte limit")]
    OutputLimit,
    #[error("provider page URL is invalid or is not the observed Google search endpoint")]
    InvalidPageUrl,
    #[error("provider locator plan is invalid")]
    InvalidPlan,
    #[error("provider document has no recognized Google result rows")]
    UnrecognizedPage,
    #[error("provider document has no usable Google organic results")]
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
#[ys(id = "google_result", description = "One Google organic result", root = locator::css(ROW_SELECTOR))]
struct GoogleRow {
    #[ys(id = "result_url", description = "The result destination", locator = locator::css(TITLE_LINK_SELECTOR).attribute("href"))]
    href: String,
    #[ys(id = "result_title", description = "The result title", locator = locator::css(TITLE_SELECTOR).text())]
    title: Option<String>,
    #[ys(id = "result_snippet", description = "The result summary", locator = locator::css(SNIPPET_SELECTOR).text())]
    snippet: Option<String>,
}

pub(in crate::internal::engine::search) enum GoogleParsedDocument {
    Challenge,
    Results(GoogleParsedPage),
}

pub(in crate::internal::engine::search) struct GoogleParsedPage {
    candidates: Vec<GoogleResultCandidate>,
    issues: Vec<SearchIssue>,
    partial: bool,
    dropped_issues: bool,
}

struct GoogleResultCandidate {
    placement_index: NonZeroU16,
    target: GoogleResultTarget,
    title: Option<String>,
    snippet: Option<String>,
}

enum GoogleResultTarget {
    Direct(SearchResultUrl),
    Opaque(Url),
}

impl GoogleParsedPage {
    pub(in crate::internal::engine::search) fn opaque_redirects(
        &self,
    ) -> impl Iterator<Item = (NonZeroU16, &Url)> {
        self.candidates.iter().filter_map(|candidate| {
            let GoogleResultTarget::Opaque(url) = &candidate.target else {
                return None;
            };
            Some((candidate.placement_index, url))
        })
    }

    pub(in crate::internal::engine::search) fn finish(
        mut self,
        resolved: &HashMap<NonZeroU16, SearchResultUrl>,
        failed_redirects: &HashMap<NonZeroU16, SearchIssueKind>,
        result_limit: usize,
        max_output_bytes: usize,
    ) -> Result<ProviderOutcome, GoogleParseError> {
        if result_limit == 0 {
            return Err(GoogleParseError::ZeroResultLimit);
        }
        if max_output_bytes == 0 {
            return Err(GoogleParseError::OutputLimit);
        }
        let mut hits = Vec::with_capacity(self.candidates.len().min(result_limit));
        let mut seen_destinations = HashSet::<String>::new();
        let mut retained_string_bytes = 0_usize;
        let mut output_limited = false;
        let mut output_limit_index = None;

        for candidate in self.candidates {
            let destination = match candidate.target {
                GoogleResultTarget::Direct(url) => Some(url),
                GoogleResultTarget::Opaque(_) => resolved.get(&candidate.placement_index).cloned(),
            };
            let Some(url) = destination else {
                self.partial = true;
                let issue_kind = failed_redirects
                    .get(&candidate.placement_index)
                    .copied()
                    .unwrap_or(SearchIssueKind::RedirectResolutionFailed);
                record_issue(
                    &mut self.issues,
                    SearchIssue {
                        placement_index: Some(candidate.placement_index),
                        kind: issue_kind,
                    },
                    result_limit,
                    &mut self.dropped_issues,
                );
                continue;
            };
            if !seen_destinations.insert(url.as_str().to_owned()) {
                self.partial = true;
                record_issue(
                    &mut self.issues,
                    SearchIssue {
                        placement_index: Some(candidate.placement_index),
                        kind: SearchIssueKind::DuplicateDestination,
                    },
                    result_limit,
                    &mut self.dropped_issues,
                );
                continue;
            }
            let row_bytes = url
                .as_str()
                .len()
                .checked_add(candidate.title.as_deref().map_or(0, str::len))
                .and_then(|bytes| {
                    bytes.checked_add(candidate.snippet.as_deref().map_or(0, str::len))
                })
                .ok_or(GoogleParseError::OutputLimit)?;
            let Some(next_bytes) = retained_string_bytes.checked_add(row_bytes) else {
                return Err(GoogleParseError::OutputLimit);
            };
            if next_bytes > max_output_bytes {
                if hits.is_empty() {
                    return Err(GoogleParseError::OutputLimit);
                }
                self.partial = true;
                output_limited = true;
                output_limit_index = Some(candidate.placement_index);
                break;
            }
            retained_string_bytes = next_bytes;
            let metadata = SearchHitMetadata {
                title: candidate.title,
                snippet: candidate.snippet,
                ..SearchHitMetadata::default()
            };
            hits.push(
                SearchHit::new(url, candidate.placement_index, candidate.placement_index)
                    .with_metadata(metadata),
            );
        }

        if output_limited || self.dropped_issues {
            self.partial = true;
            if self.issues.len() >= result_limit {
                self.issues.truncate(result_limit.saturating_sub(1));
            }
            self.issues.push(SearchIssue {
                placement_index: output_limit_index,
                kind: SearchIssueKind::OutputLimit,
            });
        }
        if hits.is_empty() {
            return Err(GoogleParseError::NoUsableHits);
        }
        let coverage = SearchCoverage::new(
            if self.partial {
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
            self.issues,
        )))
    }
}

/// Extracts Google web-result rows from a retained rendered DOM Document.
///
/// An unrecognized zero-row page returns `UnrecognizedPage`; it is never
/// silently converted to `ProviderOutcome::Empty`.
pub fn parse(
    document: &Document,
    policy: &Policy,
    provider_page_url: &str,
    result_limit: usize,
    max_output_bytes: usize,
) -> Result<ProviderOutcome, GoogleParseError> {
    if result_limit == 0 {
        return Err(GoogleParseError::ZeroResultLimit);
    }
    if max_output_bytes == 0 {
        return Err(GoogleParseError::OutputLimit);
    }
    match parse_rows(document, policy, provider_page_url, result_limit)? {
        GoogleParsedDocument::Challenge => Ok(ProviderOutcome::Failed(SearchFailure::Challenge)),
        GoogleParsedDocument::Results(page) => page.finish(
            &HashMap::new(),
            &HashMap::new(),
            result_limit,
            max_output_bytes,
        ),
    }
}

pub(in crate::internal::engine::search) fn parse_rows(
    document: &Document,
    policy: &Policy,
    provider_page_url: &str,
    result_limit: usize,
) -> Result<GoogleParsedDocument, GoogleParseError> {
    if result_limit == 0 {
        return Err(GoogleParseError::ZeroResultLimit);
    }
    if document.class() != DocumentClass::RenderedDom {
        return Err(GoogleParseError::UnsupportedDocumentClass);
    }
    let page_url = parse_page_url(provider_page_url)?;
    if is_challenge(document, policy)? {
        return Ok(GoogleParsedDocument::Challenge);
    }
    let plan = GoogleRow::plan().map_err(|_| GoogleParseError::InvalidPlan)?;
    let located = document.bind(policy).locate(plan);
    let rows = validated_rows(GoogleRow::extract(&located).validate(), URL_OUTPUT)
        .map_err(map_row_contract_error)?;

    let mut candidates = Vec::with_capacity(rows.len().min(result_limit));
    let mut issues = Vec::with_capacity(rows.len().min(result_limit));
    let mut seen_direct_destinations = HashSet::<String>::new();
    let mut partial = false;
    let mut dropped_issues = false;

    for (ordinal, row) in rows {
        let Some(placement_index) = nonzero_index(ordinal) else {
            partial = true;
            break;
        };
        // Reaching the requested hit count is normal completion for this Policy.
        // It does not mean the retained result is partial or byte limited.
        if candidates.len() >= result_limit {
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
        let Some(target) = result_target(&page_url, href) else {
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
        if let GoogleResultTarget::Direct(url) = &target
            && !seen_direct_destinations.insert(url.as_str().to_owned())
        {
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
        let title = row.title.as_deref().and_then(nonempty_text);
        let snippet = row.snippet.as_deref().and_then(nonempty_text);
        candidates.push(GoogleResultCandidate {
            placement_index,
            target,
            title: title.map(str::to_owned),
            snippet: snippet.map(str::to_owned),
        });
    }

    if candidates.is_empty() {
        return Err(GoogleParseError::NoUsableHits);
    }
    Ok(GoogleParsedDocument::Results(GoogleParsedPage {
        candidates,
        issues,
        partial,
        dropped_issues,
    }))
}

fn is_challenge(document: &Document, policy: &Policy) -> Result<bool, GoogleParseError> {
    let body = css("body").map_err(|_| GoogleParseError::InvalidPlan)?;
    let form = css("form#captcha-form").map_err(|_| GoogleParseError::InvalidPlan)?;
    let form_id = form
        .attribute("id")
        .map_err(|_| GoogleParseError::InvalidPlan)?;
    let plan = Plan::new([
        output("google_challenge_text", body.text()).map_err(|_| GoogleParseError::InvalidPlan)?,
        output("google_challenge_form", form_id).map_err(|_| GoogleParseError::InvalidPlan)?,
    ])
    .map_err(|_| GoogleParseError::InvalidPlan)?;
    match document.bind(policy).locate(&plan) {
        LocateOutcome::Matched { result } => {
            let text = result.findings().iter().any(|finding| {
                matches!(
                    finding.value(), ProjectedValue::Text(value)
                        if value.contains("Our systems have detected unusual traffic")
                )
            });
            let form = result.findings().iter().any(|finding| {
                matches!(
                finding.value(), ProjectedValue::Attribute { name, value }
                    if name == "id" && value == "captcha-form"
                )
            });
            Ok(text && form)
        }
        LocateOutcome::NoMatch { .. } => Ok(false),
        LocateOutcome::Indeterminate { .. } => Err(GoogleParseError::IncompleteDocument),
        LocateOutcome::Failed { .. } => Err(GoogleParseError::LocateFailed),
    }
}

fn result_destination(page: &Url, href: &str) -> Option<Url> {
    let url = page.join(href).ok()?;
    if matches!(url.host_str(), Some("www.google.com" | "google.com")) {
        if url.path() != "/url" {
            return None;
        }
        let values = url
            .query_pairs()
            .filter(|(name, _)| name == "q" || name == "url")
            .map(|(_, value)| value.into_owned())
            .collect::<Vec<_>>();
        let [value] = values.as_slice() else {
            return None;
        };
        let destination = Url::parse(value).ok()?;
        if matches!(
            destination.host_str(),
            Some("www.google.com" | "google.com")
        ) {
            return None;
        }
        return Some(destination);
    }
    Some(url)
}

fn result_target(page: &Url, href: &str) -> Option<GoogleResultTarget> {
    let joined = page.join(href).ok()?;
    if is_opaque_redirect(&joined) {
        return Some(GoogleResultTarget::Opaque(joined));
    }
    let destination = result_destination(page, href)?;
    if is_google_intermediary_url(&destination) {
        return None;
    }
    let url = SearchResultUrl::parse(destination.as_str()).ok()?;
    Some(GoogleResultTarget::Direct(url))
}

/// Google may publish an opaque, provider-owned link instead of the destination.
/// Such links must be resolved with redirects disabled before a hit is returned.
pub(in crate::internal::engine::search) fn is_opaque_redirect(url: &Url) -> bool {
    url.as_str().len() <= MAX_OPAQUE_REDIRECT_URL_BYTES
        && url.scheme() == "https"
        && url.host_str() == Some(PAGE_HOST)
        && url.port().is_none()
        && !has_user_information(url)
        && url.path() == "/goto"
        && {
            let values = url
                .query_pairs()
                .filter(|(key, _)| key == "url")
                .collect::<Vec<_>>();
            matches!(values.as_slice(), [(_, value)] if !value.is_empty())
        }
}

/// Accept only a single provider redirect to a validated external destination.
pub(in crate::internal::engine::search) fn redirect_destination(
    requested: &Url,
    location: &str,
) -> Option<SearchResultUrl> {
    if !is_opaque_redirect(requested) || location.len() > MAX_OPAQUE_REDIRECT_URL_BYTES {
        return None;
    }
    let destination = requested.join(location).ok()?;
    if is_google_intermediary_url(&destination) {
        return None;
    }
    SearchResultUrl::parse(destination.as_str()).ok()
}

pub(in crate::internal::engine::search) fn is_google_challenge_redirect(
    requested: &Url,
    location: &str,
) -> bool {
    if !is_opaque_redirect(requested) || location.len() > MAX_OPAQUE_REDIRECT_URL_BYTES {
        return false;
    }
    let Ok(destination) = requested.join(location) else {
        return false;
    };
    destination.scheme() == "https"
        && matches!(
            destination.host_str(),
            Some("www.google.com" | "google.com")
        )
        && destination.port().is_none()
        && !has_user_information(&destination)
        && (matches!(destination.path(), "/sorry" | "/recaptcha")
            || destination.path().starts_with("/sorry/")
            || destination.path().starts_with("/recaptcha/"))
}

fn is_google_intermediary_url(url: &Url) -> bool {
    let Some(host) = url.host_str() else {
        return false;
    };
    GOOGLE_RESULT_INTERMEDIARY_DOMAINS
        .iter()
        .any(|domain| host == *domain || is_subdomain_of(host, domain))
        || (is_google_search_host(host) && is_google_intermediary_path(url.path()))
}

fn is_google_search_host(host: &str) -> bool {
    GOOGLE_WEB_SEARCH_HOSTS.contains(&host)
}

fn is_google_intermediary_path(path: &str) -> bool {
    [
        "/search",
        "/goto",
        "/url",
        "/sorry",
        "/recaptcha",
        "/aclk",
        "/imgres",
    ]
    .iter()
    .any(|endpoint| path == *endpoint || is_path_below(path, endpoint))
}

fn is_path_below(path: &str, endpoint: &str) -> bool {
    path.strip_prefix(endpoint)
        .is_some_and(|remainder| remainder.starts_with('/'))
}

fn is_subdomain_of(host: &str, domain: &str) -> bool {
    host.strip_suffix(domain)
        .is_some_and(|prefix| prefix.ends_with('.'))
}

pub(in crate::internal::engine::search) fn response_is_challenge(body: &[u8]) -> bool {
    contains_ascii_case_insensitive(body, b"unusual traffic")
        && contains_ascii_case_insensitive(body, b"captcha-form")
}

fn contains_ascii_case_insensitive(haystack: &[u8], needle: &[u8]) -> bool {
    !needle.is_empty()
        && haystack
            .windows(needle.len())
            .any(|window| window.eq_ignore_ascii_case(needle))
}

fn parse_page_url(value: &str) -> Result<Url, GoogleParseError> {
    if value.len() > MAX_PROVIDER_PAGE_URL_BYTES {
        return Err(GoogleParseError::InvalidPageUrl);
    }
    let Ok(url) = Url::parse(value) else {
        return Err(GoogleParseError::InvalidPageUrl);
    };
    if url.scheme() != "https"
        || url.host_str() != Some(PAGE_HOST)
        || url.path() != PAGE_PATH
        || has_user_information(&url)
    {
        return Err(GoogleParseError::InvalidPageUrl);
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

const fn map_row_contract_error(error: RowContractError) -> GoogleParseError {
    match error {
        RowContractError::UnrecognizedPage => GoogleParseError::UnrecognizedPage,
        RowContractError::IncompleteDocument => GoogleParseError::IncompleteDocument,
        RowContractError::LocateFailed => GoogleParseError::LocateFailed,
        RowContractError::InvalidLocatorResult => GoogleParseError::InvalidLocatorResult,
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
#[path = "google_tests.rs"]
mod tests;
