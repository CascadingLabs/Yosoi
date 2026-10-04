//! DuckDuckGo regular-web result rows from a retained RenderedDom Document.
//!
//! The adapter uses the Search-owned Browser Requests profile. It keeps ad
//! rows in the shared locator regions so organic ranks and page placements
//! remain distinct. An unknown page with no recognized result rows is a parse
//! failure, never an invented empty result page.

use std::{
    collections::{BTreeMap, HashSet},
    num::NonZeroU16,
};

use thiserror::Error;
use url::Url;
use yosoi_documents::{DocumentClass, LocateOutcome, Plan, ProjectedValue, css, output};

use crate::{
    Document, Policy, locator,
    search::{
        FeatureCoverage, ProviderOutcome, SearchCoverage, SearchFailure, SearchHit,
        SearchHitMetadata, SearchIssue, SearchIssueKind, SearchPage, SearchResultUrl, WebCoverage,
    },
};

use super::row_contract::{RowContractError, validated_rows};

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
// The observed snippet is the fourth direct div child of each organic row.
// Yosoi's bounded CSS subset does not support nth-child; keep the row grouping
// in Locators and select that direct-child position after projection.
const ROW_SECTION_SELECTOR: &str = "article[data-testid=\"result\"] > div";
const EMPTY_MESSAGE_SELECTOR: &str = "section[data-testid=\"mainline\"] p";
const EMPTY_MESSAGE_MARKER: &str = "No results found for";
// Observed in the saved DuckDuckGo HTML 202 challenge; a browser DOM carrying
// the same provider-owned marker is classified without guessing from zero rows.
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

fn is_recognized_empty_page(
    document: &Document,
    policy: &Policy,
) -> Result<bool, DuckDuckGoParseError> {
    page_contains_marker(
        document,
        policy,
        EMPTY_MESSAGE_SELECTOR,
        EMPTY_MESSAGE_MARKER,
    )
}

fn page_contains_marker(
    document: &Document,
    policy: &Policy,
    selector: &str,
    marker: &str,
) -> Result<bool, DuckDuckGoParseError> {
    let query = css(selector).map_err(|_| DuckDuckGoParseError::InvalidQuery)?;
    let plan = Plan::new([output("duckduckgo_page_marker", query.text())
        .map_err(|_| DuckDuckGoParseError::InvalidPlan)?])
    .map_err(|_| DuckDuckGoParseError::InvalidPlan)?;
    match document.bind(policy).locate(&plan) {
        LocateOutcome::Matched { result } => Ok(result.findings().iter().any(|finding| {
            matches!(finding.value(), ProjectedValue::Text(text) if text.contains(marker))
        })),
        LocateOutcome::NoMatch { .. } => Ok(false),
        LocateOutcome::Indeterminate { .. } => Err(DuckDuckGoParseError::IncompleteDocument),
        LocateOutcome::Failed { .. } => Err(DuckDuckGoParseError::LocateFailed),
    }
}

fn parse_page_url(value: &str) -> Result<Url, DuckDuckGoParseError> {
    if value.len() > MAX_PROVIDER_PAGE_URL_BYTES {
        return Err(DuckDuckGoParseError::InvalidPageUrl);
    }
    let Ok(url) = Url::parse(value) else {
        return Err(DuckDuckGoParseError::InvalidPageUrl);
    };
    if url.scheme() != "https"
        || url.host_str() != Some(PAGE_HOST)
        || url.path() != PAGE_PATH
        || !url.username().is_empty()
        || url.password().is_some()
    {
        return Err(DuckDuckGoParseError::InvalidPageUrl);
    }
    Ok(url)
}

fn is_duckduckgo_host(host: Option<&str>) -> bool {
    host.is_some_and(|value| value == PAGE_HOST || value.ends_with(".duckduckgo.com"))
}

fn result_plan() -> Result<Plan, DuckDuckGoParseError> {
    let row_query = css(ROW_SELECTOR).map_err(|_| DuckDuckGoParseError::InvalidQuery)?;
    let rows = row_query
        .clone()
        .each_as_region(REGION_ID)
        .map_err(|_| DuckDuckGoParseError::InvalidQuery)?;
    let row_kind = row_query
        .attribute("data-testid")
        .map_err(|_| DuckDuckGoParseError::InvalidQuery)?;
    let url = rows
        .find(css(TITLE_LINK_SELECTOR).map_err(|_| DuckDuckGoParseError::InvalidQuery)?)
        .attribute("href")
        .map_err(|_| DuckDuckGoParseError::InvalidQuery)?;
    let title = rows
        .find(css(TITLE_LINK_SELECTOR).map_err(|_| DuckDuckGoParseError::InvalidQuery)?)
        .text();
    let snippet = rows
        .find(css(ROW_SECTION_SELECTOR).map_err(|_| DuckDuckGoParseError::InvalidQuery)?)
        .text();
    Plan::new([
        output(ROW_KIND_OUTPUT, row_kind).map_err(|_| DuckDuckGoParseError::InvalidPlan)?,
        output(URL_OUTPUT, url).map_err(|_| DuckDuckGoParseError::InvalidPlan)?,
        output(TITLE_OUTPUT, title).map_err(|_| DuckDuckGoParseError::InvalidPlan)?,
        output(ROW_SECTION_OUTPUT, snippet).map_err(|_| DuckDuckGoParseError::InvalidPlan)?,
    ])
    .map_err(|_| DuckDuckGoParseError::InvalidPlan)
}

