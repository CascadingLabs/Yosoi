//! Result locations and replacement without losing previous measurements.
use std::{
    env, fs,
    path::{Path, PathBuf},
    process::Command,
    time::{SystemTime, UNIX_EPOCH},
};

use anyhow::{Context, Result, bail};
use sha2::{Digest, Sha256};

pub fn result_directory(class: &str) -> Result<PathBuf> {
    let root = super::workspace_root()?;
    if Command::new("jj")
        .arg("root")
        .current_dir(root)
        .output()
        .is_ok_and(|result| result.status.success())
    {
        // Grouping needs only the stable change ID, not a working-copy snapshot.
        let change = command_text(Command::new("jj").args([
            "--ignore-working-copy",
            "log",
            "-r",
            "@",
            "--no-graph",
            "-T",
            "change_id",
        ]))?;
        Ok(PathBuf::from("benchmarks/results/by-change/jj")
            .join(change)
            .join(class))
    } else {
        let commit = command_text(Command::new("git").args(["rev-parse", "HEAD"]))?;
        Ok(PathBuf::from("benchmarks/results/by-change/git")
            .join(commit)
            .join(class))
    }
}

pub fn command_text(command: &mut Command) -> Result<String> {
    let output = command
        .current_dir(super::workspace_root()?)
        .output()
        .context("failed to read measurement identity")?;
    if !output.status.success() {
        bail!(
            "identity command failed: {}",
            String::from_utf8_lossy(&output.stderr)
        );
    }
    let value = String::from_utf8(output.stdout).context("measurement identity is not UTF-8")?;
    let value = value.trim();
    if value.is_empty() {
        bail!("measurement identity is empty");
    }
    Ok(value.to_owned())
}

