use std::env;
use std::error::Error;
use std::ffi::OsString;
use std::fmt::Debug;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use tempfile::tempdir;
use tokio::runtime::Builder;
use yosoi_archive::{Archive, ArchiveError, PolicyArchiveRef};
use yosoi_policy::policy::{Acquisition, DocumentRequest, Page};
use yosoi_policy::{CountLimit, Policy};

const CHILD_ROLE: &str = "YOSOI_ARCHIVE_CHILD_ROLE";
const CHILD_ROOT: &str = "YOSOI_ARCHIVE_CHILD_ROOT";
const CHILD_REFERENCE: &str = "YOSOI_ARCHIVE_CHILD_REFERENCE";

#[path = "policy_round_trip/integrity.rs"]
mod integrity;

fn non_default_policy() -> Result<Policy, yosoi_policy::PolicyError> {
    let mut policy = Policy::default();
    policy.locators.max_matches = CountLimit::try_from(42_u64)?;
    Ok(policy)
}

#[tokio::test]
async fn policy_write_drop_reopen_and_read_is_exact() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let root = temporary.path().join(".yosoi");
    let policy = non_default_policy()?;
    let archive = Archive::open(&root).await?;
    let reference = archive.write(&policy).await?;
    let serialized_reference = reference.to_string();
    drop(archive);

    let parsed: PolicyArchiveRef = serialized_reference.parse()?;
    let archive = Archive::open(&root).await?;
    ensure_equal(
        &archive.read(&parsed).await?,
        &policy,
        "reopened Policy differs from the written Policy",
    )?;

    let record: serde_json::Value =
        serde_json::from_slice(&fs::read(policy_record_path(&root, &parsed))?)?;
    ensure_equal(
        &record
            .get("schema_version")
            .and_then(serde_json::Value::as_u64),
        &Some(3),
        "new Policy record did not use schema v3",
    )?;
    if record.pointer("/value/effective_policy").is_none()
        || record.pointer("/value/effective_identity").is_none()
    {
        return Err("new Policy record omitted its resolved snapshot or identity".into());
    }
    ensure_equal(
        &record
            .get("writer")
            .and_then(|writer| writer.get("package"))
            .and_then(serde_json::Value::as_str),
        &Some(env!("CARGO_PKG_NAME")),
        "record writer package is not automatic",
    )?;
    ensure_equal(
        &record
            .get("writer")
            .and_then(|writer| writer.get("version"))
            .and_then(serde_json::Value::as_str),
        &Some(env!("CARGO_PKG_VERSION")),
        "record writer version is not automatic",
    )?;
    Ok(())
}

#[tokio::test]
async fn two_public_writes_create_two_immutable_snapshots() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let archive = Archive::open(temporary.path().join(".yosoi")).await?;
    let policy = non_default_policy()?;

    let first = archive.write(&policy).await?;
    let second = archive.write(&policy).await?;
    if first == second {
        return Err("two public writes reused one Archive-assigned reference".into());
    }
    ensure_equal(
        &archive.read(&first).await?,
        &policy,
        "first immutable Policy snapshot differs",
    )?;
    ensure_equal(
        &archive.read(&second).await?,
        &policy,
        "second immutable Policy snapshot differs",
    )?;
    Ok(())
}

#[tokio::test]
async fn authored_current_and_exact_policies_remain_distinct() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let archive = Archive::open(temporary.path().join(".yosoi")).await?;
    let current = Policy::default();
    let mut exact = current.clone();
    exact.page = Page::new(vec![
        Acquisition::DirectHttp.documents([DocumentRequest::ResponseDocument]),
    ])?;
    if current == exact {
        return Err("Current and Exact authored Policies unexpectedly compare equal".into());
    }
    ensure_equal(
        &current.effective_identity()?,
        &exact.effective_identity()?,
        "Current and Exact fixtures do not share effective behavior",
    )?;

    let current_ref = archive.write(&current).await?;
    let exact_ref = archive.write(&exact).await?;
    ensure_equal(
        &archive.read(&current_ref).await?,
        &current,
        "Current Policy authorship was lost",
    )?;
    ensure_equal(
        &archive.read(&exact_ref).await?,
        &exact,
        "Exact Policy authorship was lost",
    )?;
    Ok(())
}

