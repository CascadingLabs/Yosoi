use crate::{
    FieldIssueDraft, FieldIssueKind, RuntimeContractValue, RuntimeValueIssue, ValidationFailure,
};
use std::fmt::{self, Formatter};
use yosoi_contracts::{CandidateField, CandidateView, Contract};
use yosoi_documents::{Completeness, Finding};

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
        let field_count = u64::try_from(schema.fields().len())
            .map_err(|_| ValidationFailure::FieldCountOverflow)?;
        enforce(field_count, limits.max_fields, |maximum, observed| {
            ValidationFailure::FieldLimitExceeded { maximum, observed }
        })?;
        let record_count =
            u64::try_from(candidates.len()).map_err(|_| ValidationFailure::RecordCountOverflow)?;
        enforce(record_count, limits.max_records, |maximum, observed| {
            ValidationFailure::RecordLimitExceeded { maximum, observed }
        })?;
        let total_values = candidates.iter().try_fold(0_u64, |total, candidate| {
            total.checked_add(<T::Candidate as CandidateView>::value_count(candidate)?)
        });
        let total_values = total_values.ok_or(ValidationFailure::ConversionCountOverflow)?;
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
    validate_completeness(field)?;
    match field.evidence() {
        [] => Err(issue_all(field, FieldIssueKind::MissingRequired)),
        [finding] => convert(field, finding),
        findings => Err(issue_all(
            field,
            FieldIssueKind::ExcessCandidates {
                observed: u64::try_from(findings.len()).unwrap_or(u64::MAX),
            },
        )),
    }
}

#[doc(hidden)]
pub fn read_optional<T: RuntimeContractValue>(
    field: &CandidateField<T>,
) -> Result<Option<T>, FieldIssueDraft<'_>> {
    validate_completeness(field)?;
    match field.evidence() {
        [] => Ok(None),
        [finding] => convert(field, finding).map(Some),
        findings => Err(issue_all(
            field,
            FieldIssueKind::ExcessCandidates {
                observed: u64::try_from(findings.len()).unwrap_or(u64::MAX),
            },
        )),
    }
}

#[doc(hidden)]
pub fn read_many<T: RuntimeContractValue>(
    field: &CandidateField<T>,
) -> Result<Vec<T>, FieldIssueDraft<'_>> {
    validate_completeness(field)?;
    let mut values = Vec::with_capacity(field.len());
    for finding in field.evidence() {
        values.push(convert(field, finding)?);
    }
    Ok(values)
}

fn validate_completeness<T>(field: &CandidateField<T>) -> Result<(), FieldIssueDraft<'_>> {
    if field
        .evidence()
        .iter()
        .all(|finding| finding.completeness() == &Completeness::Complete)
    {
        Ok(())
    } else {
        Err(FieldIssueDraft::incomplete(
            field.id().clone(),
            field.evidence(),
        ))
    }
}

fn convert<'a, T: RuntimeContractValue>(
    field: &CandidateField<T>,
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
        FieldIssueDraft::one(field.id().clone(), kind, finding)
    })
}

fn issue_all<T>(field: &CandidateField<T>, kind: FieldIssueKind) -> FieldIssueDraft<'_> {
    FieldIssueDraft::all(field.id().clone(), kind, field.evidence())
}
