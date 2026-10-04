#![allow(
    clippy::indexing_slicing,
    reason = "fixture mutation uses a checked-in, schema-certified Web Capture document"
)]

#[path = "capture_round_trip/support.rs"]
mod support;

use std::env;
use std::error::Error;
use std::ffi::OsString;
use std::fs;
use std::path::Path;
use std::process::Command;

use serde_json::{Value, json};
use tempfile::tempdir;
use tokio::runtime::Builder;
use yosoi_archive::{Archive, ArchiveError, CaptureArchiveRef, MAX_CAPTURE_MATERIALIZED_BYTES};
use yosoi_web_capture::WebArtifactFamily;

use support::{BINARY_BYTES, mixed_bundle, payload_path, record_path, source_references};

const CHILD_ROLE: &str = "YOSOI_CAPTURE_ARCHIVE_CHILD_ROLE";
const CHILD_ROOT: &str = "YOSOI_CAPTURE_ARCHIVE_CHILD_ROOT";
const CHILD_REFERENCE: &str = "YOSOI_CAPTURE_ARCHIVE_CHILD_REFERENCE";

#[tokio::test]
async fn mixed_capture_round_trips_exact_retained_payloads_only() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let root = temporary.path().join(".yosoi");
    let expected = mixed_bundle()?;
    let expected_id = expected.capture().id();
    let archive = Archive::open(&root).await?;
    let reference = archive.write(&expected).await?;
    if reference.capture_id() != expected_id {
        return Err("Capture reference did not preserve CaptureId".into());
    }
    drop(archive);

    let archive = Archive::open(&root).await?;
    let reopened = archive.read(&reference).await?;
    if reopened != expected {
        return Err("reopened CaptureBundle differs from exact archived evidence".into());
    }
    for id in [1_u32, 2, 3] {
        if !payload_path(&root, &reference, id).is_file() {
            return Err(format!("retained payload {id} was not archived").into());
        }
    }
    for id in [4_u32, 5] {
        if payload_path(&root, &reference, id).exists() {
            return Err(format!("non-retained payload {id} was archived").into());
        }
    }
    if fs::read(payload_path(&root, &reference, 1))? != BINARY_BYTES {
        return Err("binary payload bytes changed on disk".into());
    }
    if !fs::read(payload_path(&root, &reference, 2))?.is_empty() {
        return Err("zero-byte retained payload was not preserved".into());
    }
    Ok(())
}

#[tokio::test]
async fn missing_wrong_length_and_wrong_digest_are_distinct() -> Result<(), Box<dyn Error>> {
    assert_payload_failure(PayloadCorruption::Missing).await?;
    assert_payload_failure(PayloadCorruption::WrongLength).await?;
    assert_payload_failure(PayloadCorruption::WrongDigest).await
}

#[derive(Clone, Copy)]
enum PayloadCorruption {
    Missing,
    WrongLength,
    WrongDigest,
}

async fn assert_payload_failure(corruption: PayloadCorruption) -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let root = temporary.path().join(".yosoi");
    let archive = Archive::open(&root).await?;
    let bundle = mixed_bundle()?;
    let reference = archive.write(&bundle).await?;
    let path = payload_path(&root, &reference, 1);
    match corruption {
        PayloadCorruption::Missing => fs::remove_file(&path)?,
        PayloadCorruption::WrongLength => fs::write(&path, b"x")?,
        PayloadCorruption::WrongDigest => fs::write(&path, [1_u8, 2, 3, 4])?,
    }
    let result = archive.read(&reference).await;
    let expected = match corruption {
        PayloadCorruption::Missing => {
            matches!(&result, Err(ArchiveError::CapturePayloadMissing { .. }))
        }
        PayloadCorruption::WrongLength => matches!(
            &result,
            Err(ArchiveError::CapturePayloadLengthMismatch { .. })
        ),
        PayloadCorruption::WrongDigest => matches!(
            &result,
            Err(ArchiveError::CapturePayloadDigestMismatch { .. })
        ),
    };
    if !expected {
        return Err(format!("Capture payload corruption returned {result:?}").into());
    }
    Ok(())
}

#[tokio::test]
async fn wrong_family_and_corrupt_metadata_fail_before_payload_materialization()
-> Result<(), Box<dyn Error>> {
    assert_metadata_failure(MetadataCorruption::WrongFamily).await?;
    assert_metadata_failure(MetadataCorruption::InvalidDigest).await
}

#[derive(Clone, Copy)]
enum MetadataCorruption {
    WrongFamily,
    InvalidDigest,
}

async fn assert_metadata_failure(corruption: MetadataCorruption) -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let root = temporary.path().join(".yosoi");
    let archive = Archive::open(&root).await?;
    let bundle = mixed_bundle()?;
    let reference = archive.write(&bundle).await?;
    let path = record_path(&root, &reference);
    let mut record: Value = serde_json::from_slice(&fs::read(&path)?)?;
    match corruption {
        MetadataCorruption::WrongFamily => {
            let source = &mut record["value"]["web_capture"]["capture"]["artifacts"]["results"]["source"]
                ["artifacts"];
            let artifacts = source
                .as_array_mut()
                .ok_or("source artifacts must be an array")?;
            let artifact = artifacts.remove(0);
            record["value"]["web_capture"]["capture"]["artifacts"]["results"]["rendered_dom"] = json!({
                "status": "complete",
                "artifacts": [artifact]
            });
        }
        MetadataCorruption::InvalidDigest => {
            record["value"]["web_capture"]["capture"]["artifacts"]["results"]["source"]["artifacts"]
                [0]["record"]["content_digest"] = json!("not-a-sha256");
        }
    }
    fs::write(&path, serde_json::to_vec(&record)?)?;
    if !matches!(
        archive.read(&reference).await,
        Err(ArchiveError::InvalidWebCapture(_))
    ) {
        return Err("invalid or wrong-family capture metadata was accepted".into());
    }
    Ok(())
}

