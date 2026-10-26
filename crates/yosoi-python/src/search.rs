//! Search forwards query intent to the SDK and preserves provider slot outcomes.

use std::{fmt, sync::Arc};

use pyo3::prelude::*;
use serde_json::json;
use yosoi::{policy::search::ProviderDefaultsVersion, search};

use crate::{
    async_runtime::{self, NativeCancellation},
    documents::{DocumentSource, NativeDocument},
    errors, policy, responses,
};

fn replay_error(error: &search::SearchReplayError) -> PyErr {
    Python::attach(|py| errors::search_replay_error(py, error))
}

fn attempt_summary_json(attempt: &search::RequestAttemptSummary) -> serde_json::Value {
    let mut value = json!({
        "request_id": attempt.request_id.to_string(), "capture_id": attempt.capture_id.to_string(),
        "acquisition": attempt.acquisition, "http_status": attempt.http_status,
        "source_bytes": attempt.source_bytes, "diagnostic": attempt.diagnostic,
        "terminal": attempt.terminal, "parser_diagnostic": attempt.parser_diagnostic,
        "document_class": attempt.document_class, "document_bytes": attempt.document_bytes,
        "capture_complete": attempt.capture_complete, "capture_retention": attempt.capture_retention,
    });
    if let Some(placement) = attempt.resolution_placement
        && let Some(fields) = value.as_object_mut()
    {
        fields.insert("resolution_placement".to_owned(), json!(placement.get()));
    }
    value
}
async fn response_json(
    response: &search::SearchResponse,
    diagnostic_archive: Option<String>,
) -> PyResult<String> {
    let archive = match diagnostic_archive {
        Some(root) => Some(
            yosoi::Archive::open(root)
                .await
                .map_err(|error| replay_error(&error.into()))?,
        ),
        None => None,
    };
    let mut saved = Vec::with_capacity(response.providers().len());
    for provider in response.providers() {
        let mut records = Vec::new();
        if let Some(archive) = &archive {
            for capture in provider.captures() {
                records.push(
                    capture
                        .save(archive)
                        .await
                        .map_err(|error| replay_error(&error))?,
                );
            }
        }
        saved.push(records);
    }
    let providers: Vec<_> = response.providers().iter().zip(saved).map(|(provider, captures)| {
        let identity = provider.identity();
        let profile = provider.profile();
        let attempts: Vec<_> = provider.attempts().iter().map(attempt_summary_json).collect();
        json!({
            "provider": provider.provider(),
            "identity": { "provider": identity.provider, "endpoint": identity.endpoint,
                "adapter_version": identity.adapter_version, "parser_version": identity.parser_version },
            "profile": { "acquisition": profile.acquisition, "defaults_status": profile.defaults_status,
                "defaults_version": profile.defaults_version.map(ProviderDefaultsVersion::get),
                "effective_request_policy": profile.effective_request_policy.map(responses::identity) },
            "request_id": provider.request_id().map(|value| value.to_string()),
            "recovery_query": provider.recovery_query(), "attempts": attempts, "captures": captures,
            "outcome": provider.outcome(), "charge": provider.charge(),
        })
    }).collect();
    serde_json::to_string(&json!({
        "request_id": response.request_id().to_string(),
        "policy_identity": responses::identity(response.policy_identity()),
        "termination": response.termination(), "providers": providers,
    }))
    .map_err(|error| {
        Python::attach(|py| {
            errors::serde_encode_error(py, errors::SearchError::new_err(error.to_string()), &error)
        })
    })
}

#[pyclass(frozen, module = "yosoi._native", name = "SearchResponse")]
pub struct NativeSearchResponse {
    owner: Arc<search::SearchResponse>,
    json: String,
}

impl fmt::Debug for NativeSearchResponse {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("NativeSearchResponse")
            .field("response", &self.owner)
            .finish_non_exhaustive()
    }
}

#[pymethods]
impl NativeSearchResponse {
    fn to_json(&self) -> &str {
        &self.json
    }

    fn capture_count(&self, provider: usize) -> PyResult<usize> {
        self.owner
            .providers()
            .get(provider)
            .map(|item| item.captures().len())
            .ok_or_else(|| errors::SearchError::new_err("provider index is out of range"))
    }

    fn capture(&self, provider: usize, capture: usize) -> PyResult<NativeSearchCapture> {
        let view = NativeSearchCapture {
            owner: Arc::clone(&self.owner),
            provider,
            capture,
        };
        view.borrowed()?;
        Ok(view)
    }
}

#[pyclass(frozen, module = "yosoi._native", name = "SearchCapture")]
#[derive(Debug)]
pub struct NativeSearchCapture {
    owner: Arc<search::SearchResponse>,
    provider: usize,
    capture: usize,
}

impl NativeSearchCapture {
    fn borrowed(&self) -> PyResult<&search::SearchCapture> {
        self.owner
            .providers()
            .get(self.provider)
            .and_then(|provider| provider.captures().get(self.capture))
            .ok_or_else(|| errors::SearchError::new_err("capture index is out of range"))
    }
}

