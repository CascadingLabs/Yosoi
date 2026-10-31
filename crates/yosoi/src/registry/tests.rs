#![allow(
    clippy::panic_in_result_fn,
    reason = "Assertions intentionally fail conformance tests."
)]

use std::{
    env,
    error::Error,
    fs::{self, OpenOptions},
    io::{self, BufRead, BufReader, Read, Write},
    process::{self, Command, Stdio},
};

use serde_json::json;

use super::{Change, Coordination, Registry, RegistryError};

type TestResult = Result<(), Box<dyn Error>>;

fn put(key: &str, value: serde_json::Value) -> Change {
    Change::Put {
        key: key.to_owned(),
        value,
    }
}

fn conformance(registry: &Registry) -> TestResult {
    let original = registry.snapshot()?;
    assert!(original.entries.is_empty());
    let committed = registry.commit(&original.revision, &[put("group", json!({"active": 1}))])?;
    assert_eq!(committed.revision.sequence, 1);
    assert!(matches!(
        registry.commit(&original.revision, &[put("group", json!(2))]),
        Err(RegistryError::Conflict)
    ));
    assert_eq!(registry.snapshot()?, committed);
    assert!(matches!(
        registry.commit(
            &committed.revision,
            &[put("valid", json!(true)), put("", json!(false))]
        ),
        Err(RegistryError::InvalidKey)
    ));
    assert_eq!(registry.snapshot()?, committed);
    let untouched = registry.commit(&committed.revision, &[])?;
    assert_eq!(untouched, committed);
    assert!(matches!(
        registry.commit(&Registry::default().snapshot()?.revision, &[]),
        Err(RegistryError::Conflict)
    ));
    let removed = registry.commit(
        &committed.revision,
        &[Change::Remove {
            key: "group".to_owned(),
        }],
    )?;
    assert!(removed.entries.is_empty());
    assert_eq!(removed.revision.sequence, 2);
    registry.compact()?;
    assert_eq!(registry.snapshot()?, removed);
    assert_eq!(
        serde_json::from_str::<super::Snapshot>(&serde_json::to_string(&removed)?)?,
        removed
    );
    Ok(())
}

#[test]
fn memory_transactions_are_atomic_and_instance_scoped() -> TestResult {
    let registry = Registry::default();
    assert_eq!(registry.coordination(), Coordination::Instance);
    conformance(&registry)?;
    assert_eq!(registry.clone().snapshot()?, registry.snapshot()?);
    assert_ne!(
        Registry::default().snapshot()?.revision.registry_id,
        registry.snapshot()?.revision.registry_id
    );
    Ok(())
}

#[test]
fn jsonl_conforms_and_survives_restart_and_compaction() -> TestResult {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("nested/registry.jsonl");
    let registry = Registry::jsonl(&path)?;
    assert_eq!(registry.coordination(), Coordination::LocalProcesses);
    conformance(&registry)?;
    let snapshot = registry.snapshot()?;
    drop(registry);
    assert_eq!(Registry::jsonl(&path)?.snapshot()?, snapshot);
    assert_eq!(fs::read_to_string(&path)?.lines().count(), 1);
    Ok(())
}

#[test]
fn abandoned_tail_is_ignored_then_removed_before_append() -> TestResult {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("registry.jsonl");
    let registry = Registry::jsonl(&path)?;
    let original = registry.snapshot()?;
    OpenOptions::new()
        .append(true)
        .open(&path)?
        .write_all(b"{\"version\":1,")?;
    assert_eq!(Registry::jsonl(&path)?.snapshot()?, original);
    let committed = registry.commit(&original.revision, &[put("after_crash", json!(1))])?;
    assert_eq!(Registry::jsonl(&path)?.snapshot()?, committed);
    assert_eq!(fs::read_to_string(path)?.lines().count(), 2);
    Ok(())
}

#[test]
fn malformed_committed_records_and_unknown_versions_fail_loudly() -> TestResult {
    let directory = tempfile::tempdir()?;
    for content in [
        "",
        "{}\n",
        "not JSON\n",
        "{\"version\":999,\"event\":\"checkpoint\",\"snapshot\":{}}\n",
    ] {
        let path = directory
            .path()
            .join(format!("{}.jsonl", uuid::Uuid::new_v4()));
        fs::write(&path, content)?;
        assert!(matches!(
            Registry::jsonl(path),
            Err(RegistryError::InvalidState)
        ));
    }
    let unsupported = directory.path().join("unsupported.jsonl");
    Registry::jsonl(&unsupported)?;
    let mut record: serde_json::Value = serde_json::from_str(&fs::read_to_string(&unsupported)?)?;
    record
        .as_object_mut()
        .ok_or("journal header is not an object")?
        .insert("version".to_owned(), json!(999));
    let mut bytes = serde_json::to_vec(&record)?;
    bytes.push(b'\n');
    fs::write(&unsupported, bytes)?;
    assert!(matches!(
        Registry::jsonl(unsupported),
        Err(RegistryError::InvalidState)
    ));
    let path = directory.path().join("corrupt.jsonl");
    let registry = Registry::jsonl(&path)?;
    OpenOptions::new()
        .append(true)
        .open(&path)?
        .write_all(b"broken\n")?;
    assert!(matches!(
        registry.snapshot(),
        Err(RegistryError::InvalidState)
    ));
    Ok(())
}

