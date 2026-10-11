use crate::internal::contract_validation::{ContractIssues, FieldIssue, ValidationFailure};
use crate::internal::contracts::Contract;
use crate::internal::documents::{DocumentId, IncompleteEvidence, LocateFailure};
use crate::internal::extractor::{ExtractionDiagnostic, ExtractionFailure};
use std::fmt::{self, Formatter};

/// Accepted typed record retaining its original extraction evidence.
pub struct ValidatedRecord<T: Contract> {
    /// Converted value that passed field cardinality, completeness, and semantic checks.
    pub value: T,
    /// Original candidate findings and grouping provenance.
    pub candidate: T::Candidate,
}

impl<T: Contract> fmt::Debug for ValidatedRecord<T> {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ValidatedRecord")
            .finish_non_exhaustive()
    }
}

/// Rejected candidate record with retained field-level explanations and evidence.
#[derive(Clone)]
pub struct RecordIssue<T: Contract> {
    /// Original candidate whose conversion or validation was rejected.
    pub candidate: T::Candidate,
    /// Field-specific rejection reasons with supporting findings.
    pub fields: Vec<FieldIssue>,
}

impl<T: Contract> fmt::Debug for RecordIssue<T> {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("RecordIssue")
            .field("field_issue_count", &self.fields.len())
            .finish_non_exhaustive()
    }
}

/// Typed evaluation preserving accepted records, rejected records, and terminal evidence states.
pub enum ContractOutcome<T: Contract> {
    /// Evaluation finished, possibly with field issues or nonfatal extraction diagnostics.
    Evaluated {
        /// Identity of the document providing candidate evidence.
        document_id: DocumentId,
        /// Accepted typed records with original candidate evidence.
        records: Vec<ValidatedRecord<T>>,
        /// Rejected candidates and field-level rejection explanations.
        issues: Vec<RecordIssue<T>>,
        /// Nonfatal extraction issues preventing an unqualified all-accepted claim.
        extraction_diagnostics: Vec<ExtractionDiagnostic>,
    },
    /// Complete locator evidence established no candidates within the requested scope.
    NoMatch {
        /// Document whose evidence supports this scope-specific absence claim.
        document_id: DocumentId,
    },
    /// Evidence coverage is insufficient to establish accepted records or complete absence.
    Indeterminate {
        /// Identity of the examined evidence document.
        document_id: DocumentId,
        /// Partial or unknown evidence coverage limiting the result.
        completeness: IncompleteEvidence,
        /// Structural explanation for the indeterminate outcome.
        reason_code: String,
    },
    /// Locator execution failed before candidate extraction and validation.
    LocateFailed {
        /// Typed locator failure, distinct from no-match evidence.
        failure: LocateFailure,
    },
    /// Candidate extraction failed schema or resource checks.
    ExtractionRejected {
        /// Typed candidate-assembly rejection rather than a per-field issue.
        failure: ExtractionFailure,
    },
    /// Schema or accounting budgets rejected validation as an operation.
    ValidationRejected {
        /// Typed validation rejection, without claiming partly processed records are accepted.
        failure: ValidationFailure,
    },
}

impl<T: Contract> ContractOutcome<T> {
    /// Consumes the outcome and returns values only when every candidate was accepted.
    ///
    /// Complete `NoMatch` returns an empty vector. Any record issue or extraction
    /// diagnostic returns [`ContractIssues::Rejected`]; indeterminate and failed
    /// phases retain their own error categories. Original candidate evidence is
    /// dropped on success; inspect the outcome first when that evidence is needed.
    pub fn require_all(self) -> Result<Vec<T>, ContractIssues> {
        match self {
            Self::Evaluated {
                records,
                issues,
                extraction_diagnostics,
                ..
            } if issues.is_empty() && extraction_diagnostics.is_empty() => {
                Ok(records.into_iter().map(|record| record.value).collect())
            }
            Self::Evaluated {
                issues,
                extraction_diagnostics,
                ..
            } => Err(ContractIssues::Rejected {
                record_issues: issues.len(),
                extraction_diagnostics: extraction_diagnostics.len(),
            }),
            Self::NoMatch { .. } => Ok(Vec::new()),
            Self::Indeterminate { .. } => Err(ContractIssues::Indeterminate),
            Self::LocateFailed { .. } => Err(ContractIssues::LocateFailed),
            Self::ExtractionRejected { .. } => Err(ContractIssues::ExtractionRejected),
            Self::ValidationRejected { .. } => Err(ContractIssues::ValidationRejected),
        }
    }
}

impl<T: Contract> fmt::Debug for ContractOutcome<T> {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        match self {
            Self::Evaluated {
                records,
                issues,
                extraction_diagnostics,
                ..
            } => formatter
                .debug_struct("ContractOutcome::Evaluated")
                .field("record_count", &records.len())
                .field("issue_count", &issues.len())
                .field("extraction_diagnostic_count", &extraction_diagnostics.len())
                .finish(),
            Self::NoMatch { .. } => formatter
                .debug_struct("ContractOutcome::NoMatch")
                .finish_non_exhaustive(),
            Self::Indeterminate { .. } => formatter
                .debug_struct("ContractOutcome::Indeterminate")
                .finish_non_exhaustive(),
            Self::LocateFailed { .. } => formatter
                .debug_struct("ContractOutcome::LocateFailed")
                .finish_non_exhaustive(),
            Self::ExtractionRejected { failure } => formatter
                .debug_tuple("ContractOutcome::ExtractionRejected")
                .field(failure)
                .finish(),
            Self::ValidationRejected { failure } => formatter
                .debug_tuple("ContractOutcome::ValidationRejected")
                .field(failure)
                .finish(),
        }
    }
}
