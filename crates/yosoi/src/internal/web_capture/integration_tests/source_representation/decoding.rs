use super::*;
use crate::internal::web_capture as internal_web_capture;
use crate::internal::web_capture::{
    CharacterDecodingOutcome, DecodingBasis, DecodingConflict, DecodingErrorCode,
};

fn encoding(header: &str, bytes: &[u8]) -> &'static str {
    view(&run(header, bytes)).encoding().canonical_name()
}
macro_rules! html_meta {
    ($name:ident,$markup:expr,$enc:expr) => {
        #[test]
        fn $name() {
            let r = run("text/html", $markup);
            assert_eq!(view(&r).encoding().canonical_name(), $enc);
            assert_eq!(view(&r).basis(), DecodingBasis::HtmlMeta);
        }
    };
}
html_meta!(meta_charset_double, b"<meta charset=\"utf-8\">", "UTF-8");
html_meta!(meta_charset_single, b"<meta charset='utf-8'>", "UTF-8");
html_meta!(meta_charset_unquoted, b"<meta charset=utf-8>", "UTF-8");
html_meta!(meta_case, b"<META CHARSET=UTF-8>", "UTF-8");
html_meta!(meta_attr_before, b"<meta foo=x charset=utf-8>", "UTF-8");
html_meta!(meta_attr_after, b"<meta charset=utf-8 foo=x>", "UTF-8");
html_meta!(
    meta_http_equiv_before,
    b"<meta http-equiv=content-type content='text/html; charset=utf-8'>",
    "UTF-8"
);
html_meta!(
    meta_content_before,
    b"<meta content='text/html; charset=utf-8' http-equiv=content-type>",
    "UTF-8"
);
html_meta!(meta_legacy, b"<meta charset=iso-8859-1>", "windows-1252");
html_meta!(meta_utf16_adjusted, b"<meta charset=utf-16be>", "UTF-8");

macro_rules! html_fallback {
    ($name:ident,$markup:expr) => {
        #[test]
        fn $name() {
            let r = run("text/html", $markup);
            assert_eq!(view(&r).basis(), DecodingBasis::HtmlFallback);
        }
    };
}
html_fallback!(meta_in_comment, b"<!-- <meta charset=utf-8> -->");
html_fallback!(meta_in_script, b"<script><meta charset=utf-8></script>");
html_fallback!(arbitrary_charset_attr, b"<div charset=utf-8>");
html_fallback!(missing_pragma, b"<meta content='text/html;charset=utf-8'>");
html_fallback!(
    wrong_pragma,
    b"<meta http-equiv=x content='text/html;charset=utf-8'>"
);
html_fallback!(
    content_without_charset,
    b"<meta http-equiv=content-type content='text/html'>"
);
html_fallback!(malformed_missing_gt, b"<meta charset=utf-8");
html_fallback!(malformed_empty_charset, b"<meta charset=>");
html_fallback!(
    duplicate_first_invalid,
    b"<meta charset=made-up charset=utf-8>"
);
#[test]
fn meta_ending_at_1024_is_seen() {
    let mut b = vec![b' '; 1004];
    b.extend_from_slice(b"<meta charset=utf-8>");
    assert_eq!(view(&run("text/html", &b)).basis(), DecodingBasis::HtmlMeta);
}
#[test]
fn meta_straddling_1024_is_not_seen() {
    let mut b = vec![b' '; 1005];
    b.extend_from_slice(b"<meta charset=utf-8>");
    assert_eq!(
        view(&run("text/html", &b)).basis(),
        DecodingBasis::HtmlFallback
    );
}

#[test]
fn first_meta_wins() {
    assert_eq!(
        encoding(
            "text/html",
            b"<meta charset=windows-1252><meta charset=utf-8>"
        ),
        "windows-1252"
    );
}
#[test]
fn bom_beats_http_and_meta() {
    let r = run(
        "text/html;charset=windows-1252",
        b"\xef\xbb\xbf<meta charset=shift_jis>ok",
    );
    let v = view(&r);
    assert_eq!(v.encoding().canonical_name(), "UTF-8");
    assert_eq!(v.basis(), DecodingBasis::Bom);
    assert!(v.conflicts().contains(&DecodingConflict::HttpCharset));
    assert!(v.conflicts().contains(&DecodingConflict::InBandDeclaration));
}
#[test]
fn http_beats_meta() {
    let r = run("text/html;charset=windows-1252", b"<meta charset=utf-8>x");
    assert_eq!(view(&r).basis(), DecodingBasis::HttpCharset);
    assert!(
        view(&r)
            .conflicts()
            .contains(&DecodingConflict::InBandDeclaration)
    );
}

