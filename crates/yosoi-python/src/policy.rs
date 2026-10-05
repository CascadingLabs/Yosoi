//! Rust policy remains the authority for defaults, validation and identity.

use pyo3::prelude::*;
use yosoi::policy::{Policy, PolicySnapshot};

use crate::errors::PolicyError;

pub fn parse(value: Option<&str>) -> PyResult<Policy> {
    value.map_or_else(
        || Ok(Policy::default()),
        |value| {
            serde_json::from_str(value).map_err(|error| PolicyError::new_err(error.to_string()))
        },
    )
}

#[pyfunction]
pub fn default_policy() -> PyResult<String> {
    serde_json::to_string(&Policy::default())
        .map_err(|error| PolicyError::new_err(error.to_string()))
}

#[pyfunction]
pub fn validate_policy(value: &str) -> PyResult<String> {
    let policy = parse(Some(value))?;
    serde_json::to_string(&policy).map_err(|error| PolicyError::new_err(error.to_string()))
}

#[pyfunction]
pub fn policy_identity(value: &str) -> PyResult<String> {
    let policy = parse(Some(value))?;
    let identity = policy
        .effective_identity()
        .map_err(|error| PolicyError::new_err(error.to_string()))?;
    serde_json::to_string(&serde_json::json!({
        "version": identity.version(),
        "sha256": identity.digest().to_string(),
    }))
    .map_err(|error| PolicyError::new_err(error.to_string()))
}

#[pyfunction]
pub fn effective_policy(value: &str) -> PyResult<String> {
    let policy = parse(Some(value))?;
    let effective = policy
        .effective_policy()
        .map_err(|error| PolicyError::new_err(error.to_string()))?;
    serde_json::to_string(&effective).map_err(|error| PolicyError::new_err(error.to_string()))
}

#[pyfunction]
pub fn policy_snapshot(value: &str) -> PyResult<String> {
    let policy = parse(Some(value))?;
    let snapshot = PolicySnapshot::from_policy(&policy)
        .map_err(|error| PolicyError::new_err(error.to_string()))?;
    serde_json::to_string(&crate::responses::snapshot(&snapshot))
        .map_err(|error| PolicyError::new_err(error.to_string()))
}
