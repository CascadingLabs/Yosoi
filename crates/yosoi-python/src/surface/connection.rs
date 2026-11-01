//! Thin Python ownership boundary over modality-specific Surface connections.
#[cfg(feature = "browser")]
use super::decode;
use super::encode;
use crate::{async_runtime, errors};
use pyo3::{create_exception, prelude::*};
use std::{error::Error, path::PathBuf};
#[cfg(feature = "surface-video")]
use yosoi::surface::video::VideoError;
use yosoi::surface::{ExecutionError, Outcome, archive};

create_exception!(_native, SurfaceExecutionError, errors::YosoiError);
pub(super) fn failure(error: ExecutionError) -> PyErr {
    let (variant, details) = match &error {
        ExecutionError::Operation(source) => {
            let details = serde_json::json!({});
            #[cfg(feature = "surface-video")]
            let details = if matches!(
                source.downcast_ref::<VideoError>(),
                Some(VideoError::Cancelled)
            ) {
                serde_json::json!({"cancelled":true})
            } else {
                details
            };
            #[cfg(not(feature = "surface-video"))]
            let _ = source;
            ("Operation", details)
        }
        ExecutionError::Execution { outcomes, .. } => {
            ("Execution", serde_json::json!({"outcomes":outcomes}))
        }
    };
    let mut sources = Vec::new();
    let mut source = error.source();
    while let Some(value) = source {
        sources.push(value.to_string());
        source = value.source();
    }
    let message = error.to_string();
    drop(error);
    Python::attach(|py| {
        errors::with_metadata(
            py,
            SurfaceExecutionError::new_err(message),
            "yosoi::surface::ExecutionError",
            Some(variant),
            details,
            &sources,
        )
    })
}
#[cfg(feature = "browser")]
macro_rules! connection {
    ($module:ident, $native:ident, $name:literal, $rust:path, $input:ident : $input_type:ident, $option:ident : $option_type:ty) => {
        mod $module {
            use super::super::{decode, encode};
            use super::$input_type;
            use crate::{async_runtime, surface::connection::failure};
            use pyo3::prelude::*;
            use std::sync::Arc;
            use tokio::sync::Mutex;
            use yosoi::surface::SurfaceConnection;
            use $rust as Source;
            #[pyclass(frozen, module="yosoi._native", name=$name)]
            #[derive(Debug)]
            pub struct $native {
                inner: Arc<Mutex<Source>>,
            }
            #[pymethods]
            impl $native {
                #[staticmethod]
                fn open<'py>(
                    py: Python<'py>,
                    $input: $input_type,
                    policy: &str,
                    $option: $option_type,
                ) -> PyResult<Bound<'py, PyAny>> {
                    let policy = decode(policy)?;
                    async_runtime::bridge(py, None, move |_| async move {
                        Source::open(&$input, policy, $option)
                            .await
                            .map(|inner| Self {
                                inner: Arc::new(Mutex::new(inner)),
                            })
                            .map_err(failure)
                    })
                }
                fn ready<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
                    let inner = Arc::clone(&self.inner);
                    async_runtime::bridge(py, None, move |_| async move {
                        encode(&inner.lock().await.ready().map_err(failure)?)
                    })
                }
                fn execute<'py>(
                    &self,
                    py: Python<'py>,
                    command: &str,
                ) -> PyResult<Bound<'py, PyAny>> {
                    let command = decode(command)?;
                    let inner = Arc::clone(&self.inner);
                    async_runtime::bridge(py, None, move |_| async move {
                        encode(&inner.lock().await.execute(command).await.map_err(failure)?)
                    })
                }
                fn outcome<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
                    let inner = Arc::clone(&self.inner);
                    async_runtime::bridge(py, None, move |_| async move {
                        encode(&inner.lock().await.outcome())
                    })
                }
                fn close<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
                    let inner = Arc::clone(&self.inner);
                    async_runtime::bridge(py, None, move |_| async move {
                        encode(&inner.lock().await.close().await.map_err(failure)?)
                    })
                }
            }
        }
        pub(super) use $module::$native;
    };
}
#[cfg(feature = "browser")]
pub(super) use connection;
#[pyfunction]
fn surface_replay(
    py: Python<'_>,
    path: PathBuf,
    repeat: usize,
    query: Option<String>,
    output: Option<PathBuf>,
) -> PyResult<Bound<'_, PyAny>> {
    async_runtime::bridge(py, None, move |_| async move {
        encode(
            &archive::replay(path, repeat, query.as_deref(), output.as_deref())
                .await
                .map_err(failure)?,
        )
    })
}
#[pyfunction]
fn surface_export(py: Python<'_>, path: PathBuf, output: PathBuf) -> PyResult<Bound<'_, PyAny>> {
    async_runtime::bridge(py, None, move |_| async move {
        archive::export(path, output).await.map_err(failure)
    })
}
#[cfg(feature = "browser")]
#[pyfunction]
fn surface_outcome_rerun<'py>(
    py: Python<'py>,
    value: &str,
    policy: &str,
    count: usize,
) -> PyResult<Bound<'py, PyAny>> {
    let value: Outcome = decode(value)?;
    let policy = decode(policy)?;
    async_runtime::bridge(py, None, move |_| async move {
        encode(&value.rerun(policy, count).await.map_err(failure)?)
    })
}
pub fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add(
        "SurfaceExecutionError",
        module.py().get_type::<SurfaceExecutionError>(),
    )?;
    module.add_function(wrap_pyfunction!(surface_replay, module)?)?;
    module.add_function(wrap_pyfunction!(surface_export, module)?)?;
    #[cfg(feature = "browser")]
    module.add_function(wrap_pyfunction!(surface_outcome_rerun, module)?)?;
    Ok(())
}
