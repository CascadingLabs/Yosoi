//! Versioned and canonical JSON representation of finalized Web Captures.

use std::mem;

use crate::internal::types::Sha256Digest;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use thiserror::Error;

use crate::internal::web_capture::{
    BrowserContextCleanupDisposition, BrowserExecutionAccountingPhase, BrowserExecutionLimits,
    BrowserExecutionReceipt, BrowserExecutionScope, BrowserExecutionTerminalReason,
    BrowserProcessCleanupDisposition, WebCapture,
};

/// Current pre-release Web Capture envelope version.
///
/// The schema deliberately remains v1 until the first public consumer exists.
/// During pre-release development, intentional wire changes replace the v1
/// fixtures in place; this crate does not carry speculative compatibility code.
pub const WEB_CAPTURE_SCHEMA_VERSION: u32 = 1;

/// Errors produced while encoding or decoding the Web Capture wire format.
#[derive(Debug, Error)]
pub enum WebCaptureWireError {
    /// JSON syntax or typed capture data was invalid.
    #[error("invalid Web Capture JSON: {0}")]
    InvalidJson(#[source] serde_json::Error),
    /// The root object omitted its version discriminator.
    #[error("Web Capture JSON requires an integer schema_version")]
    MissingSchemaVersion,
    /// The version discriminator was not a positive JSON integer.
    #[error("Web Capture schema_version must be a positive integer")]
    InvalidSchemaVersion,
    /// The document uses a schema this library cannot interpret.
    #[error(
        "unsupported Web Capture schema version {found}; highest supported version is {supported}"
    )]
    UnsupportedSchemaVersion {
        /// Version found in the document.
        found: u64,
        /// Highest version understood by this library.
        supported: u32,
    },
    /// A validated value could not be represented as JSON.
    #[error("could not serialize Web Capture JSON: {0}")]
    Serialization(#[source] serde_json::Error),
    /// The typed execution receipt was absent from its serialized capture location.
    #[error("serialized Web Capture omitted its browser execution receipt")]
    MissingBrowserExecutionProjectionTarget,
}

/// Namespace for versioned Web Capture wire operations.
///
/// The wire representation is an envelope containing `schema_version` and
/// `capture`. Callers should use this API, rather than hashing an incidental
/// `serde_json::to_vec(&capture)` result.
#[derive(Clone, Copy, Debug, Default)]
pub struct WebCaptureWire;

impl WebCaptureWire {
    /// Encodes the complete versioned document as canonical compact JSON.
    ///
    /// Object keys are lexicographic. Arrays whose order has no domain meaning
    /// (`artifacts`, activity `outputs`, and `relationships`) are sorted by
    /// their recursively canonical representation. Ordered request inputs and
    /// provenance lineage remain in producer-supplied order.
    pub fn to_canonical_json(capture: &WebCapture) -> Result<Vec<u8>, WebCaptureWireError> {
        let envelope = WebCaptureEnvelope {
            schema_version: WEB_CAPTURE_SCHEMA_VERSION,
            capture,
        };
        let mut value =
            serde_json::to_value(envelope).map_err(WebCaptureWireError::Serialization)?;
        canonicalize(&mut value, None);
        serde_json::to_vec(&value).map_err(WebCaptureWireError::Serialization)
    }

    /// Decodes the current pre-release v1 document or returns an actionable error.
    ///
    /// There are no production consumers, so obsolete pre-release v1 shapes are
    /// intentionally unsupported rather than migrated. Fixtures and code advance
    /// together until the first public compatibility commitment.
    pub fn from_json(bytes: &[u8]) -> Result<WebCapture, WebCaptureWireError> {
        let value: Value =
            serde_json::from_slice(bytes).map_err(WebCaptureWireError::InvalidJson)?;
        let version = value
            .as_object()
            .and_then(|object| object.get("schema_version"))
            .ok_or(WebCaptureWireError::MissingSchemaVersion)?
            .as_u64()
            .ok_or(WebCaptureWireError::InvalidSchemaVersion)?;
        if version == 0 {
            return Err(WebCaptureWireError::InvalidSchemaVersion);
        }
        if version != u64::from(WEB_CAPTURE_SCHEMA_VERSION) {
            return Err(WebCaptureWireError::UnsupportedSchemaVersion {
                found: version,
                supported: WEB_CAPTURE_SCHEMA_VERSION,
            });
        }
        let envelope: OwnedWebCaptureEnvelope =
            serde_json::from_value(value).map_err(WebCaptureWireError::InvalidJson)?;
        Ok(envelope.capture)
    }

