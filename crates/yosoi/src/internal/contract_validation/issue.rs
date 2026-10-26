use crate::internal::contracts::{ContractSchemaError, FieldId};
use crate::internal::documents::{Completeness, Finding};
use serde::{Deserialize, Serialize};
use std::fmt::{self, Formatter};
use thiserror::Error;

/// Field-level rejection with retained locator evidence for caller inspection.
#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FieldIssue {
    /// Authored Contract field whose value was rejected.
    pub field: FieldId,
    /// Whether cardinality, evidence completeness, or conversion rejected the field.
    pub kind: FieldIssueKind,
    /// Owned findings supporting the issue; these can contain source-derived values.
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

/// Field rejection category, separate from operation-level validation-budget failures.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum FieldIssueKind {
    /// An exactly-one field has no candidate value in the available evidence.
    MissingRequired,
    /// An exactly-one or zero-or-one field has more values than its cardinality permits.
    ExcessCandidates {
        /// Number of candidate findings for the field.
        observed: u64,
    },
    /// Candidate findings contain partial or unknown evidence that cannot satisfy validation.
    IncompleteEvidence,
    /// A finding's projection variant cannot be converted to the requested field type.
    UnsupportedProjectedValue,
    /// A supported projection could not be parsed into the requested field type.
    ConversionFailed,
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
    pub(in crate::internal::contract_validation) const fn all(
        field: FieldId,
        kind: FieldIssueKind,
        evidence: &'a [Finding],
    ) -> Self {
        Self {
            field,
            kind,
            evidence: IssueEvidence::All(evidence),
        }
    }

    pub(in crate::internal::contract_validation) const fn one(
        field: FieldId,
        kind: FieldIssueKind,
        evidence: &'a Finding,
    ) -> Self {
        Self {
            field,
            kind,
            evidence: IssueEvidence::One(evidence),
        }
    }

    pub(in crate::internal::contract_validation) const fn incomplete(
        field: FieldId,
        evidence: &'a [Finding],
    ) -> Self {
        Self {
            field,
            kind: FieldIssueKind::IncompleteEvidence,
            evidence: IssueEvidence::Incomplete(evidence),
        }
    }

    pub(in crate::internal::contract_validation) fn evidence_count(
        &self,
    ) -> Result<u64, ValidationFailure> {
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

/// Schema or resource failure rejecting validation as an operation.
///
/// These failures are not ordinary per-record field issues. Callers must not
/// treat a validation-rejected outcome as an accepted partial record collection.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum ValidationFailure {
    /// Contract schema validation failed before candidate conversion could proceed.
    #[error(transparent)]
    InvalidContractSchema(#[from] ContractSchemaError),
    /// The Contract field count does not fit the validation accounting representation.
    #[error("contract field count cannot be represented as u64")]
    FieldCountOverflow,
    /// Contract fields exceed the configured validation field budget.
    #[error("contract field limit exceeded: maximum {maximum}, observed {observed}")]
    FieldLimitExceeded {
        /// Maximum permitted Contract fields.
        maximum: u64,
        /// Number of Contract fields requiring validation.
        observed: u64,
    },
    /// Candidate record count does not fit validation accounting.
    #[error("candidate record count cannot be represented as u64")]
    RecordCountOverflow,
    /// Candidate records exceed the configured validation record budget.
    #[error("candidate record limit exceeded: maximum {maximum}, observed {observed}")]
    RecordLimitExceeded {
        /// Maximum permitted candidate records.
        maximum: u64,
        /// Candidate records requiring validation.
        observed: u64,
    },
    /// Required field-conversion count does not fit validation accounting.
    #[error("conversion count cannot be represented as u64")]
    ConversionCountOverflow,
    /// Required field conversions exceed the configured budget.
    #[error("conversion limit exceeded: maximum {maximum}, observed {observed}")]
    ConversionLimitExceeded {
        /// Maximum permitted field conversions.
        maximum: u64,
        /// Field conversions charged to the validation budget.
        observed: u64,
    },
    /// Generated field-issue count does not fit validation accounting.
    #[error("validation issue count cannot be represented as u64")]
    IssueCountOverflow,
    /// Generated validation issues exceed their retention budget.
    #[error("validation issue limit exceeded: maximum {maximum}, observed {observed}")]
    IssueLimitExceeded {
        /// Maximum permitted retained field issues.
        maximum: u64,
        /// Field issues requiring retention.
        observed: u64,
    },
    /// Retained finding-provenance count does not fit validation accounting.
    #[error("retained provenance count cannot be represented as u64")]
    ProvenanceCountOverflow,
    /// Findings retained for validation provenance exceed their budget.
    #[error("retained provenance limit exceeded: maximum {maximum}, observed {observed}")]
    ProvenanceLimitExceeded {
        /// Maximum permitted retained finding evidence references.
        maximum: u64,
        /// Finding evidence references requiring retention.
        observed: u64,
    },
}

impl Serialize for ValidationFailure {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        use serde::ser::SerializeStruct;
        let mut state = serializer.serialize_struct("ValidationFailure", 3)?;
        match self {
            Self::InvalidContractSchema(error) => {
                state.serialize_field("kind", "invalid_contract_schema")?;
                state.serialize_field("message", &error.to_string())?;
            }
            Self::FieldCountOverflow => state.serialize_field("kind", "field_count_overflow")?,
            Self::FieldLimitExceeded { maximum, observed } => {
                state.serialize_field("kind", "field_limit_exceeded")?;
                state.serialize_field("maximum", maximum)?;
                state.serialize_field("observed", observed)?;
            }
            Self::RecordCountOverflow => state.serialize_field("kind", "record_count_overflow")?,
            Self::RecordLimitExceeded { maximum, observed } => {
                state.serialize_field("kind", "record_limit_exceeded")?;
                state.serialize_field("maximum", maximum)?;
                state.serialize_field("observed", observed)?;
            }
            Self::ConversionCountOverflow => {
                state.serialize_field("kind", "conversion_count_overflow")?;
            }
            Self::ConversionLimitExceeded { maximum, observed } => {
                state.serialize_field("kind", "conversion_limit_exceeded")?;
                state.serialize_field("maximum", maximum)?;
                state.serialize_field("observed", observed)?;
            }
            Self::IssueCountOverflow => state.serialize_field("kind", "issue_count_overflow")?,
            Self::IssueLimitExceeded { maximum, observed } => {
                state.serialize_field("kind", "issue_limit_exceeded")?;
                state.serialize_field("maximum", maximum)?;
                state.serialize_field("observed", observed)?;
            }
            Self::ProvenanceCountOverflow => {
                state.serialize_field("kind", "provenance_count_overflow")?;
            }
            Self::ProvenanceLimitExceeded { maximum, observed } => {
                state.serialize_field("kind", "provenance_limit_exceeded")?;
                state.serialize_field("maximum", maximum)?;
                state.serialize_field("observed", observed)?;
            }
        }
        state.end()
    }
}

/// Reason an outcome cannot be converted into an all-accepted record collection.
#[derive(Clone, Debug, Deserialize, Eq, Error, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ContractIssues {
    /// Evaluation produced rejected records or nonfatal extraction diagnostics.
    #[error(
        "contract evaluation rejected {record_issues} records and produced {extraction_diagnostics} extraction diagnostics"
    )]
    Rejected {
        /// Number of rejected candidate records, not the number of individual field issues.
        record_issues: usize,
        /// Number of retained grouping or extraction diagnostics.
        extraction_diagnostics: usize,
    },
    /// Incomplete evidence prevents an all-accepted or complete-absence claim.
    #[error("contract evaluation is indeterminate")]
    Indeterminate,
    /// Locator execution failed before Contract evaluation could begin.
    #[error("location failed before contract evaluation")]
    LocateFailed,
    /// Candidate extraction was rejected by schema or resource checks.
    #[error("extraction rejected the located input")]
    ExtractionRejected,
    /// Conversion or provenance budgets rejected the validation operation.
    #[error("validation rejected the extracted candidates")]
    ValidationRejected,
}
