//! Pure public scalar/catalog operations remain Rust-owned.

use pyo3::prelude::*;
use yosoi::{map::PublicProvider, search::SearchResultUrl};

use crate::errors::{MapError, SearchError};

fn provider(value: &str) -> PyResult<PublicProvider> {
    for item in PublicProvider::all() {
        let key =
            serde_json::to_value(item).map_err(|error| MapError::new_err(error.to_string()))?;
        if key.as_str() == Some(value) {
            return Ok(*item);
        }
    }
    Err(MapError::new_err("unknown public provider"))
}

#[pyfunction]
pub fn public_providers() -> PyResult<String> {
    serde_json::to_string(PublicProvider::all())
        .map_err(|error| MapError::new_err(error.to_string()))
}

#[pyfunction]
pub fn public_provider_name(value: &str) -> PyResult<&'static str> {
    Ok(provider(value)?.name())
}

#[pyfunction]
pub fn public_provider_endpoint(value: &str, domain: &str) -> PyResult<String> {
    provider(value)?
        .endpoint(domain)
        .map(|url| url.to_string())
        .map_err(|error| MapError::new_err(error.to_string()))
}

#[pyfunction]
pub fn search_result_url(value: &str) -> PyResult<String> {
    SearchResultUrl::parse(value)
        .map(|url| url.as_str().to_owned())
        .map_err(|error| SearchError::new_err(error.to_string()))
}