const fn map_row_contract_error(error: RowContractError) -> DuckDuckGoParseError {
    match error {
        RowContractError::UnrecognizedPage => DuckDuckGoParseError::UnrecognizedPage,
        RowContractError::IncompleteDocument => DuckDuckGoParseError::IncompleteDocument,
        RowContractError::LocateFailed => DuckDuckGoParseError::LocateFailed,
        RowContractError::InvalidLocatorResult => DuckDuckGoParseError::InvalidLocatorResult,
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
    use std::{error::Error, fs, io, path::PathBuf};

    use sha2::{Digest as _, Sha256};
    use yosoi_documents::DocumentEpoch;

    use super::{DuckDuckGoParseError, parse};
    use crate::{Document, Policy, search::ProviderOutcome};

    const ROWS: &str = include_str!("duckduckgo-rendered-dom.json");
    const EMPTY: &str = include_str!("duckduckgo-empty-rendered-dom.json");
    const CHALLENGE: &str = include_str!("duckduckgo-synthetic-challenge-rendered-dom.json");
    const PAGE_URL: &str = "https://duckduckgo.com/?q=fixture";
    const RESULT_LIMIT: usize = 10;
    const OUTPUT_LIMIT: usize = 16 * 1024 * 1024;

    fn rendered_document(id: &str, bytes: impl Into<Vec<u8>>) -> Result<Document, Box<dyn Error>> {
        Ok(Document::rendered_dom(
            id,
            DocumentEpoch::try_from(1_u64)?,
            bytes,
        )?)
    }

    #[test]
    fn sanitized_rows_keep_fields_together_skip_ads_and_preserve_placement()
    -> Result<(), Box<dyn Error>> {
        let document = rendered_document("duckduckgo-results.json", ROWS.as_bytes().to_vec())?;
        let outcome = parse(
            &document,
            &Policy::default(),
            PAGE_URL,
            RESULT_LIMIT,
            OUTPUT_LIMIT,
        )?;
        let ProviderOutcome::Results(page) = outcome else {
            return Err(io::Error::other("expected parsed DuckDuckGo results").into());
        };
        let first = page
            .hits()
            .first()
            .ok_or_else(|| io::Error::other("missing first organic result"))?;
        let second = page
            .hits()
            .get(1)
            .ok_or_else(|| io::Error::other("missing second organic result"))?;

        assert_eq!(page.hits().len(), 2);
        assert_eq!(first.url().as_str(), "https://rust-lang.org/");
        assert_eq!(first.title(), Some("[redacted first title]"));
        assert_eq!(first.snippet(), Some("[redacted first snippet]"));
        assert_eq!(first.organic_rank().get(), 1);
        assert_eq!(first.placement_index().get(), 2);
        assert_eq!(second.url().as_str(), "https://doc.rust-lang.org/book/");
        assert_eq!(second.title(), Some("[redacted second title]"));
        assert_eq!(second.snippet(), Some("[redacted second snippet]"));
        assert_eq!(second.organic_rank().get(), 2);
        assert_eq!(second.placement_index().get(), 3);
        assert_eq!(page.coverage().web(), super::WebCoverage::Complete);
        assert!(page.issues().is_empty());
        let capped = parse(
            &document,
            &Policy::default(),
            "https://duckduckgo.com/?q=fixture",
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
    fn observed_mainline_empty_marker_is_empty() -> Result<(), Box<dyn Error>> {
        let document = rendered_document("duckduckgo-empty.json", EMPTY.as_bytes().to_vec())?;
        assert!(matches!(
            parse(
                &document,
                &Policy::default(),
                PAGE_URL,
                RESULT_LIMIT,
                OUTPUT_LIMIT
            ),
            Ok(ProviderOutcome::Empty)
        ));
        Ok(())
    }

    #[test]
    fn known_provider_challenge_marker_is_failed_challenge() -> Result<(), Box<dyn Error>> {
        let document = rendered_document("duckduckgo-challenge.json", CHALLENGE.as_bytes())?;
        assert!(matches!(
            parse(
                &document,
                &Policy::default(),
                PAGE_URL,
                RESULT_LIMIT,
                OUTPUT_LIMIT
            ),
            Ok(ProviderOutcome::Failed(super::SearchFailure::Challenge))
        ));
        Ok(())
    }

    #[test]
    fn unknown_zero_row_document_is_not_empty() -> Result<(), Box<dyn Error>> {
        let empty_tree = r#"{"schema":"yosoi.rendered-dom.v1","document_epoch":1,"tree_model":"document_light_dom","root":1,"nodes":[{"kind":"document","id":1,"parent":null,"children":[2]},{"kind":"element","id":2,"parent":1,"children":[3],"namespace_uri":"http://www.w3.org/1999/xhtml","tag_name":"html","attributes":[]},{"kind":"element","id":3,"parent":2,"children":[],"namespace_uri":"http://www.w3.org/1999/xhtml","tag_name":"body","attributes":[]}] }"#;
        let document = rendered_document("duckduckgo-unrecognized.json", empty_tree.as_bytes())?;
        assert!(matches!(
            parse(
                &document,
                &Policy::default(),
                PAGE_URL,
                RESULT_LIMIT,
                OUTPUT_LIMIT
            ),
            Err(DuckDuckGoParseError::UnrecognizedPage)
        ));
        Ok(())
    }

    #[test]
    fn first_hit_cannot_exceed_normalized_byte_budget() -> Result<(), Box<dyn Error>> {
        let document = rendered_document("duckduckgo-byte-limit.json", ROWS.as_bytes().to_vec())?;
        assert!(matches!(
            parse(&document, &Policy::default(), PAGE_URL, RESULT_LIMIT, 1),
            Err(DuckDuckGoParseError::OutputLimit)
        ));
        Ok(())
    }

    #[test]
    #[ignore = "requires the retained local CAS-502 rendered DOM; no network I/O"]
    fn replay_retained_headful_dom_reports_bounded_row_issues() -> Result<(), Box<dyn Error>> {
        let path = std::env::var_os("YS_DDG_CAPTURE_PATH")
            .map(PathBuf::from)
            .ok_or_else(|| io::Error::other("YS_DDG_CAPTURE_PATH is required"))?;
        let bytes = fs::read(path)?;
        let digest = format!("{:x}", Sha256::digest(&bytes));
        assert_eq!(
            digest,
            "14b522250b20df13ffb2aaf7831f0ca67da070350bb20def6845892fef652293"
        );
        let document = rendered_document("duckduckgo-retained-dom.json", bytes)?;
        let outcome = parse(&document, &Policy::default(), PAGE_URL, 10, OUTPUT_LIMIT)?;
        let ProviderOutcome::Results(page) = outcome else {
            return Err(io::Error::other("retained DDG page did not yield results").into());
        };
        println!(
            "ddg_replay hits={} issue_count={} coverage={:?}",
            page.hits().len(),
            page.issues().len(),
            page.coverage().web()
        );
        for issue in page.issues() {
            println!(
                "ddg_replay issue_kind={:?} placement_index={:?}",
                issue.kind,
                issue.placement_index.map(|index| index.get())
            );
        }
        assert_eq!(page.hits().len(), 10);
        assert!(page.issues().is_empty());
        assert_eq!(page.coverage().web(), super::WebCoverage::Complete);
        Ok(())
    }

    #[test]
    #[ignore = "requires the retained local HTTP-200 empty DDG DOM; no network I/O"]
    fn replay_retained_empty_dom_reports_empty() -> Result<(), Box<dyn Error>> {
        let path = std::env::var_os("YS_DDG_EMPTY_CAPTURE_PATH")
            .map(PathBuf::from)
            .ok_or_else(|| io::Error::other("YS_DDG_EMPTY_CAPTURE_PATH is required"))?;
        let bytes = fs::read(path)?;
        assert_eq!(
            format!("{:x}", Sha256::digest(&bytes)),
            "0f8051c4fad514aa55841fbd12c7e9a15f71ccb6c0c786e8e999b91c132e8b59"
        );
        let document = rendered_document("duckduckgo-retained-empty.json", bytes)?;
        assert!(matches!(
            parse(
                &document,
                &Policy::default(),
                PAGE_URL,
                RESULT_LIMIT,
                OUTPUT_LIMIT
            ),
            Ok(ProviderOutcome::Empty)
        ));
        println!("ddg_empty_replay=recognized sha256_verified=true");
        Ok(())
    }

    #[test]
    fn rejects_non_rendered_documents() -> Result<(), Box<dyn Error>> {
        let document = Document::html("duckduckgo-source.html", ROWS.as_bytes().to_vec())?;
        assert!(matches!(
            parse(
                &document,
                &Policy::default(),
                PAGE_URL,
                RESULT_LIMIT,
                OUTPUT_LIMIT
            ),
            Err(DuckDuckGoParseError::UnsupportedDocumentClass)
        ));
        Ok(())
    }
}
