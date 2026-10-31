//! Browser-only Python handle; source behavior and process ownership remain in Rust.
use super::connection::connection;
use pyo3::prelude::*;
use std::string::String;
connection!(browser_connection, NativeBrowserSurface, "BrowserSurface", yosoi::surface::browser::BrowserSurface, url: String, headless: bool);
use super::connection::{cancelled, failure};
use super::{decode, encode};
use crate::{
    async_runtime,
    browser::{NativeSession, NativeWork},
};
use yosoi::surface::{
    Outcome,
    browser::{BrowserSurface, archive},
};

#[pyfunction]
fn surface_browser_consume_session<'py>(
    py: Python<'py>,
    session: &NativeSession,
    policy_json: &str,
) -> PyResult<Bound<'py, PyAny>> {
    let session = session.clone_for_surface()?;
    let policy = decode(policy_json)?;
    async_runtime::bridge(py, None, move |token| async move {
        tokio::select! {
            biased;
            () = token.cancelled() => Err(cancelled()),
            result = BrowserSurface::consume_session(session, policy) =>
                result.map(NativeBrowserSurface::from_source).map_err(failure),
        }
    })
}

#[pyfunction]
fn surface_browser_consume_work<'py>(
    py: Python<'py>,
    work: &NativeWork,
    policy_json: &str,
) -> PyResult<Bound<'py, PyAny>> {
    let policy = decode(policy_json)?;
    let work = work.take_for_surface()?;
    async_runtime::bridge(py, None, move |token| async move {
        tokio::select! {
            biased;
            () = token.cancelled() => Err(cancelled()),
            result = BrowserSurface::consume_work(work, policy) =>
                result.map(NativeBrowserSurface::from_source).map_err(failure),
        }
    })
}

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
    module.add_function(wrap_pyfunction!(surface_browser_consume_session, module)?)?;
    module.add_function(wrap_pyfunction!(surface_browser_consume_work, module)?)?;
    module.add_function(wrap_pyfunction!(surface_browser_rerun, module)?)?;
    module.add_class::<NativeBrowserSurface>()
}
