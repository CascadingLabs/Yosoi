//! Public SDK activity/capture identities, generated and parsed in Rust.

use pyo3::prelude::*;
use yosoi::request::{ActivityId, CaptureId};

use crate::errors::RequestError;

#[pyfunction]
pub fn activity_identity(value: Option<&str>, capture: bool) -> PyResult<String> {
    if capture {
        value
            .map_or_else(
                || Ok(CaptureId::random()),
                |value| {
                    value
                        .parse::<CaptureId>()
                        .map_err(|error| RequestError::new_err(error.to_string()))
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
                        .map_err(|error| RequestError::new_err(error.to_string()))
                },
            )
            .map(|id| id.to_string())
    }
}
#[pyfunction]
pub fn activity_identity_bytes(value: &str) -> PyResult<Vec<u8>> {
    let id = value
        .parse::<ActivityId>()
        .map_err(|error| RequestError::new_err(error.to_string()))?;
    Ok(id.as_bytes().to_vec())
}
