//! Describe typed records and inspect extraction and validation outcomes.

use serde::Serialize;

pub use crate::internal::engine::{
    CandidateField, CandidateInput, CandidateView, Cardinality, Contract, ContractId,
    ContractIdentity, ContractLocatorError, ContractOutcome, ContractSchema, ContractSchemaError,
    ContractValue, Currency, Extracted, ExtractionDiagnostic, ExtractionFailure, ExtractionLimit,
    ExtractionLimits, FieldId, FieldIssue, FieldIssueKind, FieldSchema, Money, RecordIssue,
    RecordScope, ValidateContract, ValidatedRecord, ValidationCode, ValidationFailure,
    ValidationLimits,
};

pub use crate::internal::contract_validation::archived::ContractOutcome as ArchivedContractOutcome;
pub use crate::internal::contract_validation::{
    RuntimeContractArchiveError, RuntimeContractError, RuntimeContractOutcome, RuntimeExtracted,
    RuntimeFieldValue, RuntimeRecordIssue, RuntimeValidatedRecord, RuntimeValue,
};
pub use crate::internal::contracts::RuntimeCandidate;

/// Runtime-authored Contract adapter with the same default Policy-derived
/// extraction limits as a derive-backed Contract.
#[derive(Clone, Debug, Serialize)]
#[serde(transparent)]
pub struct RuntimeContract {
    inner: crate::internal::contract_validation::RuntimeContract,
}

impl RuntimeContract {
    pub fn new(schema: ContractSchema) -> Result<Self, RuntimeContractError> {
        Ok(Self {
            inner: crate::internal::contract_validation::RuntimeContract::new(schema)?,
        })
    }

    pub const fn schema(&self) -> &ContractSchema {
        self.inner.schema()
    }

    /// Extracts with the same default limits as `MyContract::extract`.
    pub fn extract(&self, located: &crate::internal::documents::LocateOutcome) -> RuntimeExtracted {
        self.extract_with_limits(located, default_extraction_limits())
    }

    /// Extracts with caller-supplied budgets using the same implementation as
    /// static Contracts.
    pub fn extract_with_limits(
        &self,
        located: &crate::internal::documents::LocateOutcome,
        limits: ExtractionLimits,
    ) -> RuntimeExtracted {
        self.inner.extract(located, limits)
    }
}

fn default_extraction_limits() -> ExtractionLimits {
    let policy = crate::internal::engine::Policy::default();
    let max_matches = policy.locators.max_matches.get();
    let max_regions = u64::from(policy.locators.max_regions.get());
    ExtractionLimits {
        max_scanned_regions: max_matches,
        max_scanned_findings: max_matches,
        max_matching_findings: max_matches,
        max_candidates: max_regions,
        max_values_per_field: max_matches,
        max_retained_evidence: max_matches,
        max_diagnostics: max_matches,
    }
}
