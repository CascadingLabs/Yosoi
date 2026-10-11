//! Python exceptions correspond to public SDK input and operation failures.

use pyo3::{
    create_exception,
    exceptions::PyException,
    prelude::*,
    types::{PyBool, PyDict, PyFloat, PyInt, PyList, PyString},
};
use serde::Serialize;
use serde_json::{Value, error::Category, json};
use std::error::Error as StdError;

mod contract;
mod document;
mod locator;
mod operations;

pub use contract::{contract_schema_error, runtime_archive_error, runtime_contract_error};
pub use document::{document_error, document_profile_error, parse_error};
pub use locator::{coordinate_error, plan_error, query_error};
pub use operations::{
    map_error, policy_error, request_preparation_error, request_send_error, search_query_error,
    search_send_error,
};

create_exception!(_native, YosoiError, PyException);
create_exception!(_native, DocumentError, YosoiError);
create_exception!(_native, ParseError, YosoiError);
create_exception!(_native, LocatorError, YosoiError);
create_exception!(_native, PolicyError, YosoiError);
create_exception!(_native, ClosedResourceError, YosoiError);
create_exception!(_native, RequestError, YosoiError);
create_exception!(_native, MapError, YosoiError);
create_exception!(_native, SearchError, YosoiError);
create_exception!(_native, ContractError, YosoiError);

/// Attaches Rust error identity and payload to the existing exception category
/// without changing its Display message or Python inheritance. Opaque public
/// wrappers carry no variant because their inner discriminants are not exposed.
pub fn with_metadata(
    py: Python<'_>,
    error: PyErr,
    rust_type: &str,
    variant: Option<&str>,
    details: Value,
    source_chain: &[String],
) -> PyErr {
    let value = error.value(py);
    let _ = value.setattr("rust_type", rust_type);
    match variant {
        Some(variant) => {
            let _ = value.setattr("variant", variant);
        }
        None => {
            let _ = value.setattr("variant", py.None());
        }
    }
    if let Ok(details) = json_to_python(py, details) {
        let _ = value.setattr("details", details);
    }
    let sources = PyList::empty(py);
    for source in source_chain {
        let _ = sources.append(source);
    }
    let _ = value.setattr("source_chain", sources);
    error
}

fn json_to_python(py: Python<'_>, value: Value) -> PyResult<Bound<'_, PyAny>> {
    match value {
        Value::Null => Ok(py.None().into_bound(py)),
        Value::Bool(value) => Ok(PyBool::new(py, value).to_owned().into_any()),
        Value::Number(value) => value.as_i64().map_or_else(
            || {
                value.as_u64().map_or_else(
                    || {
                        value.as_f64().map_or_else(
                            || Ok(py.None().into_bound(py)),
                            |value| Ok(PyFloat::new(py, value).into_any()),
                        )
                    },
                    |value| Ok(PyInt::new(py, value).into_any()),
                )
            },
            |value| Ok(PyInt::new(py, value).into_any()),
        ),
        Value::String(value) => Ok(PyString::new(py, &value).into_any()),
        Value::Array(values) => {
            let result = PyList::empty(py);
            for value in values {
                result.append(json_to_python(py, value)?)?;
            }
            Ok(result.into_any())
        }
        Value::Object(values) => {
            let result = PyDict::new(py);
            for (key, value) in values {
                result.set_item(key, json_to_python(py, value)?)?;
            }
            Ok(result.into_any())
        }
    }
}

fn source_chain(error: &(dyn StdError + 'static)) -> Vec<String> {
    let mut result = Vec::new();
    let mut source = error.source();
    while let Some(error) = source {
        result.push(error.to_string());
        source = error.source();
    }
    result
}

fn serde_value<T: Serialize>(value: &T) -> Value {
    match serde_json::to_value(value) {
        Ok(value) => value,
        Err(error) => json!({"serialization_error": error.to_string()}),
    }
}

pub fn serde_decode_error(py: Python<'_>, error: PyErr, source: &serde_json::Error) -> PyErr {
    let (variant, category) = match source.classify() {
        Category::Io => ("Io", "io"),
        Category::Syntax => ("Syntax", "syntax"),
        Category::Data => ("Data", "data"),
        Category::Eof => ("Eof", "eof"),
    };
    with_metadata(
        py,
        error,
        "serde_json::Error",
        Some(variant),
        json!({"category": category, "line": source.line(), "column": source.column()}),
        &[],
    )
}

pub fn serde_encode_error(py: Python<'_>, error: PyErr, source: &serde_json::Error) -> PyErr {
    with_metadata(
        py,
        error,
        "serde_json::Error",
        Some("Serialize"),
        json!({"message": source.to_string()}),
        &[],
    )
}

pub fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    let py = module.py();
    module.add("YosoiError", py.get_type::<YosoiError>())?;
    module.add("DocumentError", py.get_type::<DocumentError>())?;
    module.add("ParseError", py.get_type::<ParseError>())?;
    module.add("LocatorError", py.get_type::<LocatorError>())?;
    module.add("PolicyError", py.get_type::<PolicyError>())?;
    module.add("ClosedResourceError", py.get_type::<ClosedResourceError>())?;
    module.add("RequestError", py.get_type::<RequestError>())?;
    module.add("MapError", py.get_type::<MapError>())?;
    module.add("SearchError", py.get_type::<SearchError>())?;
    module.add("ContractError", py.get_type::<ContractError>())
}
