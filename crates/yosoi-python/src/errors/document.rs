use pyo3::prelude::{PyErr, Python};
use serde_json::{Value, json};
use yosoi::documents::{
    DocumentEpoch, DocumentError as SdkDocumentError, ParseError as SdkParseError,
};

use super::{DocumentError, ParseError, serde_value, source_chain, with_metadata};

type DocumentProfileError = <DocumentEpoch as TryFrom<u64>>::Error;

fn document_profile_error_details(error: DocumentProfileError) -> (&'static str, Value) {
    use DocumentProfileError as E;
    match error {
        E::IncompatibleAxes => ("IncompatibleAxes", json!({})),
        E::UnexpectedEpoch => ("UnexpectedEpoch", json!({})),
        E::MissingEpoch => ("MissingEpoch", json!({})),
        E::ZeroEpoch => ("ZeroEpoch", json!({})),
    }
}

pub fn document_profile_error(py: Python<'_>, error: DocumentProfileError) -> PyErr {
    let (variant, details) = document_profile_error_details(error);
    with_metadata(
        py,
        DocumentError::new_err(error.to_string()),
        "yosoi_documents::DocumentProfileError",
        Some(variant),
        details,
        &source_chain(&error),
    )
}

fn document_error_details(error: &SdkDocumentError) -> (&'static str, Value) {
    use SdkDocumentError as E;
    match error {
        E::EmptyId => ("EmptyId", json!({})),
        E::EmptyPayload => ("EmptyPayload", json!({})),
        E::PayloadLengthOverflow => ("PayloadLengthOverflow", json!({})),
        E::InvalidProfile(source) => {
            let (variant, details) = document_profile_error_details(*source);
            (
                "InvalidProfile",
                json!({
                    "source": {
                        "rust_type": "yosoi_documents::DocumentProfileError",
                        "variant": variant,
                        "details": details
                    }
                }),
            )
        }
    }
}

pub fn document_error(py: Python<'_>, error: &SdkDocumentError) -> PyErr {
    let (variant, details) = document_error_details(error);
    with_metadata(
        py,
        DocumentError::new_err(error.to_string()),
        "yosoi_documents::DocumentError",
        Some(variant),
        details,
        &source_chain(error),
    )
}

fn parse_error_details(error: &SdkParseError) -> (&'static str, Value) {
    use SdkParseError as E;
    match error {
        E::InvalidResourcePolicy { limit } => (
            "InvalidResourcePolicy",
            json!({"limit": serde_value(limit)}),
        ),
        // The SDK facade exposes this type only as the `ParseError::Document`
        // payload. Preserve that public source family and its Error chain;
        // do not infer unexported parser variants from Debug or Display text.
        E::Document(source) => (
            "Document",
            json!({
                "source": {
                    "rust_type": "yosoi_documents::DocumentParseError",
                    "message": source.to_string()
                }
            }),
        ),
    }
}

pub fn parse_error(py: Python<'_>, error: &SdkParseError) -> PyErr {
    let (variant, details) = parse_error_details(error);
    with_metadata(
        py,
        ParseError::new_err(error.to_string()),
        "yosoi_engine::ParseError",
        Some(variant),
        details,
        &source_chain(error),
    )
}
