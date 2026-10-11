//! Runtime-described Contracts over the same extraction and validation rules
//! used by derive-backed Rust types.

use crate::internal::documents as yosoi_documents;

use crate::internal::contract_validation::validation::{
    read_many_evidence, read_optional_evidence, read_required_evidence,
};
use crate::internal::contract_validation::{
    ContractIssues, FieldIssue, FieldIssueDraft, FieldIssueKind, Money, RuntimeContractValue,
    ValidationBudget, ValidationFailure, ValidationLimits,
};
use crate::internal::contracts::{
    CandidateInput, Cardinality, ContractSchema, ContractValue, FieldId, FieldSchema,
};
use crate::internal::documents::{DocumentId, IncompleteEvidence, LocateFailure, LocateOutcome};
use crate::internal::extractor::{
    ExtractionDiagnostic, ExtractionFailure, ExtractionLimits, SchemaExtracted,
    extract_schema_with_limits,
};
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeMap,
    fmt::{self, Debug, Formatter},
};
use thiserror::Error;

/// A validated runtime Contract schema.
#[derive(Clone, Debug, Serialize)]
#[serde(transparent)]
pub struct RuntimeContract {
    schema: ContractSchema,
}

impl RuntimeContract {
    /// Creates a runtime Contract for the supported scalar vocabulary.
    pub fn new(schema: ContractSchema) -> Result<Self, RuntimeContractError> {
        for field in schema.fields() {
            if !matches!(field.value_type(), "string" | "money.usd") {
                return Err(RuntimeContractError::UnsupportedValueType {
                    field: field.id().clone(),
                    value_type: field.value_type().to_owned(),
                });
            }
        }
        Ok(Self { schema })
    }

    pub const fn schema(&self) -> &ContractSchema {
        &self.schema
    }

    /// Extracts with explicit limits using the shared schema-driven grouping
    /// path used by static Contracts.
    pub fn extract(&self, located: &LocateOutcome, limits: ExtractionLimits) -> RuntimeExtracted {
        RuntimeExtracted {
            schema: self.schema.clone(),
            extracted: extract_schema_with_limits(&self.schema, located, limits),
        }
    }
}

#[derive(Clone, Debug, Error, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum RuntimeContractError {
    #[error("runtime Contract field {field} has unsupported value type {value_type}")]
    UnsupportedValueType { field: FieldId, value_type: String },
}

/// Runtime candidate extraction awaiting explicit validation.
#[derive(Clone)]
pub struct RuntimeExtracted {
    schema: ContractSchema,
    extracted: SchemaExtracted,
}

impl Debug for RuntimeExtracted {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("RuntimeExtracted")
            .field("extracted", &self.extracted)
            .finish_non_exhaustive()
    }
}

impl Serialize for RuntimeExtracted {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        self.extracted.serialize(serializer)
    }
}

impl RuntimeExtracted {
    pub fn candidates(&self) -> &[CandidateInput] {
        match &self.extracted {
            SchemaExtracted::Candidates { candidates, .. } => candidates,
            _ => &[],
        }
    }

    pub fn diagnostics(&self) -> &[ExtractionDiagnostic] {
        match &self.extracted {
            SchemaExtracted::Candidates { diagnostics, .. } => diagnostics,
            _ => &[],
        }
    }

    /// Validates using the same default validation budget as generated
    /// `Extracted<T>::validate()`.
    pub fn validate(self) -> RuntimeContractOutcome {
        self.validate_with_limits(ValidationLimits::default())
    }

