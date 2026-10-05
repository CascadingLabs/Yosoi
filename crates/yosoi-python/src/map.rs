//! Site discovery delegates to the public SDK and keeps capture owners alive.

use std::sync::Arc;

use pyo3::prelude::*;
use serde_json::json;
use yosoi::map;

use crate::{
    async_runtime::{self, NativeCancellation},
    errors, policy,
    responses::{self, NativeResponse, ResponseSource},
};

#[pyclass(frozen, module = "yosoi._native", name = "MapRequest")]
#[derive(Debug)]
pub struct NativeMapRequest {
    inner: map::MapRequest,
}

#[pymethods]
impl NativeMapRequest {
    #[new]
    fn new(seed: String) -> Self {
        Self {
            inner: map::new(seed),
        }
    }

    #[pyo3(signature = (policy_json=None))]
    fn validate(&self, policy_json: Option<&str>) -> PyResult<()> {
        let policy = policy::parse(policy_json)?;
        self.inner
            .clone()
            .bind(&policy)
            .validate()
            .map_err(|error| errors::MapError::new_err(error.to_string()))
    }

    #[pyo3(signature = (policy_json=None, cancellation=None))]
    fn send<'py>(
        &self,
        py: Python<'py>,
        policy_json: Option<&str>,
        cancellation: Option<&NativeCancellation>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let policy = policy::parse(policy_json)?;
        let request = self.inner.clone().bind(&policy);
        async_runtime::bridge(py, cancellation, move |token| async move {
            let outcome = request
                .send_cancellable(&token)
                .await
                .map_err(|error| errors::MapError::new_err(error.to_string()))?;
            Ok(NativeMapOutcome {
                inner: Arc::new(outcome),
            })
        })
    }
}

#[pyclass(frozen, module = "yosoi._native", name = "MapOutcome")]
#[derive(Debug)]
pub struct NativeMapOutcome {
    inner: Arc<map::MapOutcome>,
}

#[pymethods]
impl NativeMapOutcome {
    fn to_json(&self) -> PyResult<String> {
        let outcome = &self.inner;
        let captures: Vec<_> = outcome
            .captures()
            .map(|capture| json!({ "url": capture.url() }))
            .collect();
        serde_json::to_string(&json!({
            "policy_snapshot": responses::snapshot(outcome.policy_snapshot()),
            "hosts": outcome.hosts(), "pages": outcome.pages(),
            "relationships": outcome.relationships(), "frontier": outcome.frontier(),
            "support_documents": outcome.support_documents(), "sources": outcome.sources(),
            "tree": outcome.tree(), "captures": captures,
            "wildcard_names": outcome.wildcard_names(), "wildcards": outcome.wildcards(),
            "request_trace": outcome.request_trace(), "termination": outcome.termination(),
            "omissions": outcome.omissions(), "summary": outcome.summary(),
        }))
        .map_err(|error| errors::MapError::new_err(error.to_string()))
    }

    fn response(&self, index: usize) -> PyResult<NativeResponse> {
        let source = ResponseSource::Map {
            outcome: Arc::clone(&self.inner),
            index,
        };
        source.borrowed()?;
        Ok(NativeResponse { source })
    }
}