macro_rules! xml_encoding {
    ($name:ident,$bytes:expr,$enc:expr,$basis:expr) => {
        #[test]
        fn $name() {
            let r = run("application/xml", $bytes);
            assert_eq!(view(&r).encoding().canonical_name(), $enc);
            assert_eq!(view(&r).basis(), $basis);
        }
    };
}
xml_encoding!(
    xml_utf8_default,
    b"<x/>",
    "UTF-8",
    DecodingBasis::XmlDefaultUtf8
);
xml_encoding!(
    xml_utf8_bom,
    b"\xef\xbb\xbf<x/>",
    "UTF-8",
    DecodingBasis::Bom
);
xml_encoding!(
    xml_utf16le_bom,
    b"\xff\xfe<\0x\0/\0>\0",
    "UTF-16LE",
    DecodingBasis::Bom
);
xml_encoding!(
    xml_utf16be_bom,
    b"\xfe\xff\0<\0x\0/\0>",
    "UTF-16BE",
    DecodingBasis::Bom
);
xml_encoding!(
    xml_decl_utf8,
    b"<?xml version='1.0' encoding='utf-8'?><x/>",
    "UTF-8",
    DecodingBasis::XmlDeclaration
);
xml_encoding!(
    xml_decl_legacy,
    b"<?xml version='1.0' encoding='windows-1252'?><x>\xe9</x>",
    "windows-1252",
    DecodingBasis::XmlDeclaration
);
xml_encoding!(
    xml_signature_le,
    b"<\0?\0x\0m\0l\0?\0>\0",
    "UTF-16LE",
    DecodingBasis::XmlAutodetection
);
xml_encoding!(
    xml_signature_be,
    b"\0<\0?\0x\0m\0l\0?\0>",
    "UTF-16BE",
    DecodingBasis::XmlAutodetection
);

#[test]
fn xml_bom_http_and_declaration_conflicts_are_all_recorded() {
    let r = run(
        "application/xml;charset=windows-1252",
        b"\xef\xbb\xbf<?xml version='1.0' encoding='shift_jis'?><x/>",
    );
    let v = view(&r);
    assert_eq!(v.basis(), DecodingBasis::Bom);
    assert!(v.conflicts().contains(&DecodingConflict::HttpCharset));
    assert!(v.conflicts().contains(&DecodingConflict::InBandDeclaration));
}

#[test]
fn xml_http_beats_no_bom_utf16_signature_and_records_conflict() {
    let r = run(
        "application/xml;charset=utf-8",
        b"<\0?\0x\0m\0l\0 \0v\0e\0r\0s\0i\0o\0n\0=\0'\x001\0.\x000\0'\0?\0>\0",
    );
    let v = view(&r);
    assert_eq!(v.basis(), DecodingBasis::HttpCharset);
    assert!(v.conflicts().contains(&DecodingConflict::EncodingSignature));
}

macro_rules! xml_error {
    ($name:ident,$bytes:expr,$variant:pat) => {
        #[test]
        fn $name() {
            assert!(matches!(
                run("application/xml", $bytes).decoding(),
                $variant
            ));
        }
    };
}
xml_error!(
    xml_bom_alone,
    b"\xef\xbb\xbf",
    CharacterDecodingOutcome::Complete(_)
);
#[test]
fn xml_whitespace_before_bom_is_not_a_bom_signature() {
    let r = missing(b" \xef\xbb\xbf<?xml?>");
    assert!(matches!(
        r.classification(),
        internal_web_capture::SourceClassificationOutcome::Unknown { .. }
    ));
}
xml_error!(
    xml_utf32be_bom,
    b"\0\0\xfe\xff",
    CharacterDecodingOutcome::UnsupportedEncoding(DecodingErrorCode::UnsupportedUtf32)
);
xml_error!(
    xml_utf32le_bom,
    b"\xff\xfe\0\0",
    CharacterDecodingOutcome::UnsupportedEncoding(DecodingErrorCode::UnsupportedUtf32)
);
xml_error!(
    xml_utf32be_signature,
    b"\0\0\0<",
    CharacterDecodingOutcome::UnsupportedEncoding(DecodingErrorCode::UnsupportedUtf32)
);
xml_error!(
    xml_utf32le_signature,
    b"<\0\0\0",
    CharacterDecodingOutcome::UnsupportedEncoding(DecodingErrorCode::UnsupportedUtf32)
);
xml_error!(
    xml_decl_unsupported,
    b"<?xml version='1.0' encoding='utf-7'?>",
    CharacterDecodingOutcome::UnsupportedEncoding(DecodingErrorCode::UnsupportedCharset)
);
xml_error!(
    xml_decl_malformed,
    b"<?xml version='1.0' encoding=>",
    CharacterDecodingOutcome::Undecodable(DecodingErrorCode::InvalidCharset)
);
xml_error!(
    xml_decl_conflicting,
    b"<?xml version='1.0' encoding='utf-8' encoding='windows-1252'?>",
    CharacterDecodingOutcome::Undecodable(DecodingErrorCode::InvalidCharset)
);
xml_error!(
    xml_invalid_utf8,
    b"<x>\xff</x>",
    CharacterDecodingOutcome::Undecodable(DecodingErrorCode::InvalidSequence)
);

