use std::num::NonZeroU16;

use url::Url;

use crate::search::SearchIssue;

use super::super::row_contract::RowContractError;
use super::{DuckDuckGoParseError, MAX_PROVIDER_PAGE_URL_BYTES, PAGE_HOST, PAGE_PATH};

pub(super) fn parse_page_url(value: &str) -> Result<Url, DuckDuckGoParseError> {
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

pub(super) fn is_duckduckgo_host(host: Option<&str>) -> bool {
    host.is_some_and(|value| value == PAGE_HOST || value.ends_with(".duckduckgo.com"))
}

pub(super) const fn map_row_contract_error(error: RowContractError) -> DuckDuckGoParseError {
    match error {
        RowContractError::UnrecognizedPage => DuckDuckGoParseError::UnrecognizedPage,
        RowContractError::IncompleteDocument => DuckDuckGoParseError::IncompleteDocument,
        RowContractError::LocateFailed => DuckDuckGoParseError::LocateFailed,
        RowContractError::InvalidLocatorResult => DuckDuckGoParseError::InvalidLocatorResult,
    }
}

pub(super) fn nonzero_index(ordinal: u64) -> Option<NonZeroU16> {
    let value = u16::try_from(ordinal).ok()?;
    NonZeroU16::new(value)
}

pub(super) fn nonempty_text(value: &str) -> Option<&str> {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed)
    }
}

pub(super) fn record_issue(
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
