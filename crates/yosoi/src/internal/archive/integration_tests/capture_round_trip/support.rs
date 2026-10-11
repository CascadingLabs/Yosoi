#![allow(
    dead_code,
    clippy::indexing_slicing,
    reason = "shared fixture helpers mutate a checked-in Web Capture JSON shape"
)]

use std::error::Error;
use std::path::{Path, PathBuf};

use crate::internal::archive::CaptureArchiveRef;
use crate::internal::types::Sha256Digest;
use crate::internal::web_capture::{CaptureBundle, WebArtifactRef, WebCapture, WebCaptureWire};
use serde_json::{Value, json};

pub const BINARY_BYTES: &[u8] = &[0, 159, 255, 10];
pub const EMPTY_BYTES: &[u8] = &[];
pub const TRUNCATED_BYTES: &[u8] = b"abc";

type TestResult<T> = Result<T, Box<dyn Error>>;

#[derive(Clone, Copy)]
enum PayloadState {
    Retained(&'static [u8]),
    Truncated(&'static [u8]),
    Discarded,
    Unavailable,
}

pub fn mixed_bundle() -> TestResult<CaptureBundle> {
    let capture = mixed_capture()?;
    let references = source_references(&capture);
    let mut builder = CaptureBundle::builder(capture);
    for reference in references {
        match reference.as_untyped().artifact_id().get() {
            1 => builder.insert(reference, BINARY_BYTES.to_vec())?,
            2 => builder.insert(reference, EMPTY_BYTES.to_vec())?,
            3 => builder.insert(reference, TRUNCATED_BYTES.to_vec())?,
            _ => {}
        }
    }
    Ok(builder.finalize()?)
}

pub fn mixed_capture() -> TestResult<WebCapture> {
    let mut fixture: Value = serde_json::from_slice(include_bytes!(
        "../../../web_capture/integration_tests/fixtures/web-capture/complete-v1.json"
    ))?;
    let base = fixture["capture"]["artifacts"]["results"]["source"]["artifacts"][0].clone();
    let definitions = [
        (1_u32, PayloadState::Retained(BINARY_BYTES)),
        (2_u32, PayloadState::Retained(EMPTY_BYTES)),
        (3_u32, PayloadState::Truncated(TRUNCATED_BYTES)),
        (4_u32, PayloadState::Discarded),
        (5_u32, PayloadState::Unavailable),
    ];
    let mut artifacts = Vec::new();
    let mut outputs = Vec::new();
    for (id, state) in definitions {
        let artifact = configured_artifact(&base, id, state);
        outputs.push(artifact["record"].clone());
        artifacts.push(artifact);
    }
    fixture["capture"]["artifacts"]["results"]["source"] = json!({
        "status": "partial",
        "artifacts": artifacts,
        "reason": "archive.fixture-partial"
    });
    fixture["capture"]["acquisition"]["receipt"]["receipt"]["outputs"] = Value::Array(outputs);
    fixture["capture"]["completeness"] = json!("incomplete");
    let capture = WebCaptureWire::from_json(&serde_json::to_vec(&fixture)?)?;
    let canonical = WebCaptureWire::to_canonical_json(&capture)?;
    Ok(WebCaptureWire::from_json(&canonical)?)
}

fn configured_artifact(base: &Value, id: u32, state: PayloadState) -> Value {
    let mut artifact = base.clone();
    artifact["record"]["id"] = json!(id);
    match state {
        PayloadState::Retained(bytes) => {
            artifact["extent"] = json!({
                "status": "complete",
                "retained_bytes": bytes.len()
            });
            configure_record(&mut artifact["record"], "retained", None, Some(bytes));
        }
        PayloadState::Truncated(bytes) => {
            artifact["extent"] = json!({
                "status": "truncated",
                "retained_bytes": bytes.len(),
                "complete_bytes": {
                    "status": "known",
                    "value": bytes.len().saturating_add(2)
                }
            });
            configure_record(
                &mut artifact["record"],
                "truncated",
                Some("capture.byte-limit"),
                Some(bytes),
            );
        }
        PayloadState::Discarded => {
            artifact["extent"] = json!({
                "status": "discarded",
                "observed_bytes": { "status": "known", "value": 4 }
            });
            configure_record(
                &mut artifact["record"],
                "discarded",
                Some("capture.policy-discarded"),
                None,
            );
        }
        PayloadState::Unavailable => {
            artifact["extent"] = json!({ "status": "unavailable" });
            configure_record(
                &mut artifact["record"],
                "unavailable",
                Some("capture.body-unavailable"),
                None,
            );
        }
    }
    artifact
}

fn configure_record(
    record: &mut Value,
    availability: &str,
    reason: Option<&str>,
    bytes: Option<&[u8]>,
) {
    record["availability"] = json!(availability);
    record["availability_reason"] = reason.map_or(Value::Null, |value| json!(value));
    record["content_digest"] = bytes.map_or(Value::Null, |value| {
        json!(Sha256Digest::digest(value).to_string())
    });
}

pub fn source_references(capture: &WebCapture) -> Vec<WebArtifactRef> {
    capture
        .artifacts()
        .results()
        .source()
        .artifacts()
        .into_iter()
        .flatten()
        .map(|artifact| artifact.reference().into())
        .collect()
}

pub fn payload_path(root: &Path, reference: &CaptureArchiveRef, artifact_id: u32) -> PathBuf {
    let capture = reference.capture_id().to_string();
    let shard = capture.chars().take(2).collect::<String>();
    root.join("archive/v1/captures")
        .join(shard)
        .join(capture)
        .join("payloads")
        .join(format!("{artifact_id}.bin"))
}

pub fn record_path(root: &Path, reference: &CaptureArchiveRef) -> PathBuf {
    let capture = reference.capture_id().to_string();
    let shard = capture.chars().take(2).collect::<String>();
    root.join("archive/v1/records/capture")
        .join(shard)
        .join(format!("{capture}.json"))
}
