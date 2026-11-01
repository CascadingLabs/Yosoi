//! Rust policy remains the authority for defaults, validation and identity.

use pyo3::prelude::*;
use yosoi::policy::{Policy, PolicySnapshot};

use crate::{
    errors::{self, PolicyError},
    responses::snapshot as response_snapshot,
};

pub fn parse(value: Option<&str>) -> PyResult<Policy> {
    value.map_or_else(
        || Ok(Policy::default()),
        |value| {
            let decode_error = |error: serde_json::Error| {
                Python::attach(|py| {
                    errors::serde_decode_error(py, PolicyError::new_err(error.to_string()), &error)
                })
            };
            let authored: serde_json::Value = serde_json::from_str(value).map_err(decode_error)?;
            if let Some(observe) = authored.get("observe") {
                // Validate component relationships through the SDK before full Policy Serde
                // turns their typed error into a generic JSON Data error.
                let probe = Policy {
                    observe: serde_json::from_value(observe.clone()).map_err(decode_error)?,
                    ..Policy::default()
                };
                probe
                    .validate()
                    .map_err(|error| Python::attach(|py| errors::policy_error(py, &error)))?;
            }
            serde_json::from_value(authored).map_err(decode_error)
        },
    )
}

#[pyfunction]
pub fn default_policy() -> PyResult<String> {
    serde_json::to_string(&Policy::default()).map_err(|error| {
        Python::attach(|py| {
            errors::serde_encode_error(py, PolicyError::new_err(error.to_string()), &error)
        })
    })
}

#[pyfunction]
pub fn validate_policy(py: Python<'_>, value: &str) -> PyResult<String> {
    let policy = parse(Some(value))?;
    serde_json::to_string(&policy).map_err(|error| {
        errors::serde_encode_error(py, PolicyError::new_err(error.to_string()), &error)
    })
}

#[pyfunction]
pub fn policy_identity(py: Python<'_>, value: &str) -> PyResult<String> {
    let policy = parse(Some(value))?;
    let identity = policy
        .effective_identity()
        .map_err(|error| errors::policy_error(py, &error))?;
    serde_json::to_string(&serde_json::json!({
        "version": identity.version(),
        "sha256": identity.digest().to_string(),
    }))
    .map_err(|error| {
        errors::serde_encode_error(py, PolicyError::new_err(error.to_string()), &error)
    })
}

#[pyfunction]
pub fn effective_policy(py: Python<'_>, value: &str) -> PyResult<String> {
    let policy = parse(Some(value))?;
    let effective = policy
        .effective_policy()
        .map_err(|error| errors::policy_error(py, &error))?;
    serde_json::to_string(&effective).map_err(|error| {
        errors::serde_encode_error(py, PolicyError::new_err(error.to_string()), &error)
    })
}

#[pyfunction]
pub fn policy_snapshot(py: Python<'_>, value: &str) -> PyResult<String> {
    let policy = parse(Some(value))?;
    let snapshot =
        PolicySnapshot::from_policy(&policy).map_err(|error| errors::policy_error(py, &error))?;
    serde_json::to_string(&response_snapshot(&snapshot)).map_err(|error| {
        errors::serde_encode_error(py, PolicyError::new_err(error.to_string()), &error)
    })
}
