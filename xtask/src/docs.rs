use std::{ffi::OsString, process::Command};

use anyhow::{Context, Result, bail};

const HELP: &str = "\
Documentation development tasks

Usage: cargo xtask docs <task> [arguments]

Tasks:
  manifest <command> [options]   Public-doc generate, preview, and catalog commands
  reference <command> [options] Rust-reference discover, generate, preview-catalog,
                                verify, pack, and verify-attestation commands
  check                         Focused manifest and Rust-reference tests, one worker

Run `cargo xtask docs manifest --help` or `cargo xtask docs reference --help`
for the underlying tool's arguments. Paths are relative to the repository root.
Generation requires an explicit source identity and output directory; it does
not publish artifacts. `check` does not compile Rustdoc or build the frontend.
";

pub fn run(mut arguments: impl Iterator<Item = OsString>) -> Result<()> {
    let Some(task) = arguments.next() else {
        print!("{HELP}");
        return Ok(());
    };
    match task.to_str() {
        Some("manifest") => run_node("scripts/docs/generate.mjs", arguments),
        Some("reference") => run_node("scripts/docs/reference/generate.mjs", arguments),
        Some("check") => {
            super::no_extra_arguments(arguments)?;
            run_node(
                "--test",
                [
                    "--test-isolation=none",
                    "--test-concurrency=1",
                    "scripts/docs/generate.test.mjs",
                    "scripts/docs/reference/reference.test.mjs",
                ]
                .into_iter()
                .map(OsString::from),
            )
        }
        Some("help" | "--help" | "-h") => {
            super::no_extra_arguments(arguments)?;
            print!("{HELP}");
            Ok(())
        }
        Some(task) => bail!("unknown documentation task `{task}`\n\n{HELP}"),
        None => bail!("documentation task name must be valid Unicode"),
    }
}

fn run_node(entry: &str, arguments: impl Iterator<Item = OsString>) -> Result<()> {
    let status = Command::new("node")
        .arg(entry)
        .args(arguments)
        .current_dir(super::workspace_root()?)
        .status()
        .with_context(|| format!("failed to start Node for {entry}; install Node 24 or newer"))?;
    if !status.success() {
        bail!("documentation command {entry} failed with {status}");
    }
    Ok(())
}
