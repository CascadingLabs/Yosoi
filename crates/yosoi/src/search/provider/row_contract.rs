//! Shared Contract validation for provider-owned repeated result regions.

use std::collections::BTreeMap;

use crate::{CandidateView, Contract, ContractOutcome, FieldIssueKind};

use super::super::SearchIssueKind;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum RowContractError {
    UnrecognizedPage,
    IncompleteDocument,
    LocateFailed,
    InvalidLocatorResult,
}

pub(super) fn validated_rows<T: Contract>(
    outcome: ContractOutcome<T>,
    required_url_field: &str,
) -> Result<BTreeMap<u64, Result<T, SearchIssueKind>>, RowContractError> {
    let (records, issues, extraction_diagnostics) = match outcome {
        ContractOutcome::Evaluated {
            records,
            issues,
            extraction_diagnostics,
            ..
        } => (records, issues, extraction_diagnostics),
        ContractOutcome::NoMatch { .. } => return Err(RowContractError::UnrecognizedPage),
        ContractOutcome::Indeterminate { .. } => return Err(RowContractError::IncompleteDocument),
        ContractOutcome::LocateFailed { .. } => return Err(RowContractError::LocateFailed),
        ContractOutcome::ExtractionRejected { .. } | ContractOutcome::ValidationRejected { .. } => {
            return Err(RowContractError::InvalidLocatorResult);
        }
    };
    if !extraction_diagnostics.is_empty() {
        return Err(RowContractError::InvalidLocatorResult);
    }

    let mut rows = BTreeMap::new();
    for record in records {
        let ordinal = record
            .candidate
            .region()
            .ok_or(RowContractError::InvalidLocatorResult)?
            .region_ordinal();
        if rows.insert(ordinal, Ok(record.value)).is_some() {
            return Err(RowContractError::InvalidLocatorResult);
        }
    }
    for issue in issues {
        let ordinal = issue
            .candidate
            .region()
            .ok_or(RowContractError::InvalidLocatorResult)?
            .region_ordinal();
        let kind = if issue.fields.iter().any(|field| {
            field.field.as_str() == required_url_field
                && matches!(field.kind, FieldIssueKind::MissingRequired)
        }) {
            SearchIssueKind::MissingRequiredField
        } else {
            SearchIssueKind::UnrecognizedResultRow
        };
        if rows.insert(ordinal, Err(kind)).is_some() {
            return Err(RowContractError::InvalidLocatorResult);
        }
    }
    if rows.is_empty() {
        return Err(RowContractError::UnrecognizedPage);
    }
    Ok(rows)
}
