use crate::internal::contract_validation::portable::PortableContractDecodeError;
use crate::internal::contracts::{ContractSchemaError, FieldId};
use crate::internal::documents::OutputId;
use thiserror::Error;

#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum ContractRunRecordError {
    #[error("Contract schema is invalid")]
    InvalidContractSchema { source: ContractSchemaError },
    #[error("compiled Contract schema is invalid")]
    InvalidCompiledContractSchema,
    #[error("compiled Contract schema differs from the archived schema")]
    CompiledContractSchemaMismatch,
    #[error("archived Contract value fields differ from its schema")]
    ArchivedRecordSchemaMismatch,
    #[error("archived Contract value is missing field {field}")]
    MissingArchivedField { field: FieldId },
    #[error("archived Contract field {field} has the wrong cardinality")]
    ArchivedCardinalityMismatch { field: FieldId },
    #[error("archived Contract field {field} has the wrong value type")]
    ArchivedValueTypeMismatch { field: FieldId },
    #[error("archived Contract field {field} contains an invalid value")]
    InvalidArchivedValue { field: FieldId },
    #[error("archived Contract record repeats field {field}")]
    DuplicateField { field: FieldId },
    #[error("archived Contract record issue must contain at least one field issue")]
    EmptyRecordIssue,
    #[error("ContractRun ContractSchema is not selected by its EvaluationRun")]
    ContractSchemaNotInEvaluation,
    #[error("ContractRun schema snapshot differs from its referenced ContractSchema")]
    ContractSchemaSnapshotMismatch,
    #[error("ContractRun outcome is inconsistent with its LocatorRun terminal state")]
    LocatorOutcomeMismatch,
    #[error("LocatorRun finding names output {output} absent from the ContractSchema")]
    LocatorOutputNotInSchema { output: OutputId },
    #[error("archived Contract result Document differs from its LocatorRun Document")]
    DocumentMismatch,
    #[error("archived Contract record fields do not match the archived ContractSchema")]
    SchemaFieldMismatch,
    #[error("archived field {field} cardinality differs from the archived ContractSchema")]
    CardinalityMismatch { field: FieldId },
    #[error("archived field {field} value type differs from archived type {expected}")]
    ValueTypeMismatch { field: FieldId, expected: String },
    #[error("archived field {field} contains a value rejected by its declared type")]
    InvalidArchivedScalar { field: FieldId },
    #[error("archived Contract issue names unknown field {field}")]
    UnknownIssueField { field: FieldId },
    #[error("archived Contract evidence belongs to another Document")]
    IssueEvidenceDocumentMismatch,
    #[error("archived Contract evidence is absent from its LocatorRun")]
    EvidenceNotInLocatorRun,
    #[error("archived Contract issue evidence names another schema field")]
    IssueEvidenceFieldMismatch,
    #[error("archived Contract record names a region absent from the LocatorRun")]
    UnknownRegion,
    #[error("archived extraction diagnostic names unknown output {output}")]
    UnknownDiagnosticOutput { output: OutputId },
}

impl ContractRunRecordError {
    pub(in crate::internal::archive) fn from_decode(error: PortableContractDecodeError) -> Self {
        match error {
            PortableContractDecodeError::InvalidContractSchema => {
                Self::InvalidCompiledContractSchema
            }
            PortableContractDecodeError::ContractSchemaMismatch => {
                Self::CompiledContractSchemaMismatch
            }
            PortableContractDecodeError::RecordSchemaMismatch => Self::ArchivedRecordSchemaMismatch,
            PortableContractDecodeError::MissingField { field } => {
                Self::MissingArchivedField { field }
            }
            PortableContractDecodeError::CardinalityMismatch { field } => {
                Self::ArchivedCardinalityMismatch { field }
            }
            PortableContractDecodeError::ValueTypeMismatch { field } => {
                Self::ArchivedValueTypeMismatch { field }
            }
            PortableContractDecodeError::InvalidValue { field } => {
                Self::InvalidArchivedValue { field }
            }
        }
    }
}
