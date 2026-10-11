use pyo3::prelude::{PyErr, Python};
use serde_json::json;
use yosoi::contracts::{ContractSchemaError, RuntimeContractArchiveError, RuntimeContractError};

use super::{ContractError, source_chain, with_metadata};

pub fn contract_schema_error(py: Python<'_>, error: &ContractSchemaError) -> PyErr {
    use ContractSchemaError as E;
    let (variant, details) = match error {
        E::ZeroVersion => ("ZeroVersion", json!({})),
        E::UnsupportedVersion { observed } => ("UnsupportedVersion", json!({"observed": observed})),
        E::EmptyContractId => ("EmptyContractId", json!({})),
        E::EmptyFieldId => ("EmptyFieldId", json!({})),
        E::EmptyContractDescription => ("EmptyContractDescription", json!({})),
        E::EmptyFieldDescription { field } => {
            ("EmptyFieldDescription", json!({"field": field.as_str()}))
        }
        E::EmptyValueType { field } => ("EmptyValueType", json!({"field": field.as_str()})),
        E::NoFields => ("NoFields", json!({})),
        E::DuplicateField { field } => ("DuplicateField", json!({"field": field.as_str()})),
        E::LengthOverflow => ("LengthOverflow", json!({})),
    };
    with_metadata(
        py,
        ContractError::new_err(error.to_string()),
        "yosoi_contracts::ContractSchemaError",
        Some(variant),
        details,
        &source_chain(error),
    )
}

pub fn runtime_contract_error(py: Python<'_>, error: &RuntimeContractError) -> PyErr {
    let RuntimeContractError::UnsupportedValueType { field, value_type } = error;
    with_metadata(
        py,
        ContractError::new_err(error.to_string()),
        "yosoi_contract_validation::RuntimeContractError",
        Some("UnsupportedValueType"),
        json!({"field": field.as_str(), "value_type": value_type}),
        &source_chain(error),
    )
}

pub fn runtime_archive_error(py: Python<'_>, error: &RuntimeContractArchiveError) -> PyErr {
    use RuntimeContractArchiveError as E;
    let (variant, details) = match error {
        E::InvalidSchema => ("InvalidSchema", json!({})),
        E::UnsupportedValueType { field, value_type } => (
            "UnsupportedValueType",
            json!({"field": field.as_str(), "value_type": value_type}),
        ),
        E::RecordSchemaMismatch => ("RecordSchemaMismatch", json!({})),
        E::UnexpectedCandidateField { field } => {
            ("UnexpectedCandidateField", json!({"field": field.as_str()}))
        }
        E::FieldValueMismatch { field } => ("FieldValueMismatch", json!({"field": field.as_str()})),
    };
    with_metadata(
        py,
        ContractError::new_err(error.to_string()),
        "yosoi_contract_validation::RuntimeContractArchiveError",
        Some(variant),
        details,
        &source_chain(error),
    )
}
