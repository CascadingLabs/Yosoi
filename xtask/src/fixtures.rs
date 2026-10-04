//! Integrity and offline extraction of committed locator fixtures.
use anyhow::{Context, Result, bail, ensure};
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeSet,
    ffi::OsString,
    fs,
    path::{Component, Path, PathBuf},
    process::Command,
};

#[derive(Deserialize)]
struct FilePin {
    path: PathBuf,
    bytes: u64,
    sha256: String,
}
#[derive(Deserialize)]
struct Fixture {
    id: String,
    #[serde(flatten)]
    file: FilePin,
}
#[derive(Deserialize)]
struct Storage {
    source_artifact: FilePin,
}
#[derive(Deserialize)]
struct Manifest {
    schema: String,
    files: Vec<Fixture>,
    storage: Option<Storage>,
}

pub fn run(mut arguments: impl Iterator<Item = OsString>) -> Result<()> {
    let task = arguments.next().unwrap_or_else(|| "verify".into());
    let root = match arguments.next() {
        Some(path) => PathBuf::from(path),
        None => super::workspace_root()?.join("benchmarks/fixtures/document-locators/v1"),
    };
    super::no_extra_arguments(arguments)?;
    match task.to_str() {
        Some("verify") => {
            verify(&root)?;
            println!("locator fixture integrity verified");
            Ok(())
        }
        Some("materialize") => {
            materialize(&root)?;
            println!("pinned advanced fixtures materialized");
            Ok(())
        }
        _ => bail!("usage: cargo xtask fixtures [verify|materialize] [corpus-directory]"),
    }
}

fn read_manifest(path: &Path, schema: &str) -> Result<Manifest> {
    let manifest: Manifest = serde_json::from_slice(
        &fs::read(path).with_context(|| format!("cannot read {}", path.display()))?,
    )?;
    ensure!(
        manifest.schema == schema,
        "unsupported fixture schema in {}",
        path.display()
    );
    ensure!(!manifest.files.is_empty(), "fixture manifest is empty");
    let mut ids = BTreeSet::new();
    let mut paths = BTreeSet::new();
    for fixture in &manifest.files {
        ensure!(
            ids.insert(&fixture.id),
            "duplicate fixture ID {}",
            fixture.id
        );
        ensure!(paths.insert(&fixture.file.path), "duplicate fixture path");
        safe_path(&fixture.file.path)?;
    }
    Ok(manifest)
}

fn safe_path(path: &Path) -> Result<()> {
    ensure!(
        !path.as_os_str().is_empty()
            && path
                .components()
                .all(|part| matches!(part, Component::Normal(_))),
        "unsafe fixture path {}",
        path.display()
    );
    Ok(())
}

fn check_file(root: &Path, pin: &FilePin) -> Result<()> {
    safe_path(&pin.path)?;
    let path = root.join(&pin.path);
    let metadata = fs::symlink_metadata(&path)
        .with_context(|| format!("missing fixture {}", path.display()))?;
    ensure!(
        metadata.is_file() && metadata.len() == pin.bytes,
        "fixture type or byte count differs: {}",
        path.display()
    );
    let actual = format!("{:x}", Sha256::digest(fs::read(&path)?));
    ensure!(
        actual == pin.sha256,
        "fixture digest differs: {}",
        path.display()
    );
    Ok(())
}

