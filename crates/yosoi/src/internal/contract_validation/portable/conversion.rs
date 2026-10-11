mod diagnostics;
mod runtime;
use crate::internal::contracts::{CandidateView, Contract, ContractSchema, FieldId};
use diagnostics::{
    portable_extraction_diagnostic, portable_extraction_failure, portable_field_issue,
    portable_validation_failure,
};

use crate::internal::contract_validation::archived::{
    CandidateField as ArchivedCandidateField, ContractDecodeError,
    ContractOutcome as ArchivedContractOutcome,
    ValidatedContractRecord as ArchivedValidatedContractRecord,
};
use crate::internal::contract_validation::{ContractOutcome, Money};

use super::PortableContractDecodeError;
use super::{
    PortableContractField, PortableContractFieldValue, PortableContractOutcome,
    PortableContractRecordIssue, PortableContractValue, PortableValidatedContractRecord,
};

/// A runtime outcome could not be represented by the closed portable Contract vocabulary.
#[derive(Clone, Debug, thiserror::Error, Eq, PartialEq)]
pub enum RuntimeContractArchiveError {
    #[error("runtime Contract schema is invalid")]
    InvalidSchema,
    #[error("runtime Contract field {field} has unsupported value type {value_type}")]
    UnsupportedValueType { field: FieldId, value_type: String },
    #[error("runtime Contract record fields differ from its schema")]
    RecordSchemaMismatch,
    #[error("runtime Contract candidate contains unknown field {field}")]
    UnexpectedCandidateField { field: FieldId },
    #[error("runtime Contract field {field} value differs from its schema")]
    FieldValueMismatch { field: FieldId },
}

/// Capability for converting a typed Contract to and from its archived values.
///
/// `#[derive(yosoi::Contract)]` implements this automatically. A manual
/// [`Contract`] implementation can implement this trait to opt into
/// `ContractRunRecord::new` and typed `ContractRunRecord::values` recovery.
pub trait ArchivedContract: Contract {
    /// Projects one validated value and its evidence into archival data.
    fn to_archived_record(&self, candidate: &Self::Candidate) -> ArchivedValidatedContractRecord;

    /// Projects one candidate's evidence into archival data.
    fn to_archived_candidate(candidate: &Self::Candidate) -> Vec<ArchivedCandidateField>;

    /// Restores one validated value from archival data.
    fn from_archived_record(
        record: &ArchivedValidatedContractRecord,
    ) -> Result<Self, ContractDecodeError>;
}

#[doc(hidden)]
pub trait PortableContractScalar {
    fn to_portable_scalar(&self) -> PortableContractValue;

    fn from_portable_scalar(
        field: &FieldId,
        value: &PortableContractValue,
    ) -> Result<Self, PortableContractDecodeError>
    where
        Self: Sized;
}

impl PortableContractScalar for String {
    fn to_portable_scalar(&self) -> PortableContractValue {
        PortableContractValue::String {
            value: self.clone(),
        }
    }

    fn from_portable_scalar(
        field: &FieldId,
        value: &PortableContractValue,
    ) -> Result<Self, PortableContractDecodeError> {
        match value {
            PortableContractValue::String { value } => Ok(value.clone()),
            PortableContractValue::MoneyUsd { .. } => {
                Err(PortableContractDecodeError::ValueTypeMismatch {
                    field: field.clone(),
                })
            }
        }
    }
}

impl PortableContractScalar for Money {
    fn to_portable_scalar(&self) -> PortableContractValue {
        PortableContractValue::MoneyUsd {
            minor_units: self.minor_units(),
        }
    }

    fn from_portable_scalar(
        field: &FieldId,
        value: &PortableContractValue,
    ) -> Result<Self, PortableContractDecodeError> {
        match value {
            PortableContractValue::MoneyUsd { minor_units } => {
                Self::from_archived_usd_minor_units(*minor_units).ok_or_else(|| {
                    PortableContractDecodeError::InvalidValue {
                        field: field.clone(),
                    }
                })
            }
            PortableContractValue::String { .. } => {
                Err(PortableContractDecodeError::ValueTypeMismatch {
                    field: field.clone(),
                })
            }
        }
    }
}

#[doc(hidden)]
pub trait PortableContractFieldShape {
    fn to_portable_field(&self, id: FieldId) -> PortableContractField;

    fn from_portable_field(
        field: &PortableContractField,
    ) -> Result<Self, PortableContractDecodeError>
    where
        Self: Sized;
}

