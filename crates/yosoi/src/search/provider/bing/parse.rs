use std::collections::HashSet;

use crate::{
    Document, Policy, locator,
    search::{
        FeatureCoverage, ProviderOutcome, SearchCoverage, SearchHit, SearchHitMetadata,
        SearchIssue, SearchIssueKind, SearchPage, WebCoverage,
    },
};

use super::super::row_contract::validated_rows;
use super::common::{
    map_row_contract_error, nonempty_text, nonzero_index, parse_page_url, record_issue,
};
use super::recovery::hits_match_query;
use super::{BingParseError, decode_destination};

const URL_OUTPUT: &str = "result_url";
const ROW_SELECTOR: &str = "li.b_algo";
const TITLE_LINK_SELECTOR: &str = "h2 > a[href]";
const SNIPPET_SELECTOR: &str = ".b_caption > p.b_lineclamp2";

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
