use super::super::{
    PortableExtractionDiagnostic, PortableExtractionFailure, PortableExtractionLimit,
    PortableFieldIssue, PortableFieldIssueKind, PortableValidationCode, PortableValidationFailure,
};
use crate::internal::contract_validation::{
    FieldIssue, FieldIssueKind, ValidationCode, ValidationFailure,
};
use crate::internal::extractor::{ExtractionDiagnostic, ExtractionFailure, ExtractionLimit};
pub(super) fn portable_field_issue(issue: &FieldIssue) -> PortableFieldIssue {
    PortableFieldIssue::new(
        issue.field.clone(),
        match issue.kind {
            FieldIssueKind::MissingRequired => PortableFieldIssueKind::MissingRequired,
            FieldIssueKind::ExcessCandidates { observed } => {
                PortableFieldIssueKind::ExcessCandidates { observed }
            }
            FieldIssueKind::IncompleteEvidence => PortableFieldIssueKind::IncompleteEvidence,
            FieldIssueKind::UnsupportedProjectedValue => {
                PortableFieldIssueKind::UnsupportedProjectedValue
            }
            FieldIssueKind::ConversionFailed => PortableFieldIssueKind::ConversionFailed,
            FieldIssueKind::SemanticValidationFailed { code } => {
                PortableFieldIssueKind::SemanticValidationFailed {
                    code: match code {
                        ValidationCode::NegativeMoney => PortableValidationCode::NegativeMoney,
                    },
                }
            }
        },
        issue.evidence.clone(),
    )
}

pub(super) fn portable_extraction_diagnostic(
    diagnostic: &ExtractionDiagnostic,
) -> PortableExtractionDiagnostic {
    match diagnostic {
        ExtractionDiagnostic::IncompatibleLineage { output } => {
            PortableExtractionDiagnostic::IncompatibleLineage {
                output: output.clone(),
            }
        }
    }
}

pub(super) const fn portable_extraction_failure(
    failure: &ExtractionFailure,
) -> PortableExtractionFailure {
    match failure {
        ExtractionFailure::InvalidContractSchema(_) => {
            PortableExtractionFailure::InvalidContractSchema
        }
        ExtractionFailure::CountOverflow { limit } => PortableExtractionFailure::CountOverflow {
            limit: portable_extraction_limit(*limit),
        },
        ExtractionFailure::GroupingIndexInvariant => {
            PortableExtractionFailure::GroupingIndexInvariant
        }
        ExtractionFailure::LimitExceeded {
            limit,
            maximum,
            observed,
        } => PortableExtractionFailure::LimitExceeded {
            limit: portable_extraction_limit(*limit),
            maximum: *maximum,
            observed: *observed,
        },
    }
}

pub(super) const fn portable_extraction_limit(limit: ExtractionLimit) -> PortableExtractionLimit {
    match limit {
        ExtractionLimit::ScannedRegions => PortableExtractionLimit::ScannedRegions,
        ExtractionLimit::ScannedFindings => PortableExtractionLimit::ScannedFindings,
        ExtractionLimit::MatchingFindings => PortableExtractionLimit::MatchingFindings,
        ExtractionLimit::Candidates => PortableExtractionLimit::Candidates,
        ExtractionLimit::ValuesPerField => PortableExtractionLimit::ValuesPerField,
        ExtractionLimit::RetainedEvidence => PortableExtractionLimit::RetainedEvidence,
        ExtractionLimit::Diagnostics => PortableExtractionLimit::Diagnostics,
    }
}

pub(super) const fn portable_validation_failure(
    failure: &ValidationFailure,
) -> PortableValidationFailure {
    match failure {
        ValidationFailure::InvalidContractSchema(_) => {
            PortableValidationFailure::InvalidContractSchema
        }
        ValidationFailure::FieldCountOverflow => PortableValidationFailure::FieldCountOverflow,
        ValidationFailure::FieldLimitExceeded { maximum, observed } => {
            PortableValidationFailure::FieldLimitExceeded {
                maximum: *maximum,
                observed: *observed,
            }
        }
        ValidationFailure::RecordCountOverflow => PortableValidationFailure::RecordCountOverflow,
        ValidationFailure::RecordLimitExceeded { maximum, observed } => {
            PortableValidationFailure::RecordLimitExceeded {
                maximum: *maximum,
                observed: *observed,
            }
        }
        ValidationFailure::ConversionCountOverflow => {
            PortableValidationFailure::ConversionCountOverflow
        }
        ValidationFailure::ConversionLimitExceeded { maximum, observed } => {
            PortableValidationFailure::ConversionLimitExceeded {
                maximum: *maximum,
                observed: *observed,
            }
        }
        ValidationFailure::IssueCountOverflow => PortableValidationFailure::IssueCountOverflow,
        ValidationFailure::IssueLimitExceeded { maximum, observed } => {
            PortableValidationFailure::IssueLimitExceeded {
                maximum: *maximum,
                observed: *observed,
            }
        }
        ValidationFailure::ProvenanceCountOverflow => {
            PortableValidationFailure::ProvenanceCountOverflow
        }
        ValidationFailure::ProvenanceLimitExceeded { maximum, observed } => {
            PortableValidationFailure::ProvenanceLimitExceeded {
                maximum: *maximum,
                observed: *observed,
            }
        }
    }
}