macro_rules! json_case {
    ($name:ident,$bytes:expr) => {
        #[test]
        fn $name() {
            let r = run("application/json", $bytes);
            assert_eq!(
                view(&r).text(),
                String::from_utf8_lossy($bytes).trim_start_matches('\u{feff}')
            );
        }
    };
}
json_case!(json_empty, b"");
json_case!(json_object, b"{}");
json_case!(json_array, b"[]");
json_case!(json_malformed, b"{broken");
json_case!(json_scalar, b"true");
json_case!(json_whitespace, b" \t\r\n{}");
#[test]
fn json_charset_ignored() {
    let r = run("application/json;charset=windows-1252", b"{}");
    assert_eq!(view(&r).encoding().canonical_name(), "UTF-8");
    assert!(
        view(&r)
            .conflicts()
            .contains(&DecodingConflict::JsonCharsetIgnored)
    );
}
#[test]
fn json_utf8_bom_accepted() {
    let r = run("application/json", b"\xef\xbb\xbf{}");
    assert_eq!(view(&r).text(), "{}");
    assert!(
        view(&r)
            .conflicts()
            .contains(&DecodingConflict::JsonBomAccepted)
    );
}
#[test]
fn json_utf16le_unsupported() {
    assert!(matches!(
        run("application/json", b"\xff\xfe{\0").decoding(),
        CharacterDecodingOutcome::UnsupportedEncoding(DecodingErrorCode::UnsupportedJsonUnicode)
    ));
}
#[test]
fn json_utf16be_unsupported() {
    assert!(matches!(
        run("application/json", b"\xfe\xff\0{").decoding(),
        CharacterDecodingOutcome::UnsupportedEncoding(DecodingErrorCode::UnsupportedJsonUnicode)
    ));
}
#[test]
fn json_utf32_unsupported() {
    assert!(matches!(
        run("application/json", b"\0\0\xfe\xff").decoding(),
        CharacterDecodingOutcome::UnsupportedEncoding(DecodingErrorCode::UnsupportedJsonUnicode)
    ));
}
#[test]
fn json_invalid_utf8() {
    assert!(matches!(
        run("application/json", b"{\xff").decoding(),
        CharacterDecodingOutcome::Undecodable(DecodingErrorCode::InvalidSequence)
    ));
}

macro_rules! plain_charset {
    ($name:ident,$label:expr,$bytes:expr,$text:expr) => {
        #[test]
        fn $name() {
            let r = run(concat!("text/plain;charset=", $label), $bytes);
            assert_eq!(view(&r).text(), $text);
            assert_eq!(view(&r).basis(), DecodingBasis::HttpCharset);
        }
    };
}
plain_charset!(plain_utf8, "utf-8", "é".as_bytes(), "é");
plain_charset!(plain_1252, "windows-1252", b"\x93x\x94", "“x”");
plain_charset!(plain_latin1_alias, "iso-8859-1", b"\xe9", "é");
#[test]
fn plain_utf8_default() {
    assert_eq!(
        view(&run("text/plain", "☃".as_bytes())).basis(),
        DecodingBasis::PlainUtf8Validation
    );
}
#[test]
fn plain_invalid_utf8() {
    assert!(matches!(
        run("text/plain", b"\xff").decoding(),
        CharacterDecodingOutcome::Undecodable(DecodingErrorCode::InvalidSequence)
    ));
}
#[test]
fn plain_unsupported_terminal() {
    assert!(matches!(
        run("text/plain;charset=utf-7", b"x").decoding(),
        CharacterDecodingOutcome::UnsupportedEncoding(DecodingErrorCode::UnsupportedCharset)
    ));
}
#[test]
fn plain_conflict_terminal() {
    assert!(matches!(
        run("text/plain;charset=utf-8;charset=shift_jis", b"x").decoding(),
        CharacterDecodingOutcome::Undecodable(DecodingErrorCode::ConflictingCharset)
    ));
}
#[test]
fn plain_empty_charset_terminal() {
    assert!(matches!(
        run("text/plain;charset=\"\"", b"x").decoding(),
        CharacterDecodingOutcome::Undecodable(DecodingErrorCode::InvalidCharset)
    ));
}