#[tokio::test]
async fn manifest_family_is_the_only_payload_family_authority() -> Result<(), Box<dyn Error>> {
    let bundle = mixed_bundle()?;
    let references = source_references(bundle.capture());
    if references
        .iter()
        .any(|reference| reference.family() != WebArtifactFamily::Source)
    {
        return Err("fixture source manifest produced a foreign payload family".into());
    }
    let temporary = tempdir()?;
    let archive = Archive::open(temporary.path().join(".yosoi")).await?;
    let reference = archive.write(&bundle).await?;
    if archive.read(&reference).await? != bundle {
        return Err("Archive did not reconstruct payload families from the manifest".into());
    }
    Ok(())
}

#[tokio::test]
async fn aggregate_materialization_bound_fails_before_payload_read() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let root = temporary.path().join(".yosoi");
    let archive = Archive::open(&root).await?;
    let bundle = mixed_bundle()?;
    let reference = archive.write(&bundle).await?;
    let payload = payload_path(&root, &reference, 1);
    fs::remove_file(&payload)?;

    let path = record_path(&root, &reference);
    let mut record: Value = serde_json::from_slice(&fs::read(&path)?)?;
    let artifacts = record
        .pointer_mut("/value/web_capture/capture/artifacts/results/source/artifacts")
        .and_then(Value::as_array_mut)
        .ok_or("source artifacts must be an array")?;
    let artifact = artifacts
        .iter_mut()
        .find(|artifact| artifact.pointer("/record/id").and_then(Value::as_u64) == Some(1))
        .ok_or("retained source artifact must exist")?;
    artifact["extent"]["retained_bytes"] = json!(MAX_CAPTURE_MATERIALIZED_BYTES.saturating_add(1));
    fs::write(&path, serde_json::to_vec(&record)?)?;

    let result = archive.read(&reference).await;
    if !matches!(
        result,
        Err(ArchiveError::CaptureMaterializationTooLarge { .. })
    ) {
        return Err(format!(
            "Capture aggregate bound did not fail before missing payload resolution: {result:?}"
        )
        .into());
    }
    Ok(())
}

#[test]
fn capture_round_trip_crosses_real_process_boundaries() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let root = temporary.path().join(".yosoi");
    let reference_path = temporary.path().join("capture-ref.txt");
    run_child("subprocess_capture_writer", "write", &root, &reference_path)?;
    run_child("subprocess_capture_reader", "read", &root, &reference_path)
}

fn run_child(
    test_name: &str,
    role: &str,
    root: &Path,
    reference: &Path,
) -> Result<(), Box<dyn Error>> {
    let status = Command::new(env::current_exe()?)
        .args(["--ignored", "--exact", test_name, "--nocapture"])
        .env(CHILD_ROLE, role)
        .env(CHILD_ROOT, root)
        .env(CHILD_REFERENCE, reference)
        .status()?;
    if !status.success() {
        return Err(format!("Capture Archive child {role} failed with {status}").into());
    }
    Ok(())
}

#[test]
#[ignore = "invoked by capture_round_trip_crosses_real_process_boundaries"]
fn subprocess_capture_writer() -> Result<(), Box<dyn Error>> {
    require_role("write")?;
    let runtime = Builder::new_current_thread().enable_all().build()?;
    let root = required_os(CHILD_ROOT)?;
    let bundle = mixed_bundle()?;
    let reference = runtime.block_on(async {
        let archive = Archive::open(root).await?;
        archive.write(&bundle).await
    })?;
    fs::write(required_os(CHILD_REFERENCE)?, reference.to_string())?;
    Ok(())
}

#[test]
#[ignore = "invoked by capture_round_trip_crosses_real_process_boundaries"]
fn subprocess_capture_reader() -> Result<(), Box<dyn Error>> {
    require_role("read")?;
    let reference: CaptureArchiveRef =
        fs::read_to_string(required_os(CHILD_REFERENCE)?)?.parse()?;
    let runtime = Builder::new_current_thread().enable_all().build()?;
    let root = required_os(CHILD_ROOT)?;
    let reopened = runtime.block_on(async {
        let archive = Archive::open(root).await?;
        archive.read(&reference).await
    })?;
    if reopened != mixed_bundle()? {
        return Err("fresh process reopened different CaptureBundle evidence".into());
    }
    Ok(())
}

fn require_role(expected: &str) -> Result<(), Box<dyn Error>> {
    let observed = env::var(CHILD_ROLE)?;
    if observed != expected {
        return Err(format!("expected child role {expected}, found {observed}").into());
    }
    Ok(())
}

fn required_os(name: &str) -> Result<OsString, Box<dyn Error>> {
    env::var_os(name).ok_or_else(|| format!("missing child environment {name}").into())
}
