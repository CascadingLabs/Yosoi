//! Local release-note commands. Publication is deliberately outside this tool.

use std::{ffi::OsString, process::Command};

use anyhow::{Context, Result, bail};
use serde::Deserialize;

#[derive(Deserialize)]
struct CheckedRelease {
    version: String,
    date: String,
}

pub fn run(arguments: impl Iterator<Item = OsString>) -> Result<()> {
    let mut arguments: Vec<OsString> = arguments.collect();
    if arguments.is_empty() {
        arguments.push(OsString::from("--help"));
    }
    if arguments.iter().any(|value| {
        value
            .to_str()
            .is_some_and(|value| value == "--root" || value.starts_with("--root="))
    }) {
        bail!("xtask release always uses this workspace; use the Python tool for fixture roots");
    }
    if arguments.first().and_then(|value| value.to_str()) == Some("check") {
        if arguments
            .get(1)
            .is_some_and(|value| matches!(value.to_str(), Some("--help" | "-h")))
        {
            // Delegate help without checking release state.
        } else if arguments.len() == 2 {
            return check(&arguments);
        } else {
            bail!("usage: cargo xtask release check <VERSION>");
        }
    }
    let status = command()?.args(arguments).status().context(
        "failed to start release tooling; install uv to run the pinned Jinja environment",
    )?;
    if !status.success() {
        bail!("release-note command failed with {status}");
    }
    Ok(())
}

fn command() -> Result<Command> {
    let root = super::workspace_root()?;
    let mut command = Command::new("uv");
    command
        .arg("run")
        .arg("--locked")
        .arg("--project")
        .arg(root.join("scripts/releases"))
        .arg("python")
        .arg(root.join("scripts/releases/release.py"))
        .arg("--root")
        .arg(root)
        .current_dir(root);
    Ok(command)
}

fn check(arguments: &[OsString]) -> Result<()> {
    let output = command()?
        .args(arguments)
        .arg("--json")
        .output()
        .context("failed to run release validation; install uv")?;
    if !output.status.success() {
        eprint!("{}", String::from_utf8_lossy(&output.stderr));
        bail!("release-note validation failed with {}", output.status);
    }
    let release: CheckedRelease = serde_json::from_slice(&output.stdout)
        .context("release validator returned invalid metadata")?;
    super::version::run(
        [
            release.version,
            "--date-released".to_owned(),
            release.date,
            "--check".to_owned(),
        ]
        .into_iter()
        .map(OsString::from),
    )?;
    println!("Release notes and synchronized release metadata are consistent.");
    Ok(())
}
