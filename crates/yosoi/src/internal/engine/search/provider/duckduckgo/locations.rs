use crate::internal::documents::{LocateOutcome, Plan, ProjectedValue, css, output};

use crate::internal::engine::{Document, Policy};

use super::{
    DuckDuckGoParseError, EMPTY_MESSAGE_MARKER, EMPTY_MESSAGE_SELECTOR, REGION_ID, ROW_KIND_OUTPUT,
    ROW_SECTION_OUTPUT, ROW_SECTION_SELECTOR, ROW_SELECTOR, TITLE_LINK_SELECTOR, TITLE_OUTPUT,
    URL_OUTPUT,
};

pub(super) fn is_recognized_empty_page(
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

pub(super) fn page_contains_marker(
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

pub(super) fn result_plan() -> Result<Plan, DuckDuckGoParseError> {
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
