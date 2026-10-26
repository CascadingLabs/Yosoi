//! Browser-only Python handle; source behavior and process ownership remain in Rust.
use super::connection::connection;
use pyo3::prelude::*;
use std::string::String;
connection!(browser_connection, NativeBrowserSurface, "BrowserSurface", yosoi::surface::browser::BrowserSurface, url: String, headless: bool);
use super::connection::failure;
use super::{decode, encode};
use crate::async_runtime;
use yosoi::surface::{Outcome, browser::archive};
#[pyfunction]
fn surface_browser_rerun<'py>(
    py: Python<'py>,
    value: &str,
    policy: &str,
    count: usize,
    headless: bool,
) -> PyResult<Bound<'py, PyAny>> {
    let outcome: Outcome = decode(value)?;
    let policy = decode(policy)?;
    async_runtime::bridge(py, None, move |_| async move {
        encode(
            &archive::rerun(&outcome, policy, count, headless)
                .await
                .map_err(failure)?,
        )
    })
}
pub fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(surface_browser_rerun, module)?)?;
    module.add_class::<NativeBrowserSurface>()
}
