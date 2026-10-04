use std::error::Error;
use std::fs as std_fs;
use std::sync::{Arc, Barrier};
use std::thread;

use tempfile::tempdir;
use yosoi_policy::{CountLimit, Policy};

use super::publication::{publish_and_sync_with_hook, rename_no_replace};
use super::*;

const POLICY_SCHEMA_VERSION: u32 = 1;

fn changed_policy() -> Result<Policy, yosoi_policy::PolicyError> {
    let mut policy = Policy::default();
    policy.locators.max_matches = CountLimit::try_from(42_u64)?;
    Ok(policy)
}

#[tokio::test]
async fn same_key_equal_retry_is_idempotent_and_conflict_preserves_original_bytes()
-> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let archive = Archive::open(temporary.path().join(".yosoi")).await?;
    let key = RecordKey::parse("123e4567-e89b-42d3-a456-426614174000")?;
    let original = Policy::default();

    archive
        .write_record(RecordKind::Policy, POLICY_SCHEMA_VERSION, &key, &original)
        .await?;
    let path = archive.record_path(RecordKind::Policy, &key);
    let mut older_record: serde_json::Value = serde_json::from_slice(&fs::read(&path).await?)?;
    let writer = older_record
        .get_mut("writer")
        .and_then(serde_json::Value::as_object_mut)
        .ok_or("Archive writer must be an object")?;
    writer.insert("version".to_owned(), serde_json::json!("0.0.0"));
    let original_bytes = serde_json::to_vec(&older_record)?;
    fs::write(&path, &original_bytes).await?;
    archive
        .write_record(RecordKind::Policy, POLICY_SCHEMA_VERSION, &key, &original)
        .await?;
    if fs::read(&path).await? != original_bytes {
        return Err("equal retry rewrote the committed record".into());
    }

    let conflict = archive
        .write_record(
            RecordKind::Policy,
            POLICY_SCHEMA_VERSION,
            &key,
            &changed_policy()?,
        )
        .await;
    if !matches!(conflict, Err(ArchiveError::IdentityConflict { .. })) {
        return Err("same-key different-value write did not conflict".into());
    }
    if fs::read(&path).await? != original_bytes {
        return Err("identity conflict changed committed bytes".into());
    }
    Ok(())
}

#[test]
fn atomic_no_replace_rename_has_one_winner_and_no_staging_alias() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let first = temporary.path().join("first.tmp");
    let second = temporary.path().join("second.tmp");
    let final_path = temporary.path().join("record.json");
    std_fs::write(&first, b"first")?;
    std_fs::write(&second, b"second")?;
    let barrier = Arc::new(Barrier::new(3));

    let (first_result, second_result) = thread::scope(|scope| {
        let first_barrier = Arc::clone(&barrier);
        let first_final = final_path.clone();
        let first_stage = first.clone();
        let first_handle = scope.spawn(move || {
            first_barrier.wait();
            rename_no_replace(&first_stage, &first_final)
        });
        let second_barrier = Arc::clone(&barrier);
        let second_final = final_path.clone();
        let second_stage = second.clone();
        let second_handle = scope.spawn(move || {
            second_barrier.wait();
            rename_no_replace(&second_stage, &second_final)
        });
        barrier.wait();
        (first_handle.join(), second_handle.join())
    });

    let first_result = first_result.map_err(|_| "first publication thread panicked")?;
    let second_result = second_result.map_err(|_| "second publication thread panicked")?;
    let successes = [first_result.is_ok(), second_result.is_ok()]
        .into_iter()
        .filter(|succeeded| *succeeded)
        .count();
    if successes != 1 {
        return Err("atomic no-replace publication did not select exactly one winner".into());
    }
    let final_bytes = std_fs::read(&final_path)?;
    if final_bytes != b"first" && final_bytes != b"second" {
        return Err("published bytes did not come from either complete staged file".into());
    }
    if first.exists() && second.exists() {
        return Err("winning staged path remained as a mutable alias".into());
    }
    Ok(())
}

#[tokio::test]
async fn started_publication_cannot_be_cancelled_between_rename_and_sync()
-> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let staging_parent = temporary.path().join("staging");
    let final_parent = temporary.path().join("records");
    std_fs::create_dir(&staging_parent)?;
    std_fs::create_dir(&final_parent)?;
    let staging = staging_parent.join("record.tmp");
    let final_path = final_parent.join("record.json");
    std_fs::write(&staging, b"complete")?;
    let renamed = Arc::new(Barrier::new(2));
    let release = Arc::new(Barrier::new(2));
    let renamed_for_task = Arc::clone(&renamed);
    let release_for_task = Arc::clone(&release);

    let publication = task::spawn_blocking(move || {
        publish_and_sync_with_hook(
            &staging,
            &final_path,
            &final_parent,
            &staging_parent,
            || {
                renamed_for_task.wait();
                release_for_task.wait();
            },
        )
    });
    renamed.wait();
    publication.abort();
    release.wait();
    let result = publication.await?;
    if result.is_err() {
        return Err("publication failed after the atomic rename".into());
    }
    let final_path = temporary.path().join("records/record.json");
    if std_fs::read(&final_path)? != b"complete" {
        return Err("cancelled publication did not retain complete bytes".into());
    }
    if temporary.path().join("staging/record.tmp").exists() {
        return Err("atomic rename left a writable staging alias".into());
    }
    Ok(())
}
