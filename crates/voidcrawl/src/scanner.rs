//! Optional size, file-type and fixed EICAR checks for downloaded files.
//!
//! Callers can explicitly check a downloaded file with three bounded checks:
//!
//!   1. **size cap** — reject anything over the configured ceiling; an
//!      unbounded download is itself a resource-exhaustion surface.
//!   2. **magic-byte sniff** ([`infer`]) — detect the file's *real* type from
//!      its bytes. A file whose bytes are an executable but whose *claimed*
//!      Content-Type is a benign document (PDF, image, …) is a classic
//!      disguised-payload and is flagged.
//!   3. **EICAR signature check** — two fixed, case-sensitive byte markers,
//!      so the gate is testable with the industry-standard harmless test file.
//!      This checks the embedded signature; it is not a general malware engine.
//!
//! This helper has no signature database or custom rule interface.

use std::{fs, path::Path};

use memchr::memmem;

use crate::error::{Result, VoidCrawlError};

/// Default size ceiling: 100 MiB. Downloads larger than this are rejected
/// before any scan.
pub const DEFAULT_MAX_BYTES: u64 = 100 * 1024 * 1024;

/// Verdict for a scanned buffer.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Verdict {
    /// Passed every check.
    Clean,
    /// Failed a check. `reason` is human-readable and safe to surface.
    Flagged { reason: String },
}

impl Verdict {
    pub const fn is_clean(&self) -> bool {
        matches!(self, Self::Clean)
    }
}

/// Outcome of a scan.
#[derive(Debug, Clone)]
pub struct ScanReport {
    pub verdict: Verdict,
    /// MIME type inferred from the file's magic bytes, if recognized.
    pub detected_mime: Option<String>,
    /// Size of the scanned buffer in bytes.
    pub size: u64,
}

/// Knobs for [`scan_bytes`] / [`scan_path`].
#[derive(Debug, Clone)]
pub struct ScanConfig {
    /// Reject buffers larger than this (bytes).
    pub max_bytes: u64,
    /// The Content-Type the server *claimed*, if known. When set and it
    /// conflicts with the real (magic-byte) type in a dangerous way — a benign
    /// document that is actually an executable — the file is flagged.
    pub claimed_mime: Option<String>,
}

impl Default for ScanConfig {
    fn default() -> Self {
        Self {
            max_bytes: DEFAULT_MAX_BYTES,
            claimed_mime: None,
        }
    }
}

// Preserve the original embedded rule: both exact ASCII markers may occur
// anywhere in the payload, in either order. Keep them separate so the source
// does not contain the contiguous standard test signature.
const EICAR_TEXT_MARKER: &[u8] = b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE";
const EICAR_SUFFIX_MARKER: &[u8] = b"$H+H*";

/// Read `path` and scan its contents. See [`scan_bytes`].
pub fn scan_path(path: &Path, cfg: &ScanConfig) -> Result<ScanReport> {
    let data = fs::read(path)
        .map_err(|e| VoidCrawlError::Other(format!("read {}: {e}", path.display())))?;
    Ok(scan_bytes(&data, cfg))
}

/// Scan an in-memory buffer. Infallible — every failure mode is expressed as a
/// [`Verdict::Flagged`] rather than an error, so the gate never silently lets a
/// file through on a scanner hiccup.
pub fn scan_bytes(data: &[u8], cfg: &ScanConfig) -> ScanReport {
    let size = u64::try_from(data.len()).unwrap_or(u64::MAX);
    let detected = infer::get(data);
    let detected_mime = detected.map(|k| k.mime_type().to_string());

    let flag = |reason: String| ScanReport {
        verdict: Verdict::Flagged { reason },
        detected_mime: detected_mime.clone(),
        size,
    };

    // 1. Size cap.
    if size > cfg.max_bytes {
        return flag(format!("size {size} exceeds limit {}", cfg.max_bytes));
    }

    // 2. Disguised-executable check.
    if let (Some(claimed), Some(kind)) = (cfg.claimed_mime.as_deref(), detected)
        && is_executable(kind)
        && !mime_is_executable(claimed)
    {
        return flag(format!(
            "content-type mismatch: claimed {claimed} but bytes are {} (.{})",
            kind.mime_type(),
            kind.extension()
        ));
    }

    // 3. The shipped signature has no dynamic rules or compilation failure.
    if memmem::find(data, EICAR_TEXT_MARKER).is_some()
        && memmem::find(data, EICAR_SUFFIX_MARKER).is_some()
    {
        return flag("matched signature: EICAR_Test_File".to_owned());
    }

    ScanReport {
        verdict: Verdict::Clean,
        detected_mime,
        size,
    }
}

/// `true` when `infer` classifies these bytes as an executable / installer.
const fn is_executable(kind: infer::Type) -> bool {
    matches!(kind.matcher_type(), infer::MatcherType::App)
}

/// `true` when a claimed MIME is itself an executable type, so an executable
/// payload under it is *not* a disguise (the caller asked for a binary).
fn mime_is_executable(mime: &str) -> bool {
    mime.contains("executable")
        || matches!(
            mime,
            "application/x-msdownload"
                | "application/vnd.microsoft.portable-executable"
                | "application/x-mach-binary"
                | "application/x-dosexec"
                | "application/octet-stream"
        )
}