impl<T> PortableContractFieldShape for T
where
    T: PortableContractScalar,
{
    fn to_portable_field(&self, id: FieldId) -> PortableContractField {
        PortableContractField::new(
            id,
            PortableContractFieldValue::ExactlyOne {
                value: self.to_portable_scalar(),
            },
        )
    }

    fn from_portable_field(
        field: &PortableContractField,
    ) -> Result<Self, PortableContractDecodeError> {
        let PortableContractFieldValue::ExactlyOne { value } = field.value() else {
            return Err(PortableContractDecodeError::CardinalityMismatch {
                field: field.id().clone(),
            });
        };
        T::from_portable_scalar(field.id(), value)
    }
}

impl<T> PortableContractFieldShape for Option<T>
where
    T: PortableContractScalar,
{
    fn to_portable_field(&self, id: FieldId) -> PortableContractField {
        PortableContractField::new(
            id,
            PortableContractFieldValue::ZeroOrOne {
                value: self
                    .as_ref()
                    .map(PortableContractScalar::to_portable_scalar),
            },
        )
    }

    fn from_portable_field(
        field: &PortableContractField,
    ) -> Result<Self, PortableContractDecodeError> {
        let PortableContractFieldValue::ZeroOrOne { value } = field.value() else {
            return Err(PortableContractDecodeError::CardinalityMismatch {
                field: field.id().clone(),
            });
        };
        value
            .as_ref()
            .map(|value| T::from_portable_scalar(field.id(), value))
            .transpose()
    }
}

impl<T> PortableContractFieldShape for Vec<T>
where
    T: PortableContractScalar,
{
    fn to_portable_field(&self, id: FieldId) -> PortableContractField {
        PortableContractField::new(
            id,
            PortableContractFieldValue::Many {
                values: self
                    .iter()
                    .map(PortableContractScalar::to_portable_scalar)
                    .collect(),
            },
        )
    }

    fn from_portable_field(
        field: &PortableContractField,
    ) -> Result<Self, PortableContractDecodeError> {
        let PortableContractFieldValue::Many { values } = field.value() else {
            return Err(PortableContractDecodeError::CardinalityMismatch {
                field: field.id().clone(),
            });
        };
        values
            .iter()
            .map(|value| T::from_portable_scalar(field.id(), value))
            .collect()
    }
}

impl PortableValidatedContractRecord {
    #[doc(hidden)]
    pub fn decode<T>(
        &self,
        archived_schema: &ContractSchema,
    ) -> Result<T, PortableContractDecodeError>
    where
        T: ArchivedContract,
    {
        let compiled =
            T::schema().map_err(|_| PortableContractDecodeError::InvalidContractSchema)?;
        let compiled_identity = compiled
            .identity()
            .map_err(|_| PortableContractDecodeError::InvalidContractSchema)?;
        let archived_identity = archived_schema
            .identity()
            .map_err(|_| PortableContractDecodeError::InvalidContractSchema)?;
        if compiled_identity != archived_identity {
            return Err(PortableContractDecodeError::ContractSchemaMismatch);
        }
        if self.fields().len() != archived_schema.fields().len()
            || self
                .fields()
                .iter()
                .zip(archived_schema.fields())
                .any(|(field, schema)| field.id() != schema.id())
        {
            return Err(PortableContractDecodeError::RecordSchemaMismatch);
        }
        T::from_archived_record(self)
    }
}

impl<T> ContractOutcome<T>
where
    T: Contract + ArchivedContract,
{
    /// Returns the code-independent representation stored by ContractRunRecord.
    pub fn to_archived(&self) -> ArchivedContractOutcome {
        match self {
            Self::Evaluated {
                document_id,
                records,
                issues,
                extraction_diagnostics,
            } => PortableContractOutcome::Evaluated {
                document_id: document_id.clone(),
                records: records
                    .iter()
                    .map(|record| T::to_archived_record(&record.value, &record.candidate))
                    .collect(),
                issues: issues
                    .iter()
                    .map(|issue| {
                        PortableContractRecordIssue::new(
                            CandidateView::document_id(&issue.candidate).clone(),
                            CandidateView::region(&issue.candidate).cloned(),
                            T::to_archived_candidate(&issue.candidate),
                            issue.fields.iter().map(portable_field_issue).collect(),
                        )
                    })
                    .collect(),
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
        }
    }
}
