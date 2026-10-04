//! Download a real file from a live site through stealth Chrome, then run it
//! through the built-in antivirus gate before trusting it.
//!
//! Run it:
//!
//!     cargo run -p void_crawl_core --example download_and_scan
//!     cargo run -p void_crawl_core --example download_and_scan -- https://arxiv.org/pdf/2005.14165
//!
//! The file is downloaded into a throwaway *quarantine* directory, scanned, and
//! only copied next to you (`./downloads/`) if it comes back clean — exactly
//! the flow the `download` MCP tool runs.
#![allow(
    clippy::expect_used,
    clippy::unwrap_used,
    clippy::panic,
    clippy::disallowed_macros,
    reason = "runnable example: it prints and may unwrap for brevity"
)]

use std::{env, error::Error, fs, path::PathBuf, time::Duration};

use void_crawl_core::{BrowserSession, ScanConfig, Verdict, scan_path};

/// Default target: arXiv serves "Attention Is All You Need" as a plain,
/// unauthenticated PDF — a stable public download.
const DEFAULT_URL: &str = "https://arxiv.org/pdf/1706.03762";

#[tokio::main]
async fn main() -> Result<(), Box<dyn Error>> {
    let url = env::args()
        .nth(1)
        .unwrap_or_else(|| DEFAULT_URL.to_string());
    println!("→ downloading {url}");

    // A stealth, headless browser context — cookies/TLS fingerprint preserved.
    let session = BrowserSession::builder().headless().launch().await?;
    let page = session.new_page("about:blank").await?;

    // Quarantine: a fresh temp dir the file lands in before it is trusted.
    let quarantine = tempfile::tempdir()?;
    let max_bytes = ScanConfig::default().max_bytes;
    let outcome = page
        .download_to_dir(&url, quarantine.path(), Duration::from_secs(60), max_bytes)
        .await?;
    println!(
        "  downloaded {} bytes → {}",
        outcome.bytes,
        outcome.path.display()
    );

    // The antivirus gate: magic-byte type check + yara-x signature scan.
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
