use crate::internal::contract_validation::{
    FieldIssueDraft, FieldIssueKind, RuntimeContractValue, RuntimeValueIssue, ValidationFailure,
};
use crate::internal::contracts::{
    CandidateField, CandidateInput, CandidateView, Contract, ContractSchema, FieldId,
};
use crate::internal::documents::{Completeness, Finding};
use std::fmt::{self, Formatter};

pub const MAX_CONTRACT_FIELDS: u64 = 1_024;
pub const MAX_VALIDATED_RECORDS: u64 = 100_000;

#[doc(hidden)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ValidationLimits {
    pub max_fields: u64,
    pub max_records: u64,
    pub max_conversions: u64,
    pub max_issues: u64,
    pub max_retained_provenance: u64,
}

impl Default for ValidationLimits {
    fn default() -> Self {
        Self {
            max_fields: MAX_CONTRACT_FIELDS,
            max_records: MAX_VALIDATED_RECORDS,
            max_conversions: MAX_VALIDATED_RECORDS,
            max_issues: MAX_VALIDATED_RECORDS,
            max_retained_provenance: MAX_VALIDATED_RECORDS,
        }
    }
}

#[doc(hidden)]
pub struct ValidationBudget {
    limits: ValidationLimits,
    total_values: u64,
    issue_count: u64,
    retained_issue_evidence: u64,
}

impl fmt::Debug for ValidationBudget {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ValidationBudget")
            .field("limits", &self.limits)
            .field("total_values", &self.total_values)
            .field("issue_count", &self.issue_count)
            .field("retained_issue_evidence", &self.retained_issue_evidence)
            .finish()
    }
}

impl ValidationBudget {
    pub fn preflight<T: Contract>(
        candidates: &[T::Candidate],
        limits: ValidationLimits,
    ) -> Result<Self, ValidationFailure> {
        let schema = T::schema()?;
        let total_values = candidates.iter().try_fold(0_u64, |total, candidate| {
            total.checked_add(<T::Candidate as CandidateView>::value_count(candidate)?)
        });
        let total_values = total_values.ok_or(ValidationFailure::ConversionCountOverflow)?;
        Self::preflight_counts(schema, candidates.len(), total_values, limits)
    }

    pub(in crate::internal::contract_validation) fn preflight_runtime(
        schema: &ContractSchema,
        candidates: &[CandidateInput],
        limits: ValidationLimits,
    ) -> Result<Self, ValidationFailure> {
        let total_values = candidates.iter().try_fold(0_u64, |total, candidate| {
            candidate
                .fields()
                .values()
                .try_fold(total, |count, findings| {
                    let evidence_count = u64::try_from(findings.len()).ok()?;
                    count.checked_add(evidence_count)
                })
        });
        let total_values = total_values.ok_or(ValidationFailure::ConversionCountOverflow)?;
        Self::preflight_counts(schema, candidates.len(), total_values, limits)
    }

    fn preflight_counts(
        schema: &ContractSchema,
        candidate_count: usize,
        total_values: u64,
        limits: ValidationLimits,
    ) -> Result<Self, ValidationFailure> {
        let field_count = u64::try_from(schema.fields().len())
            .map_err(|_| ValidationFailure::FieldCountOverflow)?;
        enforce(field_count, limits.max_fields, |maximum, observed| {
            ValidationFailure::FieldLimitExceeded { maximum, observed }
        })?;
        let record_count =
            u64::try_from(candidate_count).map_err(|_| ValidationFailure::RecordCountOverflow)?;
        enforce(record_count, limits.max_records, |maximum, observed| {
            ValidationFailure::RecordLimitExceeded { maximum, observed }
        })?;
        enforce(total_values, limits.max_conversions, |maximum, observed| {
            ValidationFailure::ConversionLimitExceeded { maximum, observed }
        })?;
        enforce(
            total_values,
            limits.max_retained_provenance,
            |maximum, observed| ValidationFailure::ProvenanceLimitExceeded { maximum, observed },
        )?;
        Ok(Self {
            limits,
            total_values,
            issue_count: 0,
            retained_issue_evidence: 0,
        })
    }

