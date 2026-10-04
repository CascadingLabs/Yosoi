#![allow(
    clippy::unwrap_used,
    reason = "test-only browser fixtures use validated temporary paths"
)]

use std::{fs, os::unix::fs::PermissionsExt, path::PathBuf};

use super::browser_distribution::verify_supported_browser_distribution;

fn version_fixture(version: &str) -> (tempfile::TempDir, PathBuf) {
    let directory = tempfile::tempdir().unwrap();
    let executable = directory.path().join("chrome");
    fs::write(
        &executable,
        format!("#!/bin/sh\nprintf '%s\\n' '{version}'\n"),
    )
    .unwrap();
    let mut permissions = fs::metadata(&executable).unwrap().permissions();
    permissions.set_mode(0o700);
    fs::set_permissions(&executable, permissions).unwrap();
    (directory, executable)
}

#[tokio::test]
async fn testing_only_browser_distribution_is_rejected_before_launch() {
    let (_directory, executable) = version_fixture("Google Chrome for Testing 153.0.8010.36");
    let error = verify_supported_browser_distribution(&executable)
        .await
        .unwrap_err();
    assert!(matches!(
        error,
        crate::VoidCrawlError::LaunchFailed(message)
            if message == "testing-only browser distributions are prohibited"
    ));
}

#[tokio::test]
async fn regular_stable_browser_distribution_is_eligible_for_launch() {
    let (_directory, executable) = version_fixture("Google Chrome 153.0.8010.36");
    verify_supported_browser_distribution(&executable)
        .await
        .unwrap();
}
