use std::fmt::{self, Formatter};
use thiserror::Error;
use yosoi_contracts::{ContractSchemaError, FieldId};
use yosoi_documents::{Completeness, Finding};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ValidationCode {
    NegativeMoney,
}

#[derive(Clone)]
pub struct FieldIssue {
    pub field: FieldId,
    pub kind: FieldIssueKind,
    pub evidence: Vec<Finding>,
}

impl fmt::Debug for FieldIssue {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("FieldIssue")
            .field("field", &self.field)
            .field("kind", &self.kind)
            .field("evidence_count", &self.evidence.len())
            .finish()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FieldIssueKind {
    MissingRequired,
    ExcessCandidates { observed: u64 },
    IncompleteEvidence,
    UnsupportedProjectedValue,
    ConversionFailed,
    SemanticValidationFailed { code: ValidationCode },
}

#[doc(hidden)]
pub struct FieldIssueDraft<'a> {
    field: FieldId,
    kind: FieldIssueKind,
    evidence: IssueEvidence<'a>,
}

enum IssueEvidence<'a> {
    All(&'a [Finding]),
    One(&'a Finding),
    Incomplete(&'a [Finding]),
}

impl fmt::Debug for FieldIssueDraft<'_> {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("FieldIssueDraft")
            .field("field", &self.field)
            .field("kind", &self.kind)
            .field("evidence_count", &self.evidence_count().ok())
            .finish()
    }
}

impl<'a> FieldIssueDraft<'a> {
    pub(crate) const fn all(field: FieldId, kind: FieldIssueKind, evidence: &'a [Finding]) -> Self {
        Self {
            field,
            kind,
            evidence: IssueEvidence::All(evidence),
        }
    }

    pub(crate) const fn one(field: FieldId, kind: FieldIssueKind, evidence: &'a Finding) -> Self {
        Self {
            field,
            kind,
            evidence: IssueEvidence::One(evidence),
        }
    }

    pub(crate) const fn incomplete(field: FieldId, evidence: &'a [Finding]) -> Self {
        Self {
            field,
            kind: FieldIssueKind::IncompleteEvidence,
            evidence: IssueEvidence::Incomplete(evidence),
        }
    }

    pub(crate) fn evidence_count(&self) -> Result<u64, ValidationFailure> {
        match self.evidence {
            IssueEvidence::All(evidence) => u64::try_from(evidence.len())
                .map_err(|_| ValidationFailure::ProvenanceCountOverflow),
            IssueEvidence::One(_) => Ok(1),
            IssueEvidence::Incomplete(evidence) => evidence
                .iter()
                .filter(|finding| finding.completeness() != &Completeness::Complete)
                .try_fold(0_u64, |count, _| {
                    count
                        .checked_add(1)
                        .ok_or(ValidationFailure::ProvenanceCountOverflow)
                }),
        }
    }

    pub fn materialize(self) -> FieldIssue {
        let evidence = match self.evidence {
            IssueEvidence::All(evidence) => evidence.to_vec(),
            IssueEvidence::One(evidence) => vec![evidence.clone()],
            IssueEvidence::Incomplete(evidence) => evidence
                .iter()
                .filter(|finding| finding.completeness() != &Completeness::Complete)
                .cloned()
                .collect(),
        };
        FieldIssue {
            field: self.field,
            kind: self.kind,
            evidence,
        }
    }
}

#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum ValidationFailure {
    #[error(transparent)]
    InvalidContractSchema(#[from] ContractSchemaError),
    #[error("contract field count cannot be represented as u64")]
    FieldCountOverflow,
    #[error("contract field limit exceeded: maximum {maximum}, observed {observed}")]
    FieldLimitExceeded { maximum: u64, observed: u64 },
    #[error("candidate record count cannot be represented as u64")]
    RecordCountOverflow,
    #[error("candidate record limit exceeded: maximum {maximum}, observed {observed}")]
    RecordLimitExceeded { maximum: u64, observed: u64 },
    #[error("conversion count cannot be represented as u64")]
    ConversionCountOverflow,
    #[error("conversion limit exceeded: maximum {maximum}, observed {observed}")]
    ConversionLimitExceeded { maximum: u64, observed: u64 },
    #[error("validation issue count cannot be represented as u64")]
    IssueCountOverflow,
    #[error("validation issue limit exceeded: maximum {maximum}, observed {observed}")]
    IssueLimitExceeded { maximum: u64, observed: u64 },
    #[error("retained provenance count cannot be represented as u64")]
    ProvenanceCountOverflow,
    #[error("retained provenance limit exceeded: maximum {maximum}, observed {observed}")]
    ProvenanceLimitExceeded { maximum: u64, observed: u64 },
}

#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum ContractIssues {
    #[error(
        "contract evaluation rejected {record_issues} records and produced {extraction_diagnostics} extraction diagnostics"
    )]
    Rejected {
        record_issues: usize,
        extraction_diagnostics: usize,
    },
    #[error("contract evaluation is indeterminate")]
    Indeterminate,
    #[error("location failed before contract evaluation")]
    LocateFailed,
    #[error("extraction rejected the located input")]
    ExtractionRejected,
    #[error("validation rejected the extracted candidates")]
    ValidationRejected,
}
