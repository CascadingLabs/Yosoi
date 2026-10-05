//! Async page acquisition calls only the public SDK and retains typed results.

use std::sync::Arc;

use pyo3::prelude::*;
use yosoi::request;

use crate::{
    async_runtime::{self, NativeCancellation},
    errors, policy,
    responses::{NativeResponse, ResponseSource},
};

#[pyclass(frozen, module = "yosoi._native", name = "PageRequest")]
#[derive(Debug)]
pub struct NativeRequest {
    inner: Arc<request::PageRequest>,
}

#[pymethods]
impl NativeRequest {
    #[new]
    fn new(target: String) -> Self {
        Self {
            inner: Arc::new(request::new(target)),
        }
    }

    #[getter]
    fn id(&self) -> String {
        self.inner.id().to_string()
    }

    #[getter]
    fn target(&self) -> &str {
        self.inner.target().as_str()
    }

    #[pyo3(signature = (policy_json=None))]
    fn validate(&self, policy_json: Option<&str>) -> PyResult<()> {
        let policy = policy::parse(policy_json)?;
        self.inner
            .as_ref()
            .clone()
            .bind(&policy)
            .validate()
            .map_err(|error| errors::RequestError::new_err(error.to_string()))
    }

    #[pyo3(signature = (policy_json=None, cancellation=None))]
    fn send<'py>(
        &self,
        py: Python<'py>,
        policy_json: Option<&str>,
        cancellation: Option<&NativeCancellation>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let policy = policy::parse(policy_json)?;
        let request = self.inner.as_ref().clone();
        async_runtime::bridge(py, cancellation, move |token| async move {
            let response = request
                .bind(&policy)
                .send_cancellable(&token)
                .await
                .map_err(|error| errors::RequestError::new_err(error.to_string()))?;
            Ok(NativeResponse {
                source: ResponseSource::Request(Arc::new(response)),
            })
        })
    }
}
