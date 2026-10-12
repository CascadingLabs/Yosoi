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
    ///
    /// Owns an already validated schema. Only `string` and `money.usd` value
    /// types are supported; any other field type returns
    /// [`RuntimeContractError::UnsupportedValueType`]. No document acquisition,
    /// candidate extraction, or value conversion occurs during construction.
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

    /// Borrows the validated schema owned by this runtime Contract.
    pub const fn schema(&self) -> &ContractSchema {
        &self.schema
    }

    /// Extracts with explicit limits using the shared schema-driven grouping
    /// path used by static Contracts.
    ///
    /// Borrows located evidence and returns owned candidates or a typed terminal
    /// extraction state. This does not enforce field cardinality, convert values,
    /// or validate semantics; call [`RuntimeExtracted::validate`] explicitly.
    pub fn extract(&self, located: &LocateOutcome, limits: ExtractionLimits) -> RuntimeExtracted {
        RuntimeExtracted {
            schema: self.schema.clone(),
            extracted: extract_schema_with_limits(&self.schema, located, limits),
        }
    }
}

/// Runtime Contract construction failure for a schema outside the supported value vocabulary.
#[derive(Clone, Debug, Error, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum RuntimeContractError {
    #[error("runtime Contract field {field} has unsupported value type {value_type}")]
    /// A schema field requests a type other than `string` or `money.usd`.
    UnsupportedValueType {
        /// Authored identifier of the unsupported field.
        field: FieldId,
        /// Requested type identifier, retained for caller inspection.
        value_type: String,
    },
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
    /// Borrows grouped candidates, or an empty slice for a noncandidate terminal state.
    ///
    /// An empty slice alone cannot distinguish complete absence, indeterminate
    /// evidence, or extraction failure. Validation retains those distinctions
    /// in its returned outcome.
    pub fn candidates(&self) -> &[CandidateInput] {
        match &self.extracted {
            SchemaExtracted::Candidates { candidates, .. } => candidates,
            _ => &[],
        }
    }

    /// Borrows nonfatal extraction diagnostics when candidates were assembled.
    ///
    /// Returns an empty slice for other terminal states; it does not imply
    /// successful extraction or an all-accepted validation outcome.
    pub fn diagnostics(&self) -> &[ExtractionDiagnostic] {
        match &self.extracted {
            SchemaExtracted::Candidates { diagnostics, .. } => diagnostics,
            _ => &[],
        }
    }

    /// Validates using the same default validation budget as generated
    /// `Extracted<T>::validate()`.
    /// Consumes candidate evidence and performs cardinality, conversion,
    /// completeness, and semantic checks without acquiring any documents.
    pub fn validate(self) -> RuntimeContractOutcome {
        self.validate_with_limits(ValidationLimits::default())
    }

    /// Consumes extraction evidence and validates with caller-supplied resource budgets.
    ///
    /// Accepted and rejected records remain separate in `Evaluated`. Locator,
    /// extraction, and indeterminate states are preserved rather than converted
    /// into empty successful results. Budget failures return `ValidationRejected`
    /// instead of presenting partly processed records as fully validated.
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

/// Converted scalar value from the runtime Contract's supported vocabulary.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "type", content = "value", rename_all = "snake_case")]
pub enum RuntimeValue {
    /// Owned decoded string accepted by field conversion and validation.
    String(String),
    /// USD monetary value accepted by supported money conversion and semantics.
    MoneyUsd(Money),
}

/// Converted field value retaining its authored cardinality distinction.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "cardinality", rename_all = "snake_case")]
pub enum RuntimeFieldValue {
    /// A required field whose candidate evidence yielded exactly one accepted value.
    ExactlyOne {
        /// Single converted field value.
        value: RuntimeValue,
    },
    /// An optional field whose cardinality allows one accepted value or no value.
    ZeroOrOne {
        /// Converted optional value; `None` retains the missing-field distinction.
        value: Option<RuntimeValue>,
    },
    /// A collection field retaining every accepted value in evidence order.
    Many {
        /// Converted collection, which can be empty under many cardinality.
        values: Vec<RuntimeValue>,
    },
}

/// One accepted runtime record with the original candidate evidence retained.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RuntimeValidatedRecord {
    /// Authored field identifiers mapped to converted cardinality-aware values.
    pub value: BTreeMap<FieldId, RuntimeFieldValue>,
    /// Owned original field findings and candidate grouping provenance.
    pub candidate: CandidateInput,
}

/// One rejected runtime candidate with its field issues and original evidence.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RuntimeRecordIssue {
    /// Original grouped evidence for the rejected record.
    pub candidate: CandidateInput,
    /// Field-level rejection explanations with supporting findings.
    pub fields: Vec<FieldIssue>,
}

/// Runtime Contract evaluation preserving successes, rejected records, and terminal evidence states.
#[derive(Clone, Debug, Serialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum RuntimeContractOutcome {
    /// Evaluation finished, possibly with rejected records or extraction diagnostics.
    Evaluated {
        /// Document from which the candidate evidence originated.
        document_id: DocumentId,
        /// Accepted records with converted values and retained original evidence.
        records: Vec<RuntimeValidatedRecord>,
        /// Rejected candidates with field-specific evidence and reasons.
        issues: Vec<RuntimeRecordIssue>,
        /// Nonfatal extraction issues that prevent an unqualified all-accepted claim.
        extraction_diagnostics: Vec<ExtractionDiagnostic>,
    },
    /// Complete locator evidence established no matching candidate records in the requested scope.
    NoMatch {
        /// Examined document whose evidence supports this scope-specific absence claim.
        document_id: DocumentId,
    },
    /// Incomplete evidence prevents establishing complete absence or accepted records.
    Indeterminate {
        /// Identity of the examined evidence document.
        document_id: DocumentId,
        /// Partial or unknown coverage that limits the result.
        completeness: IncompleteEvidence,
        /// Structural explanation for indeterminate evidence.
        reason_code: String,
    },
    /// Locator execution failed before runtime candidate evaluation.
    LocateFailed {
        /// Typed locator failure, distinct from complete absence.
        failure: LocateFailure,
    },
    /// Candidate assembly failed schema or resource checks.
    ExtractionRejected {
        /// Typed extraction failure rather than a per-record field issue.
        failure: ExtractionFailure,
    },
    /// Validation failed schema or accounting-budget checks for the operation.
    ValidationRejected {
        /// Typed operation-level rejection; partly processed records are not exposed as accepted.
        failure: ValidationFailure,
    },
}

impl RuntimeContractOutcome {
    /// Returns every validated record only when no field or extraction issue
    /// exists, following `ContractOutcome::require_all()` rules.
    ///
    /// Consumes the outcome and returns an empty vector for complete `NoMatch`.
    /// Returns [`ContractIssues`] for indeterminate evidence, phase rejection,
    /// or any evaluated record/extraction issue; it never silently discards
    /// rejected records to return only the successful subset.
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
