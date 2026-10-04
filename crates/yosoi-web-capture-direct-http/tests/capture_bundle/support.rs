use std::fs;

use serde_json::{Value, json};
use yosoi_types::{ActivityId, ArtifactId, Sha256Digest};
use yosoi_web_capture_direct_http::{WebArtifactRef, WebCapture, WebCaptureWire};

pub const FIRST_BYTES: &[u8] = b"first";
pub const SECOND_BYTES: &[u8] = b"second";
pub const TRUNCATED_BYTES: &[u8] = b"fir";

#[derive(Clone, Copy)]
pub enum FirstPayloadState {
    Retained,
    Zero,
    Truncated,
    Discarded,
    Unavailable,
}

pub fn capture(state: FirstPayloadState) -> WebCapture {
    let mut value = fixture_value("complete-v1.json");
    configure_first_artifact(&mut value, state);
    WebCaptureWire::from_json(&serde_json::to_vec(&value).unwrap()).unwrap()
}

pub fn empty_capture() -> WebCapture {
    WebCaptureWire::from_json(&fixture_bytes("minimal-v1.json")).unwrap()
}

pub fn wire_round_trip(capture: &WebCapture) -> WebCapture {
    let bytes = WebCaptureWire::to_canonical_json(capture).unwrap();
    WebCaptureWire::from_json(&bytes).unwrap()
}

pub fn source_references(capture: &WebCapture) -> Vec<WebArtifactRef> {
    capture
        .artifacts()
        .results()
        .source()
        .artifacts()
        .unwrap()
        .iter()
        .map(|artifact| artifact.reference().into())
        .collect()
}

pub fn orphan_reference(capture: &WebCapture) -> WebArtifactRef {
    let activity_id = capture.id().activity_id();
    serde_json::from_value(json!({
        "family": "source",
        "reference": {
            "activity_id": activity_id,
            "artifact_id": 99
        }
    }))
    .unwrap()
}

pub fn family_mismatch_reference(capture: &WebCapture) -> WebArtifactRef {
    let activity_id = capture.id().activity_id();
    serde_json::from_value(json!({
        "family": "rendered_dom",
        "reference": {
            "activity_id": activity_id,
            "artifact_id": 1
        }
    }))
    .unwrap()
}

pub fn foreign_source_reference() -> WebArtifactRef {
    serde_json::from_value(json!({
        "family": "source",
        "reference": {
            "activity_id": ActivityId::random(),
            "artifact_id": ArtifactId::try_from(1).unwrap()
        }
    }))
    .unwrap()
}

fn fixture_value(name: &str) -> Value {
    serde_json::from_slice(&fixture_bytes(name)).unwrap()
}

fn fixture_bytes(name: &str) -> Vec<u8> {
    let path = format!(
        "{}/tests/fixtures/web-capture/{name}",
        env!("CARGO_MANIFEST_DIR")
    );
    fs::read(path).unwrap()
}

fn configure_first_artifact(value: &mut Value, state: FirstPayloadState) {
    let artifact_index = value["capture"]["artifacts"]["results"]["source"]["artifacts"]
        .as_array()
        .unwrap()
        .iter()
        .position(|artifact| artifact["record"]["id"] == 1)
        .unwrap();
    let output_index = value["capture"]["acquisition"]["receipt"]["receipt"]["outputs"]
        .as_array()
        .unwrap()
        .iter()
        .position(|output| output["id"] == 1)
        .unwrap();

    let digest = match state {
        FirstPayloadState::Zero => Some(Sha256Digest::digest([]).to_string()),
        FirstPayloadState::Truncated => Some(Sha256Digest::digest(TRUNCATED_BYTES).to_string()),
        FirstPayloadState::Retained
        | FirstPayloadState::Discarded
        | FirstPayloadState::Unavailable => None,
    };

    {
        let artifact =
            &mut value["capture"]["artifacts"]["results"]["source"]["artifacts"][artifact_index];
        match state {
            FirstPayloadState::Retained => {}
            FirstPayloadState::Zero => {
                artifact["extent"] = json!({ "status": "complete", "retained_bytes": 0 });
                artifact["record"]["content_digest"] = json!(digest.as_deref());
            }
            FirstPayloadState::Truncated => {
                artifact["extent"] = json!({
                    "status": "truncated",
                    "retained_bytes": 3,
                    "complete_bytes": { "status": "known", "value": 5 }
                });
                configure_record(
                    &mut artifact["record"],
                    "truncated",
                    Some("capture.byte-limit"),
                    digest.as_deref(),
                );
            }
            FirstPayloadState::Discarded => {
                artifact["extent"] = json!({
                    "status": "discarded",
                    "observed_bytes": { "status": "known", "value": 5 }
                });
                configure_record(
                    &mut artifact["record"],
                    "discarded",
                    Some("capture.policy-discarded"),
                    None,
                );
            }
            FirstPayloadState::Unavailable => {
                artifact["extent"] = json!({ "status": "unavailable" });
                configure_record(
                    &mut artifact["record"],
                    "unavailable",
                    Some("capture.body-unavailable"),
                    None,
                );
            }
        }
    }

    if !matches!(state, FirstPayloadState::Retained) {
        let output =
            &mut value["capture"]["acquisition"]["receipt"]["receipt"]["outputs"][output_index];
        match state {
            FirstPayloadState::Zero => {
                output["content_digest"] = json!(digest.as_deref());
            }
            FirstPayloadState::Truncated => {
                configure_record(
                    output,
                    "truncated",
                    Some("capture.byte-limit"),
                    digest.as_deref(),
                );
            }
            FirstPayloadState::Discarded => {
                configure_record(output, "discarded", Some("capture.policy-discarded"), None);
            }
            FirstPayloadState::Unavailable => {
                configure_record(
                    output,
                    "unavailable",
                    Some("capture.body-unavailable"),
                    None,
                );
            }
            FirstPayloadState::Retained => {}
        }
    }

    if matches!(
        state,
        FirstPayloadState::Truncated
            | FirstPayloadState::Discarded
            | FirstPayloadState::Unavailable
    ) {
        value["capture"]["completeness"] = json!("incomplete");
    }
}

fn configure_record(record: &mut Value, status: &str, reason: Option<&str>, digest: Option<&str>) {
    record["availability"] = json!(status);
    record["availability_reason"] = reason.map_or(Value::Null, |value| json!(value));
    record["content_digest"] = digest.map_or(Value::Null, |value| json!(value));
}
