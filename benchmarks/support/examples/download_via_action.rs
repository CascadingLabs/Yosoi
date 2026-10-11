//! Download a file triggered by a page **action** (a button click), not a URL
//! you already hold — the Google-Drive case. Demonstrates the *arm → act →
//! await* capture flow and runs it through the antivirus gate.
//!
//! Default target is a single file inside a real public "anyone with the link"
//! Google Drive folder; clicking its "Download" button makes Drive stream the
//! file back from `drive.usercontent.google.com` — exactly the indirect
//! download `download_to_dir` can't handle (no stable URL, cross-origin host).
//!
//! Run it:
//!
//!     cargo run -p yosoi-dev-support --features scanner --example download_via_action
#![allow(
    clippy::expect_used,
    clippy::unwrap_used,
    clippy::panic,
    clippy::disallowed_macros,
    reason = "runnable example: it prints and may unwrap for brevity"
)]

use std::{error::Error, fs, path::PathBuf, time::Duration};

use yosoi_dev_support::internal::browser::{BrowserSession, ScanConfig, Verdict, scan_path};

/// A single file's preview page inside a public Google Drive folder. The viewer
/// menubar exposes a `button` with accessible name "Download".
const DRIVE_FILE: &str = "https://drive.google.com/file/d/1k1NpDI0-TdO0ahdSjzKUYt3Gqa9AXfFb/view";

#[tokio::main]
async fn main() -> Result<(), Box<dyn Error>> {
    let session = BrowserSession::builder().headless().launch().await?;
    let page = session.new_page("about:blank").await?;

    println!("→ opening {DRIVE_FILE}");
    page.goto_and_wait_for_idle(DRIVE_FILE, Duration::from_secs(40))
        .await?;

    // Quarantine the file lands in before it is trusted.
    let quarantine = tempfile::tempdir()?;
    let max_bytes = ScanConfig::default().max_bytes;

    // arm → act → await.
    println!("  arming download capture …");
    let capture = page.arm_download(quarantine.path(), max_bytes).await?;

    println!("  clicking the \"Download\" button …");
    page.click_by_role("button", "Download", 0, false).await?;
    // Drive may interpose a "Download anyway" virus-scan interstitial for files
    // it can't scan — clicking it is just another action in the same flow.
    let _ = page
        .click_by_role("button", "Download anyway", 0, false)
        .await;

    println!("  waiting for the download to land …");
    let outcome = capture.wait(&page, Duration::from_secs(90)).await?;
    println!(
        "  downloaded {} bytes → {}",
        outcome.bytes,
        outcome.path.display()
    );

    let report = scan_path(&outcome.path, &ScanConfig::default())?;
    let kind = report.detected_mime.as_deref().unwrap_or("unknown");
    println!("  detected type: {kind}");

    match report.verdict {
        Verdict::Clean => {
            let out_dir = PathBuf::from("downloads");
            fs::create_dir_all(&out_dir)?;
            let name = outcome
                .path
                .file_name()
                .unwrap_or_else(|| "download".as_ref());
            let dest = out_dir.join(name);
            fs::copy(&outcome.path, &dest)?;
            println!("✓ clean — saved to {}", dest.display());
        }
        Verdict::Flagged { reason } => {
            println!("✗ FLAGGED: {reason} — discarded, not saved");
        }
    }

    session.close().await?;
    Ok(())
}