    pub fn validate_with_limits(self, limits: ValidationLimits) -> RuntimeContractOutcome {
        let Self { schema, extracted } = self;
        match extracted {
            SchemaExtracted::Candidates {
                document_id,
                candidates,
                diagnostics,
            } => {
                let mut budget =
                    match ValidationBudget::preflight_runtime(&schema, &candidates, limits) {
                        Ok(budget) => budget,
                        Err(failure) => {
                            return RuntimeContractOutcome::ValidationRejected { failure };
                        }
                    };
                let mut records = Vec::new();
                let mut issues = Vec::new();
                for candidate in candidates {
                    let mut value = BTreeMap::new();
                    let mut drafts = Vec::<FieldIssueDraft<'_>>::new();
                    for field in schema.fields() {
                        match validate_runtime_field(field, &candidate) {
                            Ok(field_value) => {
                                value.insert(field.id().clone(), field_value);
                            }
                            Err(issue) => drafts.push(issue),
                        }
                    }
                    if drafts.is_empty() {
                        drop(drafts);
                        records.push(RuntimeValidatedRecord { value, candidate });
                    } else {
                        if let Err(failure) = budget.record_issue_drafts(&drafts) {
                            return RuntimeContractOutcome::ValidationRejected { failure };
                        }
                        let fields = drafts
                            .into_iter()
                            .map(FieldIssueDraft::materialize)
                            .collect();
                        issues.push(RuntimeRecordIssue { candidate, fields });
                    }
                }
                RuntimeContractOutcome::Evaluated {
                    document_id,
                    records,
                    issues,
                    extraction_diagnostics: diagnostics,
                }
            }
            SchemaExtracted::NoMatch { document_id } => {
                RuntimeContractOutcome::NoMatch { document_id }
            }
            SchemaExtracted::Indeterminate {
                document_id,
                completeness,
                reason_code,
            } => RuntimeContractOutcome::Indeterminate {
                document_id,
                completeness,
                reason_code,
            },
            SchemaExtracted::LocateFailed { failure } => {
                RuntimeContractOutcome::LocateFailed { failure }
            }
            SchemaExtracted::Rejected { failure } => {
                RuntimeContractOutcome::ExtractionRejected { failure }
            }
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "type", content = "value", rename_all = "snake_case")]
pub enum RuntimeValue {
    String(String),
    MoneyUsd(Money),
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "cardinality", rename_all = "snake_case")]
pub enum RuntimeFieldValue {
    ExactlyOne { value: RuntimeValue },
    ZeroOrOne { value: Option<RuntimeValue> },
    Many { values: Vec<RuntimeValue> },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RuntimeValidatedRecord {
    pub value: BTreeMap<FieldId, RuntimeFieldValue>,
    pub candidate: CandidateInput,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RuntimeRecordIssue {
    pub candidate: CandidateInput,
    pub fields: Vec<FieldIssue>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum RuntimeContractOutcome {
    Evaluated {
        document_id: DocumentId,
        records: Vec<RuntimeValidatedRecord>,
        issues: Vec<RuntimeRecordIssue>,
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

impl RuntimeContractOutcome {
    /// Returns every validated record only when no field or extraction issue
    /// exists, following `ContractOutcome::require_all()` rules.
    pub fn require_all(self) -> Result<Vec<RuntimeValidatedRecord>, ContractIssues> {
        match self {
            Self::Evaluated {
                records,
                issues,
                extraction_diagnostics,
                ..
            } if issues.is_empty() && extraction_diagnostics.is_empty() => Ok(records),
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

fn validate_runtime_field<'a>(
    field: &FieldSchema,
    candidate: &'a CandidateInput,
) -> Result<RuntimeFieldValue, FieldIssueDraft<'a>> {
    let evidence = candidate.findings(field.id());
    match field.value_type() {
        value_type if value_type == <String as ContractValue>::TYPE_ID => {
            validate_typed_field::<String>(field.id(), field.cardinality(), evidence)
        }
        value_type if value_type == <Money as ContractValue>::TYPE_ID => {
            validate_typed_field::<Money>(field.id(), field.cardinality(), evidence)
        }
        _ => Err(FieldIssueDraft::all(
            field.id().clone(),
            FieldIssueKind::UnsupportedProjectedValue,
            evidence,
        )),
    }
}

fn validate_typed_field<'a, T>(
    id: &FieldId,
    cardinality: Cardinality,
    evidence: &'a [yosoi_documents::Finding],
) -> Result<RuntimeFieldValue, FieldIssueDraft<'a>>
where
    T: IntoRuntimeValue,
{
    match cardinality {
        Cardinality::ExactlyOne => {
            read_required_evidence::<T>(id, evidence).map(|value| RuntimeFieldValue::ExactlyOne {
                value: value.into_runtime_value(),
            })
        }
        Cardinality::ZeroOrOne => {
            read_optional_evidence::<T>(id, evidence).map(|value| RuntimeFieldValue::ZeroOrOne {
                value: value.map(IntoRuntimeValue::into_runtime_value),
            })
        }
        Cardinality::Many => {
            read_many_evidence::<T>(id, evidence).map(|values| RuntimeFieldValue::Many {
                values: values
                    .into_iter()
                    .map(IntoRuntimeValue::into_runtime_value)
                    .collect(),
            })
        }
    }
}

trait IntoRuntimeValue: RuntimeContractValue {
    fn into_runtime_value(self) -> RuntimeValue;
}

impl IntoRuntimeValue for String {
    fn into_runtime_value(self) -> RuntimeValue {
        RuntimeValue::String(self)
    }
}

impl IntoRuntimeValue for Money {
    fn into_runtime_value(self) -> RuntimeValue {
        RuntimeValue::MoneyUsd(self)
    }
}
