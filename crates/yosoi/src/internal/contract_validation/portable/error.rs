use crate::internal::contracts::FieldId;
use thiserror::Error;

#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum PortableContractDecodeError {
    #[error("compiled Contract schema is invalid")]
    InvalidContractSchema,
    #[error("compiled Contract schema differs from the archived ContractSchema")]
    ContractSchemaMismatch,
    #[error("portable Contract record fields differ from the archived ContractSchema")]
    RecordSchemaMismatch,
    #[error("portable Contract record is missing field {field}")]
    MissingField { field: FieldId },
    #[error("portable Contract field {field} has the wrong cardinality")]
    CardinalityMismatch { field: FieldId },
    #[error("portable Contract field {field} has the wrong value type")]
    ValueTypeMismatch { field: FieldId },
    #[error("portable Contract field {field} contains an invalid value")]
    InvalidValue { field: FieldId },
}