    pub fn record_issue_drafts(
        &mut self,
        fields: &[FieldIssueDraft<'_>],
    ) -> Result<(), ValidationFailure> {
        let candidate_issues =
            u64::try_from(fields.len()).map_err(|_| ValidationFailure::IssueCountOverflow)?;
        let observed_issues = self
            .issue_count
            .checked_add(candidate_issues)
            .ok_or(ValidationFailure::IssueCountOverflow)?;
        enforce(
            observed_issues,
            self.limits.max_issues,
            |maximum, observed| ValidationFailure::IssueLimitExceeded { maximum, observed },
        )?;
        let candidate_evidence = fields.iter().try_fold(0_u64, |total, issue| {
            total
                .checked_add(issue.evidence_count()?)
                .ok_or(ValidationFailure::ProvenanceCountOverflow)
        })?;
        let observed_evidence = self
            .retained_issue_evidence
            .checked_add(candidate_evidence)
            .ok_or(ValidationFailure::ProvenanceCountOverflow)?;
        let total_retained = self
            .total_values
            .checked_add(observed_evidence)
            .ok_or(ValidationFailure::ProvenanceCountOverflow)?;
        enforce(
            total_retained,
            self.limits.max_retained_provenance,
            |maximum, observed| ValidationFailure::ProvenanceLimitExceeded { maximum, observed },
        )?;
        self.issue_count = observed_issues;
        self.retained_issue_evidence = observed_evidence;
        Ok(())
    }
}

fn enforce(
    observed: u64,
    maximum: u64,
    failure: impl FnOnce(u64, u64) -> ValidationFailure,
) -> Result<(), ValidationFailure> {
    if observed > maximum {
        Err(failure(maximum, observed))
    } else {
        Ok(())
    }
}

#[doc(hidden)]
pub fn read_required<T: RuntimeContractValue>(
    field: &CandidateField<T>,
) -> Result<T, FieldIssueDraft<'_>> {
    read_required_evidence(field.id(), field.evidence())
}

pub fn read_required_evidence<'a, T: RuntimeContractValue>(
    id: &FieldId,
    evidence: &'a [Finding],
) -> Result<T, FieldIssueDraft<'a>> {
    validate_completeness(id, evidence)?;
    match evidence {
        [] => Err(FieldIssueDraft::all(
            id.clone(),
            FieldIssueKind::MissingRequired,
            evidence,
        )),
        [finding] => convert(id, finding),
        findings => Err(FieldIssueDraft::all(
            id.clone(),
            FieldIssueKind::ExcessCandidates {
                observed: u64::try_from(findings.len()).unwrap_or(u64::MAX),
            },
            findings,
        )),
    }
}

#[doc(hidden)]
pub fn read_optional<T: RuntimeContractValue>(
    field: &CandidateField<T>,
) -> Result<Option<T>, FieldIssueDraft<'_>> {
    read_optional_evidence(field.id(), field.evidence())
}

pub fn read_optional_evidence<'a, T: RuntimeContractValue>(
    id: &FieldId,
    evidence: &'a [Finding],
) -> Result<Option<T>, FieldIssueDraft<'a>> {
    validate_completeness(id, evidence)?;
    match evidence {
        [] => Ok(None),
        [finding] => convert(id, finding).map(Some),
        findings => Err(FieldIssueDraft::all(
            id.clone(),
            FieldIssueKind::ExcessCandidates {
                observed: u64::try_from(findings.len()).unwrap_or(u64::MAX),
            },
            findings,
        )),
    }
}

#[doc(hidden)]
pub fn read_many<T: RuntimeContractValue>(
    field: &CandidateField<T>,
) -> Result<Vec<T>, FieldIssueDraft<'_>> {
    read_many_evidence(field.id(), field.evidence())
}

pub fn read_many_evidence<'a, T: RuntimeContractValue>(
    id: &FieldId,
    evidence: &'a [Finding],
) -> Result<Vec<T>, FieldIssueDraft<'a>> {
    validate_completeness(id, evidence)?;
    let mut values = Vec::with_capacity(evidence.len());
    for finding in evidence {
        values.push(convert(id, finding)?);
    }
    Ok(values)
}

fn validate_completeness<'a>(
    id: &FieldId,
    evidence: &'a [Finding],
) -> Result<(), FieldIssueDraft<'a>> {
    if evidence
        .iter()
        .all(|finding| finding.completeness() == &Completeness::Complete)
    {
        Ok(())
    } else {
        Err(FieldIssueDraft::incomplete(id.clone(), evidence))
    }
}

fn convert<'a, T: RuntimeContractValue>(
    id: &FieldId,
    finding: &'a Finding,
) -> Result<T, FieldIssueDraft<'a>> {
    T::from_projected(finding.value()).map_err(|runtime_issue| {
        let kind = match runtime_issue {
            RuntimeValueIssue::UnsupportedProjectedValue => {
                FieldIssueKind::UnsupportedProjectedValue
            }
            RuntimeValueIssue::ConversionFailed => FieldIssueKind::ConversionFailed,
            RuntimeValueIssue::SemanticValidationFailed { code } => {
                FieldIssueKind::SemanticValidationFailed { code }
            }
        };
        FieldIssueDraft::one(id.clone(), kind, finding)
    })
}
