use std::error::Error;
use std::fs;
use std::fs::OpenOptions as StdOpenOptions;
#[cfg(unix)]
use std::os::unix::fs::{PermissionsExt as _, symlink};
use std::path::Path;

use crate::internal::archive::{Archive, ArchiveError, PolicyArchiveRef};
use tempfile::tempdir;

use super::{ensure_equal, non_default_policy, policy_record_path};

#[tokio::test]
async fn missing_corrupt_and_future_records_fail_with_typed_errors() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let root = temporary.path().join(".yosoi");
    let archive = Archive::open(&root).await?;

    let missing: PolicyArchiveRef = "policy:v1:123e4567-e89b-42d3-a456-426614174000".parse()?;
    if !matches!(
        archive.read(&missing).await,
        Err(ArchiveError::RecordNotFound { .. })
    ) {
        return Err("missing Policy did not return RecordNotFound".into());
    }

    let future: PolicyArchiveRef = "policy:v2:123e4567-e89b-42d3-a456-426614174000".parse()?;
    if !matches!(
        archive.read(&future).await,
        Err(ArchiveError::UnsupportedFormat {
            found: 2,
            supported: 1
        })
    ) {
        return Err("future reference did not return UnsupportedFormat".into());
    }

    let reference = archive.write(&non_default_policy()?).await?;
    fs::write(policy_record_path(&root, &reference), b"{")?;
    if !matches!(
        archive.read(&reference).await,
        Err(ArchiveError::MalformedEnvelope(_))
    ) {
        return Err("corrupt Policy did not return MalformedEnvelope".into());
    }
    Ok(())
}

#[tokio::test]
async fn leftover_staging_is_invisible_and_not_deleted_on_open() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let root = temporary.path().join(".yosoi");
    let policy = non_default_policy()?;
    let archive = Archive::open(&root).await?;
    let reference = archive.write(&policy).await?;
    let staged_reference: PolicyArchiveRef =
        "policy:v1:123e4567-e89b-42d3-a456-426614174000".parse()?;
    let mut staged_record: serde_json::Value =
        serde_json::from_slice(&fs::read(policy_record_path(&root, &reference))?)?;
    set_top_level(
        &mut staged_record,
        "key",
        serde_json::json!(staged_reference.logical_key()),
    )?;
    let staged = root
        .join("archive/v1/staging")
        .join("interrupted-record.json.tmp");
    write_json(&staged, &staged_record)?;
    if !matches!(
        archive.read(&staged_reference).await,
        Err(ArchiveError::RecordNotFound { .. })
    ) {
        return Err("complete staged record became visible before publication".into());
    }
    drop(archive);

    let reopened = Archive::open(&root).await?;
    ensure_equal(
        &reopened.read(&reference).await?,
        &policy,
        "leftover staging affected the committed Policy",
    )?;
    if !staged.is_file() {
        return Err("Archive::open silently removed leftover staging".into());
    }
    Ok(())
}

#[tokio::test]
async fn public_read_checks_each_header_field_before_policy_decode() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let root = temporary.path().join(".yosoi");
    let archive = Archive::open(&root).await?;
    let reference = archive.write(&non_default_policy()?).await?;
    let path = policy_record_path(&root, &reference);
    let original: serde_json::Value = serde_json::from_slice(&fs::read(&path)?)?;

    let mut changed = original.clone();
    set_top_level(&mut changed, "format_version", serde_json::json!(2))?;
    set_top_level(
        &mut changed,
        "value",
        serde_json::json!({"not": "a policy"}),
    )?;
    write_json(&path, &changed)?;
    if !matches!(
        archive.read(&reference).await,
        Err(ArchiveError::UnsupportedFormat { found: 2, .. })
    ) {
        return Err("public read did not reject the envelope format first".into());
    }

    changed = original.clone();
    set_top_level(&mut changed, "kind", serde_json::json!("capture"))?;
    set_top_level(
        &mut changed,
        "value",
        serde_json::json!({"not": "a policy"}),
    )?;
    write_json(&path, &changed)?;
    if !matches!(
        archive.read(&reference).await,
        Err(ArchiveError::WrongRecordKind { .. })
    ) {
        return Err("public read did not reject the record kind before Policy decoding".into());
    }

    changed = original.clone();
    set_top_level(&mut changed, "schema_version", serde_json::json!(4))?;
    set_top_level(
        &mut changed,
        "value",
        serde_json::json!({"not": "a policy"}),
    )?;
    write_json(&path, &changed)?;
    match archive.read(&reference).await {
        Err(ArchiveError::MigrationRequired {
            found_schema: 4,
            supported_schema: 3,
            writer_package,
            writer_version,
            ..
        }) if writer_package == "yosoi-archive" && writer_version == env!("CARGO_PKG_VERSION") => {}
        other => {
            return Err(format!(
                "public read lost migration provenance or decoded the Policy first: {other:?}"
            )
            .into());
        }
    }

    changed = original.clone();
    set_top_level(&mut changed, "schema_version", serde_json::json!(2))?;
    set_top_level(
        &mut changed,
        "value",
        serde_json::json!({"not": "a policy"}),
    )?;
    write_json(&path, &changed)?;
    if !matches!(
        archive.read(&reference).await,
        Err(ArchiveError::MigrationRequired {
            found_schema: 2,
            supported_schema: 3,
            ..
        })
    ) {
        return Err("schema-2 Policy record reached the schema-3 decoder".into());
    }

    changed = original.clone();
    set_top_level(
        &mut changed,
        "key",
        serde_json::json!("123e4567-e89b-42d3-a456-426614174000"),
    )?;
    set_top_level(
        &mut changed,
        "value",
        serde_json::json!({"not": "a policy"}),
    )?;
    write_json(&path, &changed)?;
    if !matches!(
        archive.read(&reference).await,
        Err(ArchiveError::WrongRecordKey { .. })
    ) {
        return Err("public read did not reject the record key before Policy decoding".into());
    }

    changed = original;
    let value = changed
        .pointer_mut("/value/policy")
        .and_then(serde_json::Value::as_object_mut)
        .ok_or("Policy archive record must contain an authored Policy object")?;
    let request = value
        .get_mut("request")
        .and_then(serde_json::Value::as_object_mut)
        .ok_or("Policy request must be an object")?;
    request.insert("maximum_elapsed".to_owned(), serde_json::json!(0));
    write_json(&path, &changed)?;
    if !matches!(
        archive.read(&reference).await,
        Err(ArchiveError::InvalidRecordValue { kind: "policy", .. })
    ) {
        return Err("current-schema invalid Policy bypassed domain validation".into());
    }
    Ok(())
}

