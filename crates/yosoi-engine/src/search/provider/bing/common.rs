use std::num::NonZeroU16;

use url::Url;

use crate::search::SearchIssue;

use super::super::row_contract::RowContractError;

use super::{BingParseError, MAX_PROVIDER_PAGE_URL_BYTES, PAGE_HOST, PAGE_PATH};

pub(super) fn has_user_information(url: &Url) -> bool {
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

pub(super) fn parse_page_url(value: &str) -> Result<Url, BingParseError> {
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

pub(super) const fn map_row_contract_error(error: RowContractError) -> BingParseError {
    match error {
        RowContractError::UnrecognizedPage => BingParseError::UnrecognizedPage,
        RowContractError::IncompleteDocument => BingParseError::IncompleteDocument,
        RowContractError::LocateFailed => BingParseError::LocateFailed,
        RowContractError::InvalidLocatorResult => BingParseError::InvalidLocatorResult,
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
