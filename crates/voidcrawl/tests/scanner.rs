//! Unit tests for the content-safety scanner.
//!
//! Pure and deterministic — no browser, no daemon, no network — so they run
//! everywhere including CI. The malware case uses **EICAR**, the industry
//! standard harmless antivirus test string.
#![allow(clippy::expect_used, clippy::unwrap_used, clippy::panic)]

use void_crawl_core::{ScanConfig, Verdict, scan_bytes};

/// Assemble the EICAR test string at runtime so the repository never stores the
/// contiguous 68-byte signature on disk (which a host antivirus would itself
/// quarantine).
fn eicar() -> Vec<u8> {
    let head = r"X5O!P%@AP[4\PZX54(P^)7CC)7}";
    let tag = "$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!";
    let tail = "$H+H*";
    format!("{head}{tag}{tail}").into_bytes()
}

/// Smallest thing `infer` recognizes as a PDF (the `%PDF` magic).
const MINIMAL_PDF: &[u8] = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n";

/// ELF magic + a little padding — `infer` classifies this as an executable.
const ELF_HEADER: &[u8] = &[0x7f, b'E', b'L', b'F', 2, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0];

#[test]
fn eicar_is_flagged() {
    let report = scan_bytes(&eicar(), &ScanConfig::default());
    assert!(
        matches!(report.verdict, Verdict::Flagged { .. }),
        "EICAR must be flagged, got {:?}",
        report.verdict
    );
}

#[test]
fn clean_pdf_passes() {
    let cfg = ScanConfig {
        claimed_mime: Some("application/pdf".into()),
        ..Default::default()
    };
    let report = scan_bytes(MINIMAL_PDF, &cfg);
    assert_eq!(report.verdict, Verdict::Clean);
    assert_eq!(report.detected_mime.as_deref(), Some("application/pdf"));
}

#[test]
fn executable_disguised_as_pdf_is_flagged() {
    let mut data = ELF_HEADER.to_vec();
    data.extend_from_slice(&[0u8; 64]);
    let cfg = ScanConfig {
        claimed_mime: Some("application/pdf".into()),
        ..Default::default()
    };
    let report = scan_bytes(&data, &cfg);
    assert!(
        matches!(report.verdict, Verdict::Flagged { .. }),
        "an executable served as application/pdf must be flagged, got {:?}",
        report.verdict
    );
}

#[test]
fn executable_under_octet_stream_is_allowed() {
    // octet-stream is the generic binary type — an executable under it is not a
    // disguise, so the type check must not flag it (the signature check still gets a say).
    let mut data = ELF_HEADER.to_vec();
    data.extend_from_slice(&[0u8; 64]);
    let cfg = ScanConfig {
        claimed_mime: Some("application/octet-stream".into()),
        ..Default::default()
    };
    let report = scan_bytes(&data, &cfg);
    assert_eq!(report.verdict, Verdict::Clean);
}

#[test]
fn oversize_is_flagged() {
    let cfg = ScanConfig {
        max_bytes: 8,
        ..Default::default()
    };
    let report = scan_bytes(&[0u8; 64], &cfg);
    assert!(matches!(report.verdict, Verdict::Flagged { .. }));
}

#[test]
fn small_clean_payload_passes() {
    let report = scan_bytes(b"hello world, not a virus", &ScanConfig::default());
    assert_eq!(report.verdict, Verdict::Clean);
}

#[test]
fn eicar_requires_both_case_sensitive_markers_in_either_order() {
    for incomplete in [b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE".as_slice(), b"$H+H*"] {
        assert_eq!(
            scan_bytes(incomplete, &ScanConfig::default()).verdict,
            Verdict::Clean
        );
    }
    let reordered = b"$H+H*\0EICAR-STANDARD-ANTIVIRUS-TEST-FILE";
    assert_eq!(
        scan_bytes(reordered, &ScanConfig::default()).verdict,
        Verdict::Flagged {
            reason: "matched signature: EICAR_Test_File".to_owned()
        }
    );
    assert_eq!(
        scan_bytes(
            b"$H+H*eicar-standard-antivirus-test-file",
            &ScanConfig::default()
        )
        .verdict,
        Verdict::Clean
    );
}
