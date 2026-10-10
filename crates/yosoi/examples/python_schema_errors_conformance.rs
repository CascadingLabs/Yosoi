//! Emit structural views of real public Rust SDK schema errors.
//!
//! ContractSchemaError is intentionally not serializable. This fixture keeps
//! its variant and payload structure explicit while taking display text and
//! error sources from the actual public error values.

use std::error::Error;
use std::io::{self, Write};

use serde_json::{Value, json};
use yosoi::contracts::{
    Cardinality, ContractId, ContractSchema, ContractSchemaError, ExtractionFailure, FieldId,
    FieldSchema, RecordScope, ValidationFailure,
};

fn expected_error<T>(
    result: Result<T, ContractSchemaError>,
) -> Result<ContractSchemaError, Box<dyn Error>> {
    match result {
        Err(error) => Ok(error),
        Ok(_) => Err("the schema constructor unexpectedly accepted invalid input".into()),
    }
}

fn field(id: &str, description: &str, value_type: &str) -> Result<FieldSchema, Box<dyn Error>> {
    Ok(FieldSchema::try_new(
        FieldId::try_new(id)?,
        description,
        Cardinality::ExactlyOne,
        value_type,
    )?)
}

fn schema_error_value(error: &ContractSchemaError) -> (Value, Value, &'static str) {
    let (variant, details, arguments) = match error {
        ContractSchemaError::ZeroVersion => ("ZeroVersion", json!({}), json!({})),
        ContractSchemaError::UnsupportedVersion { observed } => (
            "UnsupportedVersion",
            json!({"observed": observed}),
            json!({"observed": observed}),
        ),
        ContractSchemaError::EmptyContractId => ("EmptyContractId", json!({}), json!({})),
        ContractSchemaError::EmptyFieldId => ("EmptyFieldId", json!({}), json!({})),
        ContractSchemaError::EmptyContractDescription => {
            ("EmptyContractDescription", json!({}), json!({}))
        }
        ContractSchemaError::EmptyFieldDescription { field } => (
            "EmptyFieldDescription",
            json!({"field": field.as_str()}),
            json!({"field": field.as_str()}),
        ),
        ContractSchemaError::EmptyValueType { field } => (
            "EmptyValueType",
            json!({"field": field.as_str()}),
            json!({"field": field.as_str()}),
        ),
        ContractSchemaError::NoFields => ("NoFields", json!({}), json!({})),
        ContractSchemaError::DuplicateField { field } => (
            "DuplicateField",
            json!({"field": field.as_str()}),
            json!({"field": field.as_str()}),
        ),
        ContractSchemaError::LengthOverflow => ("LengthOverflow", json!({}), json!({})),
    };
    (
        json!({"variant": variant, "details": details}),
        arguments,
        variant,
    )
}

fn source_chain(error: &(dyn Error + 'static)) -> Vec<String> {
    let mut messages = Vec::new();
    let mut source = error.source();
    while let Some(error) = source {
        messages.push(error.to_string());
        source = error.source();
    }
    messages
}

fn record_schema_error(output: &mut Vec<Value>, error: &ContractSchemaError) {
    let (value, arguments, variant) = schema_error_value(error);
    output.push(json!({
        "rust_type": "ContractSchemaError",
        "variant": variant,
        "case": variant,
        "value": value,
        "arguments": arguments,
        "message": error.to_string(),
        "source_chain": source_chain(error),
    }));
}

fn record_wrapped_errors(output: &mut Vec<Value>, error: ContractSchemaError) {
    let (schema_error, _, case) = schema_error_value(&error);
    let extraction = ExtractionFailure::InvalidContractSchema(error.clone());
    output.push(json!({
        "rust_type": "ExtractionFailure",
        "variant": "InvalidContractSchema",
        "case": case,
        "value": {
            "kind": "invalid_contract_schema",
            "message": extraction.to_string(),
            "schema_error": schema_error,
        },
        "arguments": {"0": schema_error},
        "message": extraction.to_string(),
        "source_chain": source_chain(&extraction),
    }));

    let validation = ValidationFailure::InvalidContractSchema(error);
    output.push(json!({
        "rust_type": "ValidationFailure",
        "variant": "InvalidContractSchema",
        "case": case,
        "value": {
            "kind": "invalid_contract_schema",
            "message": validation.to_string(),
            "schema_error": schema_error,
        },
        "arguments": {"0": schema_error},
        "message": validation.to_string(),
        "source_chain": source_chain(&validation),
    }));
}

fn errors() -> Result<Vec<ContractSchemaError>, Box<dyn Error>> {
    let valid_id = ContractId::try_new("example")?;
    let valid_field = field("title", "Title", "string")?;
    let duplicate_field = valid_field.clone();

    Ok(vec![
        expected_error(ContractSchema::try_new(
            0,
            valid_id.clone(),
            "Example",
            RecordScope::Page,
            vec![valid_field.clone()],
        ))?,
        expected_error(ContractSchema::try_new(
            2,
            valid_id.clone(),
            "Example",
            RecordScope::Page,
            vec![valid_field.clone()],
        ))?,
        ContractId::try_new("")
            .err()
            .ok_or("empty contract ID was accepted")?,
        FieldId::try_new("")
            .err()
            .ok_or("empty field ID was accepted")?,
        expected_error(ContractSchema::try_new(
            1,
            valid_id.clone(),
            " ",
            RecordScope::Page,
            vec![valid_field.clone()],
        ))?,
        expected_error(FieldSchema::try_new(
            FieldId::try_new("title")?,
            " ",
            Cardinality::ExactlyOne,
            "string",
        ))?,
        expected_error(FieldSchema::try_new(
            FieldId::try_new("title")?,
            "Title",
            Cardinality::ExactlyOne,
            " ",
        ))?,
        expected_error(ContractSchema::try_new(
            1,
            valid_id.clone(),
            "Example",
            RecordScope::Page,
            Vec::new(),
        ))?,
        expected_error(ContractSchema::try_new(
            1,
            valid_id,
            "Example",
            RecordScope::Page,
            vec![valid_field, duplicate_field],
        ))?,
        ContractSchemaError::LengthOverflow,
    ])
}

fn main() -> Result<(), Box<dyn Error>> {
    let mut output = Vec::new();
    for error in errors()? {
        record_schema_error(&mut output, &error);
        record_wrapped_errors(&mut output, error);
    }

    let stdout = io::stdout();
    let mut writer = io::BufWriter::new(stdout.lock());
    serde_json::to_writer(&mut writer, &output)?;
    writeln!(writer)?;
    Ok(())
}
