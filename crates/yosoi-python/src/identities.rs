//! Public SDK activity/capture identities, generated and parsed in Rust.

use pyo3::prelude::*;
use serde_json::json;
use std::str::FromStr;
use yosoi::request::{ActivityId, CaptureId};

use crate::errors::{self, RequestError};

type IdentityParseError = <ActivityId as FromStr>::Err;

fn identity_error(py: Python<'_>, error: &IdentityParseError) -> PyErr {
    let variant = match error {
        IdentityParseError::InvalidUuid => "InvalidUuid",
        IdentityParseError::NonCanonical => "NonCanonical",
        IdentityParseError::NotRandomV4 => "NotRandomV4",
    };
    errors::with_metadata(
        py,
        RequestError::new_err(error.to_string()),
        "yosoi_types::OccurrenceIdParseError",
        Some(variant),
        json!({}),
        &[],
    )
}

#[pyfunction]
pub fn activity_identity(py: Python<'_>, value: Option<&str>, capture: bool) -> PyResult<String> {
    if capture {
        value
            .map_or_else(
                || Ok(CaptureId::random()),
                |value| {
                    value
                        .parse::<CaptureId>()
                        .map_err(|error| identity_error(py, &error))
                },
            )
            .map(|id| id.to_string())
    } else {
        value
            .map_or_else(
                || Ok(ActivityId::random()),
                |value| {
                    value
                        .parse::<ActivityId>()
                        .map_err(|error| identity_error(py, &error))
                },
            )
            .map(|id| id.to_string())
    }
}
#[pyfunction]
pub fn activity_identity_bytes(py: Python<'_>, value: &str) -> PyResult<Vec<u8>> {
    let id = value
        .parse::<ActivityId>()
        .map_err(|error| identity_error(py, &error))?;
    Ok(id.as_bytes().to_vec())
}