#[test]
fn oversized_value_does_not_partially_commit() -> TestResult {
    for persistent in [false, true] {
        let directory = tempfile::tempdir()?;
        let registry = if persistent {
            Registry::jsonl(directory.path().join("registry.jsonl"))?
        } else {
            Registry::default()
        };
        let original = registry.snapshot()?;
        assert!(matches!(
            registry.commit(
                &original.revision,
                &[
                    put("small", json!(1)),
                    put("large", json!("x".repeat(65536)))
                ]
            ),
            Err(RegistryError::CapacityExceeded)
        ));
        assert_eq!(registry.snapshot()?, original);
    }
    Ok(())
}

#[test]
fn accepted_nesting_replays_and_excess_nesting_cannot_poison_the_journal() -> TestResult {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("nested.jsonl");
    for registry in [Registry::default(), Registry::jsonl(&path)?] {
        let original = registry.snapshot()?;
        let mut value = json!(null);
        for _ in 0..32 {
            value = json!([value]);
        }
        let accepted = registry.commit(&original.revision, &[put("nested", value.clone())])?;
        assert!(matches!(
            registry.commit(&accepted.revision, &[put("excess", json!([value]))]),
            Err(RegistryError::CapacityExceeded)
        ));
        assert_eq!(registry.snapshot()?, accepted);
    }
    assert_eq!(Registry::jsonl(&path)?.snapshot()?.revision.sequence, 1);
    Ok(())
}

#[test]
fn local_lock_contention_is_explicit_and_does_not_reset_state() -> TestResult {
    let directory = tempfile::tempdir()?;
    let registry = Registry::jsonl(directory.path().join("registry.jsonl"))?;
    let original = registry.snapshot()?;
    let lock = OpenOptions::new()
        .read(true)
        .write(true)
        .open(directory.path().join("registry.jsonl.lock"))?;
    lock.lock()?;
    assert!(matches!(registry.snapshot(), Err(RegistryError::Busy)));
    assert!(matches!(
        registry.commit(&original.revision, &[put("unexpected", json!(true))]),
        Err(RegistryError::Busy)
    ));
    drop(lock);
    assert_eq!(registry.snapshot()?, original);
    Ok(())
}

#[test]
fn independent_processes_cannot_commit_the_same_revision_twice() -> TestResult {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("registry.jsonl");
    let registry = Registry::jsonl(&path)?;
    let mut children = Vec::new();
    for _ in 0..2 {
        let mut child = Command::new(env::current_exe()?)
            .args([
                "--exact",
                "registry::tests::child_commit",
                "--ignored",
                "--nocapture",
            ])
            .env("YOSOI_REGISTRY_TEST_PATH", &path)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()?;
        let mut output = BufReader::new(child.stdout.take().ok_or("missing child stdout")?);
        let mut line = String::new();
        loop {
            if output.read_line(&mut line)? == 0 {
                return Err("child exited before readiness".into());
            }
            if line.contains("REGISTRY_READY") {
                break;
            }
            line.clear();
        }
        children.push((child, output));
    }
    for (child, _) in &mut children {
        child
            .stdin
            .take()
            .ok_or("missing child stdin")?
            .write_all(b"x")?;
    }
    let mut committed = 0_usize;
    for (mut child, mut output) in children {
        let mut text = String::new();
        output.read_to_string(&mut text)?;
        assert!(child.wait()?.success(), "{text}");
        if text.contains("REGISTRY_COMMITTED") {
            committed = committed.saturating_add(1);
        }
    }
    assert_eq!(committed, 1);
    assert_eq!(registry.snapshot()?.revision.sequence, 1);
    Ok(())
}

#[test]
#[ignore = "subprocess helper, invoked only by the parent concurrency test"]
fn child_commit() -> TestResult {
    let registry =
        Registry::jsonl(env::var_os("YOSOI_REGISTRY_TEST_PATH").ok_or("missing test journal")?)?;
    let original = registry.snapshot()?;
    println!("REGISTRY_READY");
    io::stdout().flush()?;
    let mut byte = [0_u8];
    io::stdin().read_exact(&mut byte)?;
    match registry.commit(&original.revision, &[put("winner", json!(process::id()))]) {
        Ok(_) => println!("REGISTRY_COMMITTED"),
        Err(RegistryError::Busy | RegistryError::Conflict) => println!("REGISTRY_DECLINED"),
        Err(error) => return Err(error.into()),
    }
    Ok(())
}
