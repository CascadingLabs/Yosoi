#![cfg(feature = "browser")]

//! Opt-in real-browser proof against an isolated loopback fixture only.
//!
//! Run with:
//! `YOSOI_BROWSER_TESTS=1 YOSOI_BROWSER_OUTPUT_DIR=/tmp/yosoi-browser-evidence cargo test -p yosoi --features browser --test browser_sessions -- --nocapture`

use std::{
    env,
    error::Error,
    io,
    path::{Path, PathBuf},
    process::Command,
};

const REPLAY_CHILD_MARKER: &str = "YOSOI_BROWSER_ARCHIVE_REPLAY_CHILD";
const CHROME_DISABLED_PATH: &str = "/path/that/must-not-be-launched-for-offline-replay";

#[path = "../examples/browser_automation_spike.rs"]
mod browser_automation_spike;

#[tokio::test]
async fn work_requests_retain_documents_after_session_close() -> Result<(), Box<dyn Error>> {
    if env::var("YOSOI_BROWSER_TESTS").ok().as_deref() != Some("1") {
        eprintln!("skipped browser session fixture; set YOSOI_BROWSER_TESTS=1 to opt in");
        return Ok(());
    }
    let output_dir = env::var_os("YOSOI_BROWSER_OUTPUT_DIR")
        .map(PathBuf::from)
        .ok_or_else(|| {
            io::Error::other("set YOSOI_BROWSER_OUTPUT_DIR to persist the evidence artifact")
        })?;
    let fixture = browser_automation_spike::LocalFixture::start().await?;
    let proof = browser_automation_spike::run_spike(&fixture.url, &output_dir).await;
    let shutdown = fixture.shutdown().await;
    proof?;
    shutdown?;
    for artifact in [
        "record_ref.json",
        "js_ref.json",
        "rerun_ref.json",
        "drift_ref.json",
    ] {
        if !output_dir.join(artifact).is_file() {
            return Err(
                io::Error::other(format!("browser spike did not persist {artifact}")).into(),
            );
        }
    }
    run_fresh_process_replay(&output_dir)?;
    Ok(())
}

#[tokio::test]
async fn browser_sessions_archive_replay_child() -> Result<(), Box<dyn Error>> {
    if env::var(REPLAY_CHILD_MARKER).ok().as_deref() != Some("1") {
        return Ok(());
    }
    if env::var("CHROME").ok().as_deref() != Some(CHROME_DISABLED_PATH) {
        return Err(io::Error::other(
            "fresh-process replay did not receive the invalid CHROME path",
        )
        .into());
    }
    let output_dir = env::var_os("YOSOI_BROWSER_OUTPUT_DIR")
        .map(PathBuf::from)
        .ok_or_else(|| {
            io::Error::other("set YOSOI_BROWSER_OUTPUT_DIR to the persisted evidence")
        })?;
    browser_automation_spike::replay_spike(&output_dir).await?;
    println!("fresh-process offline replay passed");
    Ok(())
}

fn run_fresh_process_replay(output_dir: &Path) -> io::Result<()> {
    let executable = env::current_exe()?;
    let output = Command::new(executable)
        .args([
            "--exact",
            "browser_sessions_archive_replay_child",
            "--nocapture",
        ])
        .env(REPLAY_CHILD_MARKER, "1")
        .env("YOSOI_BROWSER_OUTPUT_DIR", output_dir.as_os_str())
        .env("CHROME", CHROME_DISABLED_PATH)
        .output()?;
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    if !output.status.success() || !stdout.contains("fresh-process offline replay passed") {
        return Err(io::Error::other(format!(
            "fresh-process archive replay did not run successfully\nstdout:\n{stdout}\nstderr:\n{stderr}"
        )));
    }
    println!("fresh-process offline replay verified the linked baseline, rerun, and drift records");
    Ok(())
}
