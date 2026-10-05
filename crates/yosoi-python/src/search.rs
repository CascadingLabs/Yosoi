//! Search forwards query intent to the SDK and preserves provider slot outcomes.

use pyo3::prelude::*;
use serde_json::json;
use yosoi::{policy::search::ProviderDefaultsVersion, search};

use crate::{
    async_runtime::{self, NativeCancellation},
    errors, policy, responses,
};

fn response_json(response: &search::SearchResponse) -> PyResult<String> {
    let providers: Vec<_> = response.providers().iter().map(|provider| {
        let identity = provider.identity();
        let profile = provider.profile();
        let attempts: Vec<_> = provider.attempts().iter().map(|attempt| json!({
            "request_id": attempt.request_id.to_string(), "capture_id": attempt.capture_id.to_string(),
            "acquisition": attempt.acquisition, "http_status": attempt.http_status,
            "source_bytes": attempt.source_bytes, "diagnostic": attempt.diagnostic,
            "terminal": attempt.terminal,
        })).collect();
        json!({
            "provider": provider.provider(),
            "identity": { "provider": identity.provider, "endpoint": identity.endpoint,
                "adapter_version": identity.adapter_version, "parser_version": identity.parser_version },
            "profile": { "acquisition": profile.acquisition, "defaults_status": profile.defaults_status,
                "defaults_version": profile.defaults_version.map(ProviderDefaultsVersion::get),
                "effective_request_policy": profile.effective_request_policy.map(responses::identity) },
            "request_id": provider.request_id().map(|value| value.to_string()),
            "recovery_query": provider.recovery_query(), "attempts": attempts,
            "outcome": provider.outcome(), "charge": provider.charge(),
        })
    }).collect();
    serde_json::to_string(&json!({
        "request_id": response.request_id().to_string(),
        "policy_identity": responses::identity(response.policy_identity()),
        "termination": response.termination(), "providers": providers,
    }))
    .map_err(|error| errors::SearchError::new_err(error.to_string()))
}

#[pyclass(frozen, module = "yosoi._native", name = "SearchRequest")]
#[derive(Debug)]
pub struct NativeSearch {
    inner: search::SearchRequest,
}

#[pymethods]
impl NativeSearch {
    #[new]
    fn new(query: String) -> PyResult<Self> {
        search::new(query)
            .map(|inner| Self { inner })
            .map_err(|error| errors::SearchError::new_err(error.to_string()))
    }

    #[getter]
    fn id(&self) -> String {
        self.inner.id().to_string()
    }

    #[pyo3(signature = (policy_json=None))]
    fn validate(&self, policy_json: Option<&str>) -> PyResult<()> {
        let policy = policy::parse(policy_json)?;
        self.inner
            .clone()
            .bind(&policy)
            .validate()
            .map_err(|error| errors::SearchError::new_err(error.to_string()))
    }

    #[pyo3(signature = (policy_json=None, cancellation=None))]
    fn send<'py>(
        &self,
        py: Python<'py>,
        policy_json: Option<&str>,
        cancellation: Option<&NativeCancellation>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let policy = policy::parse(policy_json)?;
        let request = self.inner.clone();
        async_runtime::bridge(py, cancellation, move |token| async move {
            let response = request
                .bind(&policy)
                .send_cancellable(&token)
                .await
                .map_err(|error| errors::SearchError::new_err(error.to_string()))?;
            response_json(&response)
        })
    }
}
