//! Content-safety gate for downloaded files — a small, pure-Rust "antivirus".
//!
//! Anything fetched from the open web is untrusted, so before a downloaded
//! file is handed back to a caller it passes three checks, cheapest first:
//!
//!   1. **size cap** — reject anything over the configured ceiling; an
//!      unbounded download is itself a resource-exhaustion surface.
//!   2. **magic-byte sniff** ([`infer`]) — detect the file's *real* type from
//!      its bytes. A file whose bytes are an executable but whose *claimed*
//!      Content-Type is a benign document (PDF, image, …) is a classic
//!      disguised-payload and is flagged.
//!   3. **signature scan** ([`yara_x`]) — VirusTotal's pure-Rust YARA engine,
//!      run against a tiny embedded ruleset. Ships an EICAR signature so the
//!      gate is testable with the industry-standard harmless test file.
//!
//! `clamd` signature-database scanning is intentionally **not** here — it needs
//! an external daemon and is an opt-in follow-up. This module is the always-on
//! baseline that runs anywhere, including CI.

use std::{fs, path::Path, sync::OnceLock};

use yara_x::Rules;

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

/// Embedded YARA ruleset — signature-only, so it compiles fast and needs no
/// YARA modules.
///
/// The EICAR rule deliberately keys on two disjoint substrings rather than the
/// full contiguous 68-byte test string, so this source file is not itself
/// quarantined by a host antivirus scanning the repository.
const RULES_SRC: &str = r#"
rule EICAR_Test_File {
    meta:
        description = "EICAR standard antivirus test file"
    strings:
        $a = "EICAR-STANDARD-ANTIVIRUS-TEST-FILE"
        $b = "$H+H*"
    condition:
        all of them
}
"#;

/// Lazily compile and cache the embedded ruleset.
fn rules() -> &'static Rules {
    static RULES: OnceLock<Rules> = OnceLock::new();
    RULES.get_or_init(|| {
        let mut compiler = yara_x::Compiler::new();
        // The source is a compile-time constant we control; a failure here is a
        // programming error, but we still avoid panicking — fall back to an
        // empty ruleset so the gate degrades to type/size checks only.
        match compiler.add_source(RULES_SRC) {
            Ok(_) => compiler.build(),
            Err(_) => yara_x::Compiler::new().build(),
        }
    })
}

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

    // 3. YARA signature scan.
    let mut scanner = yara_x::Scanner::new(rules());
    match scanner.scan(data) {
        Ok(results) => {
            if let Some(rule) = results.matching_rules().next() {
                return flag(format!("matched signature: {}", rule.identifier()));
            }
        }
        Err(e) => return flag(format!("scan error: {e}")),
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