#[tokio::test]
async fn record_bounds_and_non_regular_files_fail_before_decode() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let root = temporary.path().join(".yosoi");
    let archive = Archive::open(&root).await?;
    let reference = archive.write(&non_default_policy()?).await?;
    let path = policy_record_path(&root, &reference);

    StdOpenOptions::new()
        .write(true)
        .open(&path)?
        .set_len(16_777_217)?;
    if !matches!(
        archive.read(&reference).await,
        Err(ArchiveError::RecordTooLarge {
            maximum: 16_777_216,
            observed: 16_777_217
        })
    ) {
        return Err("oversized record was not rejected before decoding".into());
    }

    fs::remove_file(&path)?;
    fs::create_dir(&path)?;
    if !matches!(
        archive.read(&reference).await,
        Err(ArchiveError::NotRegularFile { .. })
    ) {
        return Err("record directory was not rejected as non-regular".into());
    }
    Ok(())
}

#[cfg(unix)]
#[tokio::test]
async fn record_symlink_is_rejected_without_following_it() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let root = temporary.path().join(".yosoi");
    let archive = Archive::open(&root).await?;
    let reference = archive.write(&non_default_policy()?).await?;
    let path = policy_record_path(&root, &reference);
    let foreign = temporary.path().join("foreign.json");
    fs::write(&foreign, b"foreign")?;
    fs::remove_file(&path)?;
    symlink(&foreign, &path)?;

    if !matches!(
        archive.read(&reference).await,
        Err(ArchiveError::UnsafeArchivePath { .. })
    ) {
        return Err("record symlink was followed or returned an untyped failure".into());
    }
    Ok(())
}

#[cfg(unix)]
#[tokio::test]
async fn shared_root_may_be_permissive_but_archive_subtree_must_be_private()
-> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let root = temporary.path().join(".yosoi");
    fs::create_dir(&root)?;
    fs::set_permissions(&root, fs::Permissions::from_mode(0o755))?;
    Archive::open(&root).await?;

    let other_root = temporary.path().join("other-yosoi");
    fs::create_dir(&other_root)?;
    fs::set_permissions(&other_root, fs::Permissions::from_mode(0o755))?;
    let archive_root = other_root.join("archive");
    fs::create_dir(&archive_root)?;
    fs::set_permissions(&archive_root, fs::Permissions::from_mode(0o755))?;
    if !matches!(
        Archive::open(&other_root).await,
        Err(ArchiveError::InsecurePermissions { mode: 0o755, .. })
    ) {
        return Err("permissive Archive-owned subtree was accepted".into());
    }
    Ok(())
}

fn set_top_level(
    value: &mut serde_json::Value,
    key: &str,
    replacement: serde_json::Value,
) -> Result<(), Box<dyn Error>> {
    let object = value
        .as_object_mut()
        .ok_or("Archive envelope must be an object")?;
    object.insert(key.to_owned(), replacement);
    Ok(())
}

fn write_json(path: &Path, value: &serde_json::Value) -> Result<(), Box<dyn Error>> {
    fs::write(path, serde_json::to_vec(value)?)?;
    Ok(())
}