pub fn verify(root: &Path) -> Result<()> {
    let golden = read_manifest(
        &root.join("manifest.json"),
        "yosoi.document-locator-corpus.v1",
    )?;
    let advanced = read_manifest(
        &root.join("advanced/manifest.json"),
        "yosoi.document-locator-advanced-corpus.v1",
    )?;
    let ids: BTreeSet<_> = golden
        .files
        .iter()
        .chain(&advanced.files)
        .map(|fixture| fixture.id.as_str())
        .collect();
    ensure!(
        ids.len()
            == golden
                .files
                .len()
                .checked_add(advanced.files.len())
                .context("fixture count overflow")?,
        "fixture IDs overlap between tiers"
    );
    let matrix: serde_json::Value = serde_json::from_slice(&fs::read(root.join("matrix.json"))?)?;
    ensure!(
        matrix.get("schema").and_then(serde_json::Value::as_str)
            == Some("yosoi.document-locator-matrix.v1"),
        "unsupported fixture matrix schema"
    );
    for group in ["benchmark_cases", "golden_cases", "advanced_cases"] {
        let cases = matrix
            .get(group)
            .and_then(serde_json::Value::as_array)
            .with_context(|| format!("missing fixture matrix group {group}"))?;
        ensure!(!cases.is_empty(), "empty fixture matrix group {group}");
        for case in cases {
            let id = case
                .get("fixture_id")
                .and_then(serde_json::Value::as_str)
                .context("matrix case has no fixture ID")?;
            ensure!(ids.contains(id), "matrix references unknown fixture {id}");
        }
    }
    for fixture in &golden.files {
        check_file(root, &fixture.file)?;
    }
    let storage = advanced
        .storage
        .context("advanced corpus has no source artifact")?;
    check_file(&root.join("advanced"), &storage.source_artifact)?;
    let materialized = root.join("advanced/materialized");
    if materialized.exists() {
        for fixture in &advanced.files {
            check_file(&materialized, &fixture.file)?;
        }
    }
    Ok(())
}

fn tar_output(archive: &Path, flag: &str) -> Result<String> {
    let output = Command::new("tar")
        .arg(flag)
        .arg(archive)
        .output()
        .context("failed to inspect fixture archive with tar")?;
    ensure!(
        output.status.success(),
        "cannot inspect fixture archive: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    String::from_utf8(output.stdout).context("fixture archive member names are not UTF-8")
}

pub fn materialize(root: &Path) -> Result<()> {
    verify(root)?;
    let advanced_root = root.join("advanced");
    let manifest = read_manifest(
        &advanced_root.join("manifest.json"),
        "yosoi.document-locator-advanced-corpus.v1",
    )?;
    let archive = advanced_root.join(
        manifest
            .storage
            .context("advanced corpus has no source artifact")?
            .source_artifact
            .path,
    );
    let destination = advanced_root.join("materialized");
    if destination.exists() {
        return Ok(());
    }
    let names = tar_output(&archive, "-tzf")?;
    let members: Vec<_> = names.lines().map(PathBuf::from).collect();
    let actual: BTreeSet<_> = members.iter().collect();
    let expected: BTreeSet<_> = manifest
        .files
        .iter()
        .map(|fixture| &fixture.file.path)
        .collect();
    ensure!(
        actual == expected && actual.len() == members.len(),
        "fixture archive members differ from manifest"
    );
    ensure!(
        tar_output(&archive, "-tvzf")?
            .lines()
            .all(|line| line.starts_with('-')),
        "fixture archive may contain only regular files"
    );
    let staging = tempfile::Builder::new()
        .prefix(".fixture-staging-")
        .tempdir_in(&advanced_root)?;
    let status = Command::new("tar")
        .args(["-xzf"])
        .arg(&archive)
        .arg("-C")
        .arg(staging.path())
        .args(["--no-same-owner", "--no-same-permissions"])
        .status()
        .context("failed to extract fixture archive")?;
    ensure!(status.success(), "fixture extraction failed with {status}");
    for fixture in &manifest.files {
        check_file(staging.path(), &fixture.file)?;
    }
    fs::rename(staging.path(), destination).context("failed to publish materialized fixtures")?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_byte_mutation_and_unsafe_paths() -> Result<()> {
        let root = tempfile::tempdir()?;
        fs::write(root.path().join("fixture"), b"original")?;
        let pin = FilePin {
            path: "fixture".into(),
            bytes: 8,
            sha256: format!("{:x}", Sha256::digest(b"original")),
        };
        check_file(root.path(), &pin)?;
        fs::write(root.path().join("fixture"), b"modified")?;
        ensure!(check_file(root.path(), &pin).is_err());
        ensure!(safe_path(Path::new("../outside")).is_err());
        ensure!(safe_path(Path::new("/outside")).is_err());
        Ok(())
    }
    #[test]
    fn rejects_unknown_schema() -> Result<()> {
        let root = tempfile::tempdir()?;
        let manifest = root.path().join("manifest.json");
        fs::write(&manifest, r#"{"schema":"unknown","files":[]}"#)?;
        ensure!(read_manifest(&manifest, "yosoi.document-locator-corpus.v1").is_err());
        Ok(())
    }
}