    /// Hashes the canonical semantic-identity projection.
    ///
    /// This deliberately excludes occurrence UUIDs, activity-local ordinals,
    /// wall-clock timestamps, and location-based input, lineage, and
    /// relationship references. It retains elapsed timing, policies,
    /// termination facts, producers and versions, schemas, artifact metadata,
    /// and content digests. The digest identifies equivalent represented
    /// capture evidence; it is not an execution ID, artifact byte digest, or
    /// future replay-plan identity.
    pub fn identity_digest(capture: &WebCapture) -> Result<Sha256Digest, WebCaptureWireError> {
        let envelope = WebCaptureEnvelope {
            schema_version: WEB_CAPTURE_SCHEMA_VERSION,
            capture,
        };
        let mut value =
            serde_json::to_value(envelope).map_err(WebCaptureWireError::Serialization)?;
        if let Some(receipt) = capture.browser_execution() {
            let projection =
                serde_json::to_value(BrowserExecutionSemanticProjection::from(receipt))
                    .map_err(WebCaptureWireError::Serialization)?;
            let target = value
                .pointer_mut("/capture/browser_execution")
                .ok_or(WebCaptureWireError::MissingBrowserExecutionProjectionTarget)?;
            *target = projection;
        }
        redact_volatile_identity_fields(&mut value);
        canonicalize(&mut value, None);
        let bytes = serde_json::to_vec(&value).map_err(WebCaptureWireError::Serialization)?;
        Ok(Sha256Digest::digest(&bytes))
    }
}

#[derive(Serialize)]
#[serde(deny_unknown_fields)]
struct WebCaptureEnvelope<'a> {
    schema_version: u32,
    capture: &'a WebCapture,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct OwnedWebCaptureEnvelope {
    #[serde(rename = "schema_version")]
    _schema_version: u32,
    capture: WebCapture,
}

/// Explicit semantic projection of a managed execution receipt.
///
/// Every UUID-backed lease identity and the capture occurrence binding are
/// intentionally absent. All non-occurrence admission, cleanup, terminal, and
/// accounting facts are named here so similarly named fields elsewhere cannot
/// be erased by broad JSON-key deletion.
#[derive(Serialize)]
#[serde(deny_unknown_fields)]
struct BrowserExecutionSemanticProjection {
    admission: BrowserExecutionAdmissionSemanticProjection,
    cleanup: BrowserExecutionCleanupSemanticProjection,
    reason: BrowserExecutionTerminalReason,
    accounting: BrowserExecutionAccountingSemanticProjection,
}

impl From<&BrowserExecutionReceipt> for BrowserExecutionSemanticProjection {
    fn from(receipt: &BrowserExecutionReceipt) -> Self {
        let admission = receipt.terminal().admission();
        let cleanup = receipt.terminal().cleanup();
        let accounting = receipt.accounting();
        Self {
            admission: BrowserExecutionAdmissionSemanticProjection {
                scope: admission.scope(),
                process_generation: admission.execution().process().generation().get(),
            },
            cleanup: BrowserExecutionCleanupSemanticProjection {
                context: cleanup.context(),
                process: cleanup.process(),
            },
            reason: receipt.terminal().reason(),
            accounting: BrowserExecutionAccountingSemanticProjection {
                phase: accounting.phase(),
                limits: accounting.limits(),
                active_processes: accounting.active_processes(),
                active_contexts_total: accounting.active_contexts_total(),
                active_contexts_in_process: accounting.active_contexts_in_process(),
                active_tabs_total: accounting.active_tabs_total(),
                active_tabs_in_session: accounting.active_tabs_in_session(),
                queued_executions: accounting.queued_executions(),
                completed_executions_since_recycle: accounting.completed_executions_since_recycle(),
            },
        }
    }
}

