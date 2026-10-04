use std::collections::{BTreeMap, HashSet};

use yosoi_documents::{DocumentClass, LocateOutcome, ProjectedValue};

use crate::{
    Document, Policy, locator,
    search::{
        FeatureCoverage, ProviderOutcome, SearchCoverage, SearchFailure, SearchHit,
        SearchHitMetadata, SearchIssue, SearchIssueKind, SearchPage, SearchResultUrl, WebCoverage,
    },
};

use super::super::row_contract::validated_rows;
use super::common::{
    is_duckduckgo_host, map_row_contract_error, nonempty_text, nonzero_index, parse_page_url,
    record_issue,
};
use super::locations::{is_recognized_empty_page, page_contains_marker, result_plan};
use super::{
    CHALLENGE_MARKER, CHALLENGE_SELECTOR, DuckDuckGoParseError, REGION_ID, ROW_KIND_OUTPUT,
    ROW_SECTION_OUTPUT, ROW_SELECTOR, TITLE_OUTPUT, URL_OUTPUT,
};

#[derive(crate::Contract)]
#[ys(id = "duckduckgo_result_row", description = "One DuckDuckGo result placement", root = locator::css(ROW_SELECTOR))]
struct DuckDuckGoRow {
    #[ys(id = "result_url", description = "The result destination")]
    href: String,
    #[ys(id = "result_title", description = "The result title")]
    title: Option<String>,
    #[ys(id = "result_section", description = "Sections in the result card")]
    sections: Vec<String>,
}

/// Extracts organic DuckDuckGo hits from the RenderedDom returned by the
/// policy-bound Browser Requests acquisition.
pub fn parse(
    document: &Document,
    policy: &Policy,
    provider_page_url: &str,
    result_limit: usize,
    max_output_bytes: usize,
) -> Result<ProviderOutcome, DuckDuckGoParseError> {
    if result_limit == 0 {
        return Err(DuckDuckGoParseError::ZeroResultLimit);
    }
    if max_output_bytes == 0 {
        return Err(DuckDuckGoParseError::OutputLimit);
    }
    if document.class() != DocumentClass::RenderedDom {
        return Err(DuckDuckGoParseError::UnsupportedDocumentClass);
    }
    let page_url = parse_page_url(provider_page_url)?;
    if page_contains_marker(document, policy, CHALLENGE_SELECTOR, CHALLENGE_MARKER)? {
        return Ok(ProviderOutcome::Failed(SearchFailure::Challenge));
    }
    let plan = result_plan()?;
    let located = document.bind(policy).locate(&plan);
    let result = match &located {
        LocateOutcome::Matched { result } => result,
        LocateOutcome::NoMatch { .. } => {
            if is_recognized_empty_page(document, policy)? {
                return Ok(ProviderOutcome::Empty);
            }
            return Err(DuckDuckGoParseError::UnrecognizedPage);
        }
        LocateOutcome::Indeterminate { .. } => {
            return Err(DuckDuckGoParseError::IncompleteDocument);
        }
        LocateOutcome::Failed { .. } => return Err(DuckDuckGoParseError::LocateFailed),
    };

    if result.regions().is_empty() {
        if is_recognized_empty_page(document, policy)? {
            return Ok(ProviderOutcome::Empty);
        }
        return Err(DuckDuckGoParseError::UnrecognizedPage);
    }

    let mut row_kinds = Vec::<&str>::with_capacity(result.regions().len());
    for finding in result.findings() {
        match (finding.output_id().as_str(), finding.parent_region()) {
            (ROW_KIND_OUTPUT, None) => {
                let ProjectedValue::Attribute { value, .. } = finding.value() else {
                    return Err(DuckDuckGoParseError::InvalidLocatorResult);
                };
                row_kinds.push(value);
            }
            (ROW_KIND_OUTPUT, Some(_)) => {
                return Err(DuckDuckGoParseError::InvalidLocatorResult);
            }
            (URL_OUTPUT | TITLE_OUTPUT | ROW_SECTION_OUTPUT, Some(region))
                if region.region_id().as_str() == REGION_ID => {}
            _ => return Err(DuckDuckGoParseError::InvalidLocatorResult),
        }
    }

    let rows = validated_rows(DuckDuckGoRow::extract(&located).validate(), URL_OUTPUT)
        .map_err(map_row_contract_error)?;

    if row_kinds.len() != rows.len() {
        return Err(DuckDuckGoParseError::InvalidLocatorResult);
    }
    let row_kinds = rows
        .keys()
        .copied()
        .zip(row_kinds)
        .collect::<BTreeMap<_, _>>();

    let mut hits = Vec::with_capacity(rows.len().min(result_limit));
    let mut issues = Vec::with_capacity(rows.len().min(result_limit));
    let mut seen_destinations = HashSet::<String>::new();
    let mut partial = false;
    let mut dropped_issues = false;
    let mut output_limited = false;
    let mut output_limit_index = None;
    let mut retained_string_bytes = 0_usize;
    let mut organic_rank = 0_u64;

    for (ordinal, row) in rows {
        let Some(row_kind) = row_kinds.get(&ordinal).copied() else {
            return Err(DuckDuckGoParseError::InvalidLocatorResult);
        };
        let Some(placement_index) = nonzero_index(ordinal) else {
            partial = true;
            output_limited = true;
            break;
        };
        match row_kind {
            "ad" => continue,
            "result" => {}
            _ => {
                partial = true;
                record_issue(
                    &mut issues,
                    SearchIssue {
                        placement_index: Some(placement_index),
                        kind: SearchIssueKind::UnrecognizedResultRow,
                    },
                    result_limit,
                    &mut dropped_issues,
                );
                continue;
            }
        }

        organic_rank = organic_rank
            .checked_add(1)
            .ok_or(DuckDuckGoParseError::OutputLimit)?;
        let Some(rank) = nonzero_index(organic_rank) else {
            partial = true;
            output_limited = true;
            output_limit_index = Some(placement_index);
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
        if is_duckduckgo_host(destination.host_str()) {
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

        let title = row.title.as_deref().and_then(nonempty_text);
        let snippet = row
            .sections
            .get(3)
            .map(String::as_str)
            .and_then(nonempty_text);
        let row_bytes = url
            .as_str()
            .len()
            .checked_add(title.map_or(0, str::len))
            .and_then(|bytes| bytes.checked_add(snippet.map_or(0, str::len)))
            .ok_or(DuckDuckGoParseError::OutputLimit)?;
        let Some(next_bytes) = retained_string_bytes.checked_add(row_bytes) else {
            return Err(DuckDuckGoParseError::OutputLimit);
        };
        if next_bytes > max_output_bytes {
            if hits.is_empty() {
                return Err(DuckDuckGoParseError::OutputLimit);
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
        if issues.len() >= result_limit {
            issues.truncate(result_limit.saturating_sub(1));
        }
        issues.push(SearchIssue {
            placement_index: output_limit_index,
            kind: SearchIssueKind::OutputLimit,
        });
    }

    if hits.is_empty() {
        return Err(DuckDuckGoParseError::NoUsableHits);
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
