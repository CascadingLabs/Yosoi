//! Live browser-download integration test: download a real PDF through stealth
//! Chrome and run it through the antivirus gate.
//!
//! Requires a real Chromium/Chrome binary and network access, so it is
//! `#[ignore]`d by default. Run it explicitly:
//!
//!     cargo test -p yosoi --features scanner --lib internal::browser::integration_tests::download -- --ignored
//! --test-threads=1
#![allow(clippy::expect_used, clippy::unwrap_used, clippy::panic)]

use std::time::Duration;

use crate::internal::browser::{BrowserSession, ScanConfig, Verdict, scan_path};

/// arXiv serves "Attention Is All You Need" as a plain, unauthenticated PDF —
/// a stable public download target.
const PDF_URL: &str = "https://arxiv.org/pdf/1706.03762";

#[tokio::test]
#[ignore = "requires Chromium + network"]
async fn downloads_and_scans_a_real_pdf() {
    let session = BrowserSession::builder()
        .headless()
        .launch()
        .await
        .expect("launch headless browser");
    let page = session.new_page("about:blank").await.expect("open page");

    let dir = tempfile::tempdir().expect("quarantine dir");
    let max_bytes = ScanConfig::default().max_bytes;
    let outcome = page
        .download_to_dir(PDF_URL, dir.path(), Duration::from_secs(60), max_bytes)
        .await
        .expect("download PDF");

    assert!(outcome.bytes > 0, "downloaded file is empty");
    assert_eq!(outcome.content_type.as_deref(), Some("application/pdf"));

    let report = scan_path(&outcome.path, &ScanConfig::default()).expect("scan");
    assert_eq!(
        report.verdict,
        Verdict::Clean,
        "real arXiv PDF should be clean"
    );
    assert_eq!(report.detected_mime.as_deref(), Some("application/pdf"));
}