#[derive(Serialize)]
#[serde(deny_unknown_fields)]
struct BrowserExecutionAdmissionSemanticProjection {
    scope: BrowserExecutionScope,
    process_generation: u64,
}

#[derive(Serialize)]
#[serde(deny_unknown_fields)]
struct BrowserExecutionCleanupSemanticProjection {
    context: BrowserContextCleanupDisposition,
    process: BrowserProcessCleanupDisposition,
}

#[derive(Serialize)]
#[serde(deny_unknown_fields)]
struct BrowserExecutionAccountingSemanticProjection {
    phase: BrowserExecutionAccountingPhase,
    limits: BrowserExecutionLimits,
    active_processes: u32,
    active_contexts_total: u32,
    active_contexts_in_process: u32,
    active_tabs_total: u32,
    active_tabs_in_session: u32,
    queued_executions: u32,
    completed_executions_since_recycle: u32,
}

fn canonicalize(value: &mut Value, parent_key: Option<&str>) {
    match value {
        Value::Array(values) => {
            for value in values.iter_mut() {
                canonicalize(value, None);
            }
            if parent_key.is_some_and(is_unordered_array) {
                values.sort_by_key(Value::to_string);
            }
        }
        Value::Object(object) => {
            let previous = mem::take(object);
            let mut entries: Vec<_> = previous.into_iter().collect();
            entries.sort_by(|left, right| left.0.cmp(&right.0));
            let mut ordered = Map::new();
            for (key, mut child) in entries {
                canonicalize(&mut child, Some(&key));
                ordered.insert(key, child);
            }
            *object = ordered;
        }
        Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => {}
    }
}

const fn is_unordered_array(key: &str) -> bool {
    matches!(key.as_bytes(), b"artifacts" | b"outputs" | b"relationships")
}

fn redact_volatile_identity_fields(value: &mut Value) {
    match value {
        Value::Array(values) => {
            for value in values {
                redact_volatile_identity_fields(value);
            }
        }
        Value::Object(object) => {
            for key in [
                "capture_id",
                "activity_id",
                "artifact_id",
                "local_id",
                "frame_id",
                "started_at",
                "finished_at",
                "generated_at",
                "inputs",
                "derived_from",
                "relationships",
            ] {
                object.remove(key);
            }
            if is_artifact_record(object) || is_activity_or_capture_receipt(object) {
                object.remove("id");
            }
            for child in object.values_mut() {
                redact_volatile_identity_fields(child);
            }
        }
        Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => {}
    }
}

fn is_artifact_record(object: &Map<String, Value>) -> bool {
    object.contains_key("availability") && object.contains_key("provenance")
}

fn is_activity_or_capture_receipt(object: &Map<String, Value>) -> bool {
    object.contains_key("receipt")
        || (object.contains_key("operation")
            && object.contains_key("producer")
            && object.contains_key("outcome"))
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::canonicalize;

    #[test]
    fn canonicalization_sorts_relationships_and_nested_unicode_keys() {
        let mut value = json!({
            "z": {"é": "é", "a": 1},
            "relationships": [
                {"relation": "visual", "z": 2},
                {"relation": "accessibility", "a": 1}
            ]
        });

        canonicalize(&mut value, None);

        assert_eq!(
            value.to_string(),
            r#"{"relationships":[{"a":1,"relation":"accessibility"},{"relation":"visual","z":2}],"z":{"a":1,"é":"é"}}"#
        );
    }
}
