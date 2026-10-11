use crate::internal::contract_validation::{ContractIssues, FieldIssue, ValidationFailure};
use crate::internal::contracts::Contract;
use crate::internal::documents::{DocumentId, IncompleteEvidence, LocateFailure};
use crate::internal::extractor::{ExtractionDiagnostic, ExtractionFailure};
use std::fmt::{self, Formatter};

pub struct ValidatedRecord<T: Contract> {
    pub value: T,
    pub candidate: T::Candidate,
}

impl<T: Contract> fmt::Debug for ValidatedRecord<T> {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ValidatedRecord")
            .finish_non_exhaustive()
    }
}

#[derive(Clone)]
pub struct RecordIssue<T: Contract> {
    pub candidate: T::Candidate,
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

pub enum ContractOutcome<T: Contract> {
    Evaluated {
        document_id: DocumentId,
        records: Vec<ValidatedRecord<T>>,
        issues: Vec<RecordIssue<T>>,
        extraction_diagnostics: Vec<ExtractionDiagnostic>,
    },
    NoMatch {
        document_id: DocumentId,
    },
    Indeterminate {
        document_id: DocumentId,
        completeness: IncompleteEvidence,
        reason_code: String,
    },
    LocateFailed {
        failure: LocateFailure,
    },
    ExtractionRejected {
        failure: ExtractionFailure,
    },
    ValidationRejected {
        failure: ValidationFailure,
    },
}

impl<T: Contract> ContractOutcome<T> {
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