#[tokio::test]
async fn invalid_policy_is_rejected_without_publishing() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let root = temporary.path().join(".yosoi");
    let archive = Archive::open(&root).await?;
    let mut invalid = Policy::default();
    invalid.page.acquisitions = vec![Acquisition::DirectHttp, Acquisition::DirectHttp];

    if !matches!(
        archive.write(&invalid).await,
        Err(ArchiveError::InvalidPolicy(_))
    ) {
        return Err("invalid authored Policy was not rejected with its typed error".into());
    }
    let record_count = fs::read_dir(root.join("archive/v1/records/policy"))?.count();
    if record_count != 0 {
        return Err("invalid authored Policy published a record or shard".into());
    }
    let staging_count = fs::read_dir(root.join("archive/v1/staging"))?.count();
    if staging_count != 0 {
        return Err("invalid authored Policy left staged bytes".into());
    }
    Ok(())
}

#[test]
fn policy_round_trip_crosses_real_process_boundaries() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let root = temporary.path().join(".yosoi");
    let reference_path = temporary.path().join("policy-ref.txt");

    run_child("subprocess_writer", "write", &root, &reference_path)?;
    run_child("subprocess_reader", "read", &root, &reference_path)?;
    Ok(())
}

fn run_child(
    test_name: &str,
    role: &str,
    root: &Path,
    reference_path: &Path,
) -> Result<(), Box<dyn Error>> {
    let status = Command::new(env::current_exe()?)
        .args(["--ignored", "--exact", test_name, "--nocapture"])
        .env(CHILD_ROLE, role)
        .env(CHILD_ROOT, root)
        .env(CHILD_REFERENCE, reference_path)
        .status()?;
    if !status.success() {
        return Err(format!("Archive child {role} failed with {status}").into());
    }
    Ok(())
}

#[test]
#[ignore = "invoked by policy_round_trip_crosses_real_process_boundaries"]
fn subprocess_writer() -> Result<(), Box<dyn Error>> {
    require_child_role("write")?;
    let root = required_os(CHILD_ROOT)?;
    let reference_path = required_os(CHILD_REFERENCE)?;
    let policy = non_default_policy()?;
    let runtime = Builder::new_current_thread().enable_all().build()?;
    let reference = runtime.block_on(async {
        let archive = Archive::open(root).await?;
        archive.write(&policy).await
    })?;
    fs::write(reference_path, reference.to_string())?;
    Ok(())
}

#[test]
#[ignore = "invoked by policy_round_trip_crosses_real_process_boundaries"]
fn subprocess_reader() -> Result<(), Box<dyn Error>> {
    require_child_role("read")?;
    let root = required_os(CHILD_ROOT)?;
    let reference_path = required_os(CHILD_REFERENCE)?;
    let reference: PolicyArchiveRef = fs::read_to_string(reference_path)?.parse()?;
    let runtime = Builder::new_current_thread().enable_all().build()?;
    let reopened = runtime.block_on(async {
        let archive = Archive::open(root).await?;
        archive.read(&reference).await
    })?;
    ensure_equal(
        &reopened,
        &non_default_policy()?,
        "reader subprocess reopened a different Policy",
    )?;
    Ok(())
}

fn require_child_role(expected: &str) -> Result<(), Box<dyn Error>> {
    let observed = env::var(CHILD_ROLE)?;
    if observed != expected {
        return Err(format!("expected child role {expected}, found {observed}").into());
    }
    Ok(())
}

fn required_os(name: &str) -> Result<OsString, Box<dyn Error>> {
    env::var_os(name).ok_or_else(|| format!("missing child environment {name}").into())
}

fn policy_record_path(root: &Path, reference: &PolicyArchiveRef) -> PathBuf {
    let key = reference.logical_key();
    let shard: String = key.chars().take(2).collect();
    root.join("archive/v1/records/policy")
        .join(shard)
        .join(format!("{key}.json"))
}

fn ensure_equal<T>(actual: &T, expected: &T, message: &str) -> Result<(), Box<dyn Error>>
where
    T: Debug + PartialEq,
{
    if actual != expected {
        return Err(format!("{message}: expected {expected:?}, found {actual:?}").into());
    }
    Ok(())
}
