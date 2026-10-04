//! Fixture integrity uses the same native checker as repository maintenance.
use anyhow::{Result, ensure};
use std::{ffi::OsString, path::Path};

#[path = "../../xtask/src/fixtures.rs"]
mod fixtures;

fn workspace_root() -> Result<&'static Path> {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .ok_or_else(|| anyhow::anyhow!("benchmark manifest has no repository parent"))
}
fn no_extra_arguments(mut arguments: impl Iterator<Item = OsString>) -> Result<()> {
    ensure!(arguments.next().is_none(), "unexpected fixture argument");
    Ok(())
}

#[test]
fn committed_locator_fixture_bytes_and_matrix_references_are_valid() -> Result<()> {
    fixtures::run([OsString::from("verify")].into_iter())
}
