#![allow(clippy::string_lit_as_bytes, reason = "table-driven UTF-8 fixtures")]

use super::*;
use crate::internal::web_capture::{CharacterDecodingOutcome, DecodingErrorCode};

macro_rules! utf8_limit {
    ($name:ident,$text:expr,$limit:expr,$expected:expr,$truncated:expr) => {
        #[test]
        fn $name() {
            let r = run_limit(
                SourceMediaType::from_text("text/plain"),
                $text.as_bytes(),
                $limit,
            );
            assert_eq!(view(&r).text(), $expected);
            assert_eq!(
                matches!(r.decoding(), CharacterDecodingOutcome::OutputTruncated(_)),
                $truncated
            );
        }
    };
}
utf8_limit!(ascii_exact, "abc", 3, "abc", false);
utf8_limit!(ascii_one_under, "abc", 2, "ab", true);
utf8_limit!(ascii_one_over, "abc", 4, "abc", false);
utf8_limit!(two_byte_exact, "é", 2, "é", false);
utf8_limit!(two_byte_under, "é", 1, "", true);
utf8_limit!(two_byte_over, "é", 3, "é", false);
utf8_limit!(three_byte_exact, "☃", 3, "☃", false);
utf8_limit!(three_byte_under1, "☃", 1, "", true);
utf8_limit!(three_byte_under2, "☃", 2, "", true);
utf8_limit!(three_byte_over, "☃", 4, "☃", false);
utf8_limit!(four_byte_exact, "😀", 4, "😀", false);
utf8_limit!(four_byte_under1, "😀", 1, "", true);
utf8_limit!(four_byte_under2, "😀", 2, "", true);
utf8_limit!(four_byte_under3, "😀", 3, "", true);
utf8_limit!(four_byte_over, "😀", 5, "😀", false);
utf8_limit!(mixed_boundary1, "a☃b", 1, "a", true);
utf8_limit!(mixed_boundary2, "a☃b", 2, "a", true);
utf8_limit!(mixed_boundary3, "a☃b", 3, "a", true);
utf8_limit!(mixed_boundary4, "a☃b", 4, "a☃", true);
utf8_limit!(mixed_boundary5, "a☃b", 5, "a☃b", false);

#[test]
fn zero_limit_rejects_nonempty_output() {
    let r = run_limit(SourceMediaType::from_text("text/plain"), b"a", 0);
    assert!(matches!(
        r.decoding(),
        CharacterDecodingOutcome::OutputTruncated(_)
    ));
    assert_eq!(view(&r).text(), "");
}
#[test]
fn zero_limit_allows_empty_output() {
    let r = run_limit(SourceMediaType::from_text("text/plain"), b"", 0);
    assert!(matches!(
        r.decoding(),
        CharacterDecodingOutcome::Complete(_)
    ));
}
#[test]
fn replacement_expansion_respects_utf8_limit() {
    let r = run_limit(
        SourceMediaType::from_text("text/html;charset=utf-8"),
        b"\xff",
        2,
    );
    assert_eq!(view(&r).text(), "");
    assert!(matches!(
        r.decoding(),
        CharacterDecodingOutcome::OutputTruncated(_)
    ));
}
#[test]
fn replacement_exact_limit() {
    let r = run_limit(
        SourceMediaType::from_text("text/html;charset=utf-8"),
        b"\xff",
        3,
    );
    assert_eq!(view(&r).text(), "�");
    assert_eq!(view(&r).replacements(), 1);
}
#[test]
fn genuine_replacement_character_is_not_decoder_replacement() {
    let r = run("text/plain", "�".as_bytes());
    assert_eq!(view(&r).replacements(), 0);
}
#[test]
fn decoder_inserted_replacement_is_counted() {
    let r = run("text/html;charset=utf-8", b"\xff");
    assert_eq!(view(&r).replacements(), 1);
}
#[test]
fn legacy_expansion_respects_limit() {
    let r = run_limit(
        SourceMediaType::from_text("text/html;charset=windows-1252"),
        b"\x93",
        2,
    );
    assert_eq!(view(&r).text(), "");
    assert!(matches!(
        r.decoding(),
        CharacterDecodingOutcome::OutputTruncated(_)
    ));
}
#[test]
fn legacy_expansion_exact_limit() {
    let r = run_limit(
        SourceMediaType::from_text("text/html;charset=windows-1252"),
        b"\x93",
        3,
    );
    assert_eq!(view(&r).text(), "“");
}
#[test]
fn output_digest_covers_only_bounded_view() {
    let r = run_limit(SourceMediaType::from_text("text/plain"), b"abcdef", 3);
    assert_eq!(view(&r).digest(), Sha256Digest::digest(b"abc"));
    assert_ne!(view(&r).digest(), Sha256Digest::digest(b"abcdef"));
}
#[test]
fn source_and_view_extents_are_separate() {
    let r = run_limit(SourceMediaType::from_text("text/plain"), b"abcdef", 3);
    assert!(matches!(
        r.decoding(),
        CharacterDecodingOutcome::OutputTruncated(_)
    ));
    assert!(!view(&r).source_truncated());
    assert!(!view(&r).incomplete_terminal_sequence());
}
#[test]
fn strict_invalid_before_output_boundary_still_fails() {
    let r = run_limit(SourceMediaType::from_text("text/plain"), b"a\xff", 1);
    assert!(matches!(
        r.decoding(),
        CharacterDecodingOutcome::Undecodable(DecodingErrorCode::InvalidSequence)
    ));
}
#[test]
fn html_replacement_after_output_boundary_is_not_semantically_hidden() {
    let r = run_limit(
        SourceMediaType::from_text("text/html;charset=utf-8"),
        b"a\xff",
        1,
    );
    assert_eq!(view(&r).text(), "a");
    assert_eq!(view(&r).replacements(), 1);
}
#[test]
fn canonical_utf8_identity_is_exact() {
    assert_eq!(
        view(&run("text/plain;charset=utf8", b"x"))
            .encoding()
            .canonical_name(),
        "UTF-8"
    );
}
#[test]
fn canonical_utf16le_identity_is_exact() {
    assert_eq!(
        view(&run("text/plain", b"\xff\xfex\0"))
            .encoding()
            .canonical_name(),
        "UTF-16LE"
    );
}
#[test]
fn canonical_utf16be_identity_is_exact() {
    assert_eq!(
        view(&run("text/plain", b"\xfe\xff\0x"))
            .encoding()
            .canonical_name(),
        "UTF-16BE"
    );
}
#[test]
fn canonical_windows_identity_is_exact() {
    assert_eq!(
        view(&run("text/html", b"x")).encoding().canonical_name(),
        "windows-1252"
    );
}