pub fn publish(staging: &Path, destination: &Path) -> Result<()> {
    if !staging.is_dir() {
        bail!(
            "measurement staging directory does not exist: {}",
            staging.display()
        );
    }
    let parent = destination
        .parent()
        .filter(|path| !path.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    fs::create_dir_all(parent).context("failed to create measurement result parent")?;
    let name = destination
        .file_name()
        .context("measurement destination needs a directory name")?;
    if destination.exists() && staging.canonicalize()? == destination.canonicalize()? {
        bail!("staging and destination must be distinct directories");
    }
    let archive = if destination.exists() {
        let history = parent.join("history").join(name);
        fs::create_dir_all(&history).context("failed to create measurement history")?;
        let epoch = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .context("system clock is before Unix epoch")?
            .as_secs();
        let archive = tempfile::Builder::new()
            .prefix(&format!("{epoch}-"))
            .tempdir_in(history)
            .context("failed to reserve measurement history directory")?;
        fs::rename(destination, archive.path().join("result"))
            .context("failed to retain previous measurement")?;
        Some(archive.keep())
    } else {
        None
    };
    if let Err(error) = fs::rename(staging, destination) {
        if let Some(archive) = &archive {
            fs::rename(archive.join("result"), destination).with_context(|| {
                format!(
                    "publication failed ({error}); previous result remains at {}",
                    archive.display()
                )
            })?;
            fs::remove_dir(archive)
                .context("failed to remove empty history directory after rollback")?;
        }
        return Err(error).context("failed to publish measurement; previous result restored");
    }
    Ok(())
}

pub fn copy_directory(source: &Path, destination: &Path) -> Result<()> {
    fs::create_dir_all(destination)?;
    for entry in fs::read_dir(source)
        .with_context(|| format!("no raw measurement directory at {}", source.display()))?
    {
        let entry = entry?;
        let target = destination.join(entry.file_name());
        if entry.file_type()?.is_dir() {
            copy_directory(&entry.path(), &target)?;
        } else if entry.file_type()?.is_file() {
            fs::copy(entry.path(), target)?;
        } else {
            bail!(
                "unexpected non-file measurement artifact {}",
                entry.path().display()
            );
        }
    }
    Ok(())
}

pub fn write_identity(output: &Path, class: &str) -> Result<()> {
    let root = super::workspace_root()?;
    let jj = Command::new("jj")
        .arg("root")
        .current_dir(root)
        .output()
        .is_ok_and(|result| result.status.success());
    let (revision, change) = if jj {
        (
            command_text(Command::new("jj").args([
                "log",
                "-r",
                "@",
                "--no-graph",
                "-T",
                "commit_id",
            ]))?,
            command_text(Command::new("jj").args([
                "--ignore-working-copy",
                "log",
                "-r",
                "@",
                "--no-graph",
                "-T",
                "change_id",
            ]))?,
        )
    } else {
        (
            command_text(Command::new("git").args(["rev-parse", "HEAD"]))?,
            "not_detected".to_owned(),
        )
    };
    let mut fixtures = serde_json::Map::new();
    for name in [
        "benchmarks/fixtures/web-capture/v1/manifest.json",
        "benchmarks/fixtures/web-capture/v1/complete-capture-v1.json",
        "Cargo.lock",
    ] {
        fixtures.insert(
            name.to_owned(),
            format!("{:x}", Sha256::digest(fs::read(root.join(name))?)).into(),
        );
    }
    let metadata = serde_json::json!({
        "schema": "yosoi.benchmark-run.v1", "measurement_class": class,
        "source_snapshot_commit": revision, "jj_change_id": change, "fixtures_sha256": fixtures,
        "rustc": command_text(Command::new("rustc").arg("-vV"))?,
        "cargo": command_text(Command::new("cargo").arg("--version"))?,
        "platform": command_text(Command::new("uname").args(["-srm"]))?,
        "rustflags": env::var_os("RUSTFLAGS").map(|value| value.to_string_lossy().into_owned()), "cargo_jobs": 1,
        "scope": "raw measurements; no derived dashboard or regression threshold",
        "network": "fixed local fixtures or IPv4 loopback only"
    });
    fs::write(
        output.join("metadata.json"),
        serde_json::to_vec_pretty(&metadata)?,
    )?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use anyhow::ensure;

    #[test]
    fn repeated_publication_retains_previous_results() -> Result<()> {
        let root = tempfile::tempdir()?;
        let destination = root.path().join("criterion");
        for value in ["first", "second", "third"] {
            let staging = root.path().join("staging");
            fs::create_dir(&staging)?;
            fs::write(staging.join("evidence"), value)?;
            publish(&staging, &destination)?;
        }
        ensure!(
            fs::read_to_string(destination.join("evidence"))? == "third",
            "latest result was not preserved"
        );
        let mut previous = Vec::new();
        for entry in fs::read_dir(root.path().join("history/criterion"))? {
            previous.push(fs::read_to_string(entry?.path().join("result/evidence"))?);
        }
        previous.sort();
        ensure!(previous == ["first", "second"], "previous runs were lost");
        Ok(())
    }

    #[test]
    fn missing_or_identical_staging_preserves_existing_result() -> Result<()> {
        let root = tempfile::tempdir()?;
        let destination = root.path().join("criterion");
        fs::create_dir(&destination)?;
        fs::write(destination.join("evidence"), "previous")?;
        ensure!(publish(&root.path().join("missing"), &destination).is_err());
        ensure!(publish(&destination, &destination).is_err());
        ensure!(
            fs::read_to_string(destination.join("evidence"))? == "previous",
            "previous result was lost"
        );
        ensure!(!root.path().join("history").exists());
        Ok(())
    }

    #[test]
    fn failed_rename_restores_previous_result() -> Result<()> {
        let root = tempfile::tempdir()?;
        let destination = root.path().join("criterion");
        let staging = destination.join("nested-staging");
        fs::create_dir_all(&staging)?;
        fs::write(destination.join("evidence"), "previous")?;
        // Moving the destination moves this nested staging path away before publication.
        ensure!(publish(&staging, &destination).is_err());
        ensure!(
            fs::read_to_string(destination.join("evidence"))? == "previous",
            "previous result was lost"
        );
        ensure!(staging.is_dir());
        Ok(())
    }
}
