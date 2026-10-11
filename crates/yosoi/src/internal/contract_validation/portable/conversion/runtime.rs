use crate::internal::contract_validation as yosoi_contract_validation;

use super::super::{
    PortableContractField, PortableContractFieldValue, PortableContractOutcome,
    PortableContractRecordIssue, PortableContractValue, PortableValidatedContractRecord,
};
use super::RuntimeContractArchiveError;
use super::diagnostics::{
    portable_extraction_diagnostic, portable_extraction_failure, portable_field_issue,
    portable_validation_failure,
};
use crate::internal::contract_validation::archived::{
    CandidateField as ArchivedCandidateField, ContractOutcome as ArchivedContractOutcome,
};
use crate::internal::contract_validation::{
    RuntimeContractOutcome, RuntimeFieldValue, RuntimeValue,
};
use crate::internal::contracts::{CandidateInput, Cardinality, ContractSchema, FieldSchema};

impl RuntimeContractOutcome {
    /// Converts this runtime-validated outcome into the same portable archive
    /// representation used by derive-backed `ContractOutcome::to_archived`.
    pub fn to_archived(
        &self,
        schema: &ContractSchema,
    ) -> Result<ArchivedContractOutcome, RuntimeContractArchiveError> {
        schema
            .identity()
            .map_err(|_| RuntimeContractArchiveError::InvalidSchema)?;
        for field in schema.fields() {
            if !matches!(field.value_type(), "string" | "money.usd") {
                return Err(RuntimeContractArchiveError::UnsupportedValueType {
                    field: field.id().clone(),
                    value_type: field.value_type().to_owned(),
                });
            }
        }

        let outcome = match self {
            Self::Evaluated {
                document_id,
                records,
                issues,
                extraction_diagnostics,
            } => PortableContractOutcome::Evaluated {
                document_id: document_id.clone(),
                records: records
                    .iter()
                    .map(|record| runtime_archived_record(record, schema))
                    .collect::<Result<_, _>>()?,
                issues: issues
                    .iter()
                    .map(|issue| {
                        Ok(PortableContractRecordIssue::new(
                            issue.candidate.document_id().clone(),
                            issue.candidate.region().cloned(),
                            runtime_archived_candidate(&issue.candidate, schema)?,
                            issue.fields.iter().map(portable_field_issue).collect(),
                        ))
                    })
                    .collect::<Result<_, RuntimeContractArchiveError>>()?,
                extraction_diagnostics: extraction_diagnostics
                    .iter()
                    .map(portable_extraction_diagnostic)
                    .collect(),
            },
            Self::NoMatch { document_id } => PortableContractOutcome::NoMatch {
                document_id: document_id.clone(),
            },
            Self::Indeterminate {
                document_id,
                completeness,
                reason_code,
            } => PortableContractOutcome::Indeterminate {
                document_id: document_id.clone(),
                completeness: completeness.clone(),
                reason_code: reason_code.clone(),
            },
            Self::LocateFailed { failure } => PortableContractOutcome::LocateFailed {
                failure: failure.clone(),
            },
            Self::ExtractionRejected { failure } => PortableContractOutcome::ExtractionRejected {
                failure: portable_extraction_failure(failure),
            },
            Self::ValidationRejected { failure } => PortableContractOutcome::ValidationRejected {
                failure: portable_validation_failure(failure),
            },
        };
        Ok(outcome)
    }
}

fn runtime_archived_record(
    record: &yosoi_contract_validation::RuntimeValidatedRecord,
    schema: &ContractSchema,
) -> Result<PortableValidatedContractRecord, RuntimeContractArchiveError> {
    if record.value.len() != schema.fields().len() {
        return Err(RuntimeContractArchiveError::RecordSchemaMismatch);
    }
    let fields = schema
        .fields()
        .iter()
        .map(|field| {
            let value = record.value.get(field.id()).ok_or_else(|| {
                RuntimeContractArchiveError::FieldValueMismatch {
                    field: field.id().clone(),
                }
            })?;
            runtime_archived_field(field, value)
        })
        .collect::<Result<_, _>>()?;
    Ok(PortableValidatedContractRecord::new(
        record.candidate.document_id().clone(),
        record.candidate.region().cloned(),
        fields,
        runtime_archived_candidate(&record.candidate, schema)?,
    ))
}

fn runtime_archived_candidate(
    candidate: &CandidateInput,
    schema: &ContractSchema,
) -> Result<Vec<ArchivedCandidateField>, RuntimeContractArchiveError> {
    if let Some((field, _)) = candidate
        .fields()
        .iter()
        .find(|(field, _)| !schema.fields().iter().any(|schema| schema.id() == *field))
    {
        return Err(RuntimeContractArchiveError::UnexpectedCandidateField {
            field: field.clone(),
        });
    }
    Ok(schema
        .fields()
        .iter()
        .map(|field| {
            ArchivedCandidateField::new(field.id().clone(), candidate.findings(field.id()).to_vec())
        })
        .collect())
}

fn runtime_archived_field(
    field: &FieldSchema,
    value: &RuntimeFieldValue,
) -> Result<PortableContractField, RuntimeContractArchiveError> {
    let mismatch = || RuntimeContractArchiveError::FieldValueMismatch {
        field: field.id().clone(),
    };
    let portable = match (field.cardinality(), value) {
        (Cardinality::ExactlyOne, RuntimeFieldValue::ExactlyOne { value }) => {
            PortableContractFieldValue::ExactlyOne {
                value: runtime_archived_value(field, value)?,
            }
        }
        (Cardinality::ZeroOrOne, RuntimeFieldValue::ZeroOrOne { value }) => {
            PortableContractFieldValue::ZeroOrOne {
                value: value
                    .as_ref()
                    .map(|value| runtime_archived_value(field, value))
                    .transpose()?,
            }
        }
        (Cardinality::Many, RuntimeFieldValue::Many { values }) => {
            PortableContractFieldValue::Many {
                values: values
                    .iter()
                    .map(|value| runtime_archived_value(field, value))
                    .collect::<Result<_, _>>()?,
            }
        }
        _ => return Err(mismatch()),
    };
    Ok(PortableContractField::new(field.id().clone(), portable))
}

fn runtime_archived_value(
    field: &FieldSchema,
    value: &RuntimeValue,
) -> Result<PortableContractValue, RuntimeContractArchiveError> {
    match (field.value_type(), value) {
        ("string", RuntimeValue::String(value)) => Ok(PortableContractValue::String {
            value: value.clone(),
        }),
        ("money.usd", RuntimeValue::MoneyUsd(value)) => Ok(PortableContractValue::MoneyUsd {
            minor_units: value.minor_units(),
        }),
        _ => Err(RuntimeContractArchiveError::FieldValueMismatch {
            field: field.id().clone(),
        }),
    }
}