#[pymethods]
impl NativeSearchCapture {
    fn metadata(&self) -> PyResult<String> {
        let capture = self.borrowed()?;
        serde_json::to_string(&json!({
            "provider":capture.provider(), "request_id":capture.request_id(),
            "capture_id":capture.capture_id(), "original_provider_page_url":capture.original_provider_page_url(),
            "provider_page_url":capture.provider_page_url(), "final_url":capture.final_url(),
            "http_status":capture.http_status(), "capture_complete":capture.capture_complete(),
            "environment":capture.environment().map_err(|error| replay_error(&error))?, "replay_policy":capture.replay_policy(),
            "selected_for_parsing":capture.selected_for_parsing(), "observed":capture.observed(),
        })).map_err(|error| errors::SearchError::new_err(error.to_string()))
    }

    fn document(&self) -> PyResult<NativeDocument> {
        Ok(NativeDocument {
            source: DocumentSource::Owned(Arc::new(self.borrowed()?.document())),
        })
    }

    fn replay(&self, py: Python<'_>) -> PyResult<String> {
        let capture = self.borrowed()?;
        py.detach(|| {
            serde_json::to_string(&capture.replay())
                .map_err(|error| errors::SearchError::new_err(error.to_string()))
        })
    }

    fn save<'py>(&self, py: Python<'py>, archive_root: String) -> PyResult<Bound<'py, PyAny>> {
        let owner = Arc::clone(&self.owner);
        let provider = self.provider;
        let capture = self.capture;
        async_runtime::bridge(py, None, move |_token| async move {
            let item = owner
                .providers()
                .get(provider)
                .and_then(|item| item.captures().get(capture))
                .ok_or_else(|| errors::SearchError::new_err("capture index is out of range"))?;
            let archive = yosoi::Archive::open(archive_root)
                .await
                .map_err(|error| replay_error(&error.into()))?;
            let record = item
                .save(&archive)
                .await
                .map_err(|error| replay_error(&error))?;
            serde_json::to_string(&record)
                .map_err(|error| errors::SearchError::new_err(error.to_string()))
        })
    }
}

#[pyclass(frozen, module = "yosoi._native", name = "SearchRequest")]
#[derive(Debug)]
pub struct NativeSearch {
    inner: search::SearchRequest,
}

#[pymethods]
impl NativeSearch {
    #[new]
    fn new(py: Python<'_>, query: String) -> PyResult<Self> {
        search::new(query)
            .map(|inner| Self { inner })
            .map_err(|error| errors::search_query_error(py, &error))
    }

    #[getter]
    fn id(&self) -> String {
        self.inner.id().to_string()
    }

    #[pyo3(signature = (policy_json=None))]
    fn validate(&self, py: Python<'_>, policy_json: Option<&str>) -> PyResult<()> {
        let policy = policy::parse(policy_json)?;
        self.inner
            .clone()
            .bind(&policy)
            .validate()
            .map_err(|error| errors::search_send_error(py, &error))
    }

    #[pyo3(signature = (policy_json=None, cancellation=None, diagnostic_archive=None, capture=false))]
    fn send<'py>(
        &self,
        py: Python<'py>,
        policy_json: Option<&str>,
        cancellation: Option<&NativeCancellation>,
        diagnostic_archive: Option<String>,
        capture: bool,
    ) -> PyResult<Bound<'py, PyAny>> {
        let policy = policy::parse(policy_json)?;
        let request = self.inner.clone();
        async_runtime::bridge(py, cancellation, move |token| async move {
            let bound = request.bind(&policy);
            let bound = if capture || diagnostic_archive.is_some() {
                bound.with_diagnostic_capture()
            } else {
                bound
            };
            let response = bound
                .send_cancellable(&token)
                .await
                .map_err(|error| Python::attach(|py| errors::search_send_error(py, &error)))?;
            let json = response_json(&response, diagnostic_archive).await?;
            Ok(NativeSearchResponse {
                owner: Arc::new(response),
                json,
            })
        })
    }
}

#[pyfunction]
pub fn search_replay<'py>(
    py: Python<'py>,
    record_json: &str,
    archive_root: String,
) -> PyResult<Bound<'py, PyAny>> {
    let record: search::SearchReplay = serde_json::from_str(record_json)
        .map_err(|error| errors::SearchError::new_err(error.to_string()))?;
    async_runtime::bridge(py, None, move |_token| async move {
        let archive = yosoi::Archive::open(archive_root)
            .await
            .map_err(|error| replay_error(&error.into()))?;
        let result = record
            .replay(&archive)
            .await
            .map_err(|error| replay_error(&error))?;
        serde_json::to_string(&result)
            .map_err(|error| errors::SearchError::new_err(error.to_string()))
    })
}

#[pyfunction]
pub fn search_replay_document(
    py: Python<'_>,
    provider: &str,
    document: &NativeDocument,
    provider_page_url: &str,
    replay_policy_json: &str,
) -> PyResult<String> {
    let provider = serde_json::from_value(serde_json::Value::String(provider.to_owned()))
        .map_err(|error| errors::SearchError::new_err(error.to_string()))?;
    let policy = serde_json::from_str(replay_policy_json)
        .map_err(|error| errors::SearchError::new_err(error.to_string()))?;
    let document = document.borrowed()?;
    py.detach(|| {
        serde_json::to_string(&search::replay_document(
            provider,
            document,
            provider_page_url,
            policy,
        ))
        .map_err(|error| errors::SearchError::new_err(error.to_string()))
    })
}
