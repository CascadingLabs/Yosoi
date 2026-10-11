#![allow(
    dead_code,
    clippy::indexing_slicing,
    clippy::unwrap_used,
    reason = "deterministic conformance fixture assertions"
)]

use super::capture_bundle_support as bundle_fixture;

use crate::internal::web_capture::{
    BoundedAcquisitionLifecycle, ByteCount, ByteLimit, CaptureBundle, CaptureDeadline,
    CaptureOffset, EventAdmission, LifecycleEvent, ObservationLimits, ObservationPolicy,
    SettlementPolicy, WebArtifactRef, WebCaptureWire,
};
use bundle_fixture::{FIRST_BYTES, FirstPayloadState, SECOND_BYTES, capture, source_references};
use serde::{Deserialize, Serialize};
use std::{
    env, fs,
    path::{Path, PathBuf},
    process::{Command, id as process_id},
    time::{SystemTime, UNIX_EPOCH},
};

#[derive(Serialize, Deserialize)]
struct PayloadFile {
    reference: WebArtifactRef,
    file: String,
}

struct TempDirectory(PathBuf);
impl TempDirectory {
    fn new(label: &str) -> Self {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path = env::temp_dir().join(format!("yosoi-cas308-{label}-{}-{nonce}", process_id()));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
}
impl Drop for TempDirectory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn write_handoff(directory: &Path) {
    let capture = capture(FirstPayloadState::Retained);
    let references = source_references(&capture);
    let mut builder = CaptureBundle::builder(capture);
    builder
        .insert(references[1], SECOND_BYTES.to_vec())
        .unwrap();
    builder.insert(references[0], FIRST_BYTES.to_vec()).unwrap();
    let bundle = builder.finalize().unwrap();
    fs::write(
        directory.join("capture.json"),
        WebCaptureWire::to_canonical_json(bundle.capture()).unwrap(),
    )
    .unwrap();
    let mut index = Vec::new();
    for (position, (reference, bytes)) in bundle.payloads().enumerate() {
        let file = format!("payload-{position}.bin");
        fs::write(directory.join(&file), bytes).unwrap();
        index.push(PayloadFile { reference, file });
    }
    fs::write(
        directory.join("index.json"),
        serde_json::to_vec(&index).unwrap(),
    )
    .unwrap();
}

fn receive_handoff(directory: &Path) -> Result<(), String> {
    let metadata = fs::read(directory.join("capture.json")).map_err(|error| error.to_string())?;
    let capture = WebCaptureWire::from_json(&metadata).map_err(|error| error.to_string())?;
    let canonical =
        WebCaptureWire::to_canonical_json(&capture).map_err(|error| error.to_string())?;
    if canonical != metadata {
        return Err("metadata is not canonical".into());
    }
    let index: Vec<PayloadFile> = serde_json::from_slice(
        &fs::read(directory.join("index.json")).map_err(|error| error.to_string())?,
    )
    .map_err(|error| error.to_string())?;
    let mut builder = CaptureBundle::builder(capture);
    for entry in index {
        let bytes = fs::read(directory.join(entry.file)).map_err(|error| error.to_string())?;
        builder
            .insert(entry.reference, bytes)
            .map_err(|error| error.to_string())?;
    }
    let bundle = builder.finalize().map_err(|error| error.to_string())?;
    for (reference, bytes) in bundle.payloads() {
        if bundle.payload(reference) != Some(bytes) {
            return Err("payload lookup mismatch".into());
        }
    }
    Ok(())
}

fn subprocess_case(label: &str, mutate: impl FnOnce(&Path), expect_success: bool) {
    if let Some(directory) = env::var_os("YOSOI_CAS308_RECEIVER") {
        assert!(
            receive_handoff(Path::new(&directory)).is_ok(),
            "receiver rejected handoff"
        );
        return;
    }
    let directory = TempDirectory::new(label);
    write_handoff(&directory.0);
    mutate(&directory.0);
    let test_name =
        format!("internal::web_capture::integration_tests::acquisition_conformance::{label}");
    let status = Command::new(env::current_exe().unwrap())
        .arg("--exact")
        .arg(test_name)
        .arg("--nocapture")
        .env("YOSOI_CAS308_RECEIVER", &directory.0)
        .status()
        .unwrap();
    assert_eq!(status.success(), expect_success);
}

#[test]
fn durable_handoff_reconstructs_exact_bundle_in_subprocess() {
    subprocess_case(
        "durable_handoff_reconstructs_exact_bundle_in_subprocess",
        |_| {},
        true,
    );
}
#[test]
fn durable_handoff_rejects_tampered_metadata_in_subprocess() {
    subprocess_case(
        "durable_handoff_rejects_tampered_metadata_in_subprocess",
        |dir| {
            let path = dir.join("capture.json");
            let mut bytes = fs::read(&path).unwrap();
            bytes[0] = b'!';
            fs::write(path, bytes).unwrap();
        },
        false,
    );
}
#[test]
fn durable_handoff_rejects_tampered_payload_in_subprocess() {
    subprocess_case(
        "durable_handoff_rejects_tampered_payload_in_subprocess",
        |dir| {
            let path = dir.join("payload-0.bin");
            let mut bytes = fs::read(&path).unwrap();
            bytes[0] ^= 1;
            fs::write(path, bytes).unwrap();
        },
        false,
    );
}
#[test]
fn durable_handoff_rejects_missing_payload_in_subprocess() {
    subprocess_case(
        "durable_handoff_rejects_missing_payload_in_subprocess",
        |dir| {
            fs::remove_file(dir.join("payload-0.bin")).unwrap();
        },
        false,
    );
}

#[test]
fn provider_neutral_core_enforces_deadline_and_exact_accounting() {
    let capture = capture(FirstPayloadState::Retained);
    let limits = ObservationLimits::new(
        CaptureDeadline::try_from(100).unwrap(),
        None,
        Some(ByteLimit::try_from(5_u64).unwrap()),
    );
    let policy = ObservationPolicy::new(limits, SettlementPolicy::Disabled);
    let started_at = capture
        .acquisition()
        .receipt()
        .receipt()
        .started_at()
        .to_owned();
    let mut lifecycle = BoundedAcquisitionLifecycle::start(capture.id(), policy, started_at);
    let event = LifecycleEvent::new(
        CaptureOffset::from_microseconds(10),
        ByteCount::new(9),
        ByteCount::new(4),
        true,
    )
    .unwrap();
    assert!(
        matches!(lifecycle.admit(event).unwrap(), EventAdmission::AdmittedAndStopped { admitted, .. } if admitted.admitted_bytes().get() == 5 && admitted.retained_bytes().get() == 4)
    );
    assert_eq!(lifecycle.dropped_counts(), (0, 1));
}

#[test]
fn physical_provider_neutral_modules_do_not_depend_on_providers() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("src/internal/web_capture");
    let neutral = [
        "bounded_acquisition.rs",
        "bundle.rs",
        "capture.rs",
        "wire.rs",
        "artifact/mod.rs",
        "artifact/family.rs",
        "observation/mod.rs",
    ];
    let forbidden = [
        "crate::direct_http",
        "direct_http::",
        "direct_http_spec",
        "direct_http_orchestration",
        "wreq",
        "PendingDirectHttpResponse",
        "DirectHttpResponseFacts",
        "VoidCrawl",
        "browser::",
    ];
    for relative in neutral {
        let source = fs::read_to_string(root.join(relative)).unwrap();
        for dependency in forbidden {
            assert!(
                !source.contains(dependency),
                "neutral module {relative} contains forbidden dependency {dependency}"
            );
        }
    }
}
