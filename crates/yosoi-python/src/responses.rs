//! Borrow SDK results through owned response or discovery handles.

use std::sync::Arc;

use pyo3::prelude::*;
use serde_json::{Value, json};
use yosoi::{
    documents::DocumentRef,
    map::{MapOutcome, RetainedCapture},
    policy::{EffectivePolicyIdentity, PolicySnapshot},
    request::{AttemptState, DocumentOutcome, Response, ResponseRef},
};

use crate::{
    documents::{DocumentSource, NativeDocument},
    errors,
};

#[derive(Clone, Debug)]
pub enum ResponseSource {
    Request(Arc<Response>),
    Map {
        outcome: Arc<MapOutcome>,
        index: usize,
    },
}

impl ResponseSource {
    pub fn borrowed(&self) -> PyResult<ResponseRef<'_>> {
        match self {
            Self::Request(response) => Ok(response.as_ref().as_ref()),
            Self::Map { outcome, index } => outcome
                .captures()
                .nth(*index)
                .map(RetainedCapture::response)
                .ok_or_else(|| errors::RequestError::new_err("capture index is out of range")),
        }
    }
}

pub fn identity(identity: EffectivePolicyIdentity) -> Value {
    json!({ "version": identity.version(), "sha256": identity.digest().to_string() })
}

pub fn snapshot(snapshot: &PolicySnapshot) -> Value {
    json!({
        "policy": snapshot.policy(),
        "effective_policy": snapshot.effective_policy(),
        "identity": identity(snapshot.identity()),
    })
}

fn document_metadata(document: DocumentRef<'_>) -> Value {
    json!({
        "id": document.id(), "profile": document.profile(),
        "document_class": document.class(), "byte_len": document.byte_len(),
    })
}

fn document_outcome(outcome: DocumentOutcome<'_>) -> Value {
    match outcome {
        DocumentOutcome::Produced(document) => json!({
            "status": "produced", "document": document_metadata(document),
        }),
        DocumentOutcome::Partial { document, reasons } => json!({
            "status": "partial", "document": document.map(document_metadata),
            "reasons": reasons,
        }),
        DocumentOutcome::Unavailable(reason) => json!({
            "status": "unavailable", "reason": reason,
        }),
        DocumentOutcome::Unprojectable(reason) => json!({
            "status": "unprojectable", "reason": reason,
        }),
    }
}

#[pyclass(frozen, module = "yosoi._native", name = "Response")]
#[derive(Debug)]
pub struct NativeResponse {
    pub source: ResponseSource,
}

#[pymethods]
impl NativeResponse {
    fn to_json(&self) -> PyResult<String> {
        let response = self.source.borrowed()?;
        let attempts: Vec<_> = response
            .attempts()
            .map(|attempt| {
                let (state, failure, not_started) = match attempt.state() {
                    AttemptState::Completed => ("completed", None, None),
                    AttemptState::Failed(kind) => ("failed", Some(kind), None),
                    AttemptState::NotStarted(reason) => ("not_started", None, Some(reason)),
                };
                let documents: Vec<_> = attempt.documents().map(|item| json!({
                "requested": item.requested(), "outcome": document_outcome(item.outcome()),
            })).collect();
                json!({
                    "capture_id": attempt.capture_id().to_string(),
                    "acquisition": attempt.acquisition(),
                    "authored_selection": attempt.authored_selection(),
                    "requested_target": attempt.requested_target(),
                    "http_status": attempt.status(),
                    "state": state, "failure_kind": failure,
                    "not_started_reason": not_started, "diagnostic": attempt.diagnostic(),
                    "documents": documents,
                })
            })
            .collect();
        serde_json::to_string(&json!({
            "request_id": response.request_id().to_string(),
            "requested_target": response.requested_target(),
            "policy_snapshot": snapshot(response.policy_snapshot()),
            "termination": response.termination(), "attempts": attempts,
        }))
        .map_err(|error| errors::RequestError::new_err(error.to_string()))
    }

    fn document(&self, attempt: usize, document: usize) -> PyResult<NativeDocument> {
        let value = NativeDocument {
            source: DocumentSource::Response {
                response: self.source.clone(),
                attempt,
                document,
            },
        };
        value.borrowed()?;
        Ok(value)
    }
}
