use super::*;
use crate::internal::web_capture::{
    CharsetDeclaration, CharsetIssue, MediaDeclaration, MediaDeclarationIssue,
    SourceClassificationOutcome, SourceFormat, XmlProfile,
};

macro_rules! parsed_case {
    ($name:ident, $header:expr, $essence:expr) => {
        #[test]
        fn $name() {
            match run($header, b"").declaration() {
                MediaDeclaration::Parsed { essence, .. } => assert_eq!(essence, $essence),
                other => panic!("{other:?}"),
            }
        }
    };
}
parsed_case!(token_letters, "text/plain", "text/plain");
parsed_case!(token_digits, "application/x1", "application/x1");
parsed_case!(token_bang, "application/x!", "application/x!");
parsed_case!(token_hash, "application/x#", "application/x#");
parsed_case!(token_dollar, "application/x$", "application/x$");
parsed_case!(token_amp, "application/x&", "application/x&");
parsed_case!(token_quote, "application/x'", "application/x'");
parsed_case!(token_star, "application/x*", "application/x*");
parsed_case!(token_plus, "application/x+json", "application/x+json");
parsed_case!(token_dash, "application/x-y", "application/x-y");
parsed_case!(token_dot, "application/x.y", "application/x.y");
parsed_case!(token_caret, "application/x^y", "application/x^y");
parsed_case!(token_under, "application/x_y", "application/x_y");
parsed_case!(token_backtick, "application/x`y", "application/x`y");
parsed_case!(token_pipe, "application/x|y", "application/x|y");
parsed_case!(token_tilde, "application/x~y", "application/x~y");
parsed_case!(case_folded, "TEXT/HTML", "text/html");
parsed_case!(outer_ows, "\t text/plain \t", "text/plain");
parsed_case!(unrelated_token, "text/plain;foo=bar", "text/plain");
parsed_case!(unrelated_quoted, "text/plain;foo=\"a b\"", "text/plain");
parsed_case!(quoted_pair, "text/plain;foo=\"a\\\"b\"", "text/plain");

macro_rules! malformed_case {
    ($name:ident, $header:expr) => {
        #[test]
        fn $name() {
            assert_eq!(
                run($header, b"").declaration(),
                &MediaDeclaration::Malformed(MediaDeclarationIssue::InvalidSyntax)
            );
        }
    };
}
malformed_case!(empty, "");
malformed_case!(missing_slash, "text");
malformed_case!(empty_type, "/plain");
malformed_case!(empty_subtype, "text/");
malformed_case!(extra_slash, "text/plain/x");
malformed_case!(space_in_type, "te xt/plain");
malformed_case!(space_after_slash, "text/ plain");
malformed_case!(bare_parameter, "text/plain;x");
malformed_case!(empty_parameter_name, "text/plain;=x");
malformed_case!(empty_unquoted_value, "text/plain;x=");
malformed_case!(unterminated_quote, "text/plain;x=\"");
malformed_case!(junk_after_quote, "text/plain;x=\"a\"z");
malformed_case!(comma_is_not_field_joining, "text/plain,text/plain");
malformed_case!(newline_control, "text/plain\n");
malformed_case!(carriage_control, "text/plain\r");
malformed_case!(nul_control, "text/plain\0");
malformed_case!(delete_control, "text/plain\u{7f}");
malformed_case!(non_ascii, "text/pläin");
malformed_case!(backslash_outside_quote, "text/plain;x=a\\b");
malformed_case!(bracket_not_token, "text/[plain");
malformed_case!(paren_not_token, "text/(plain");

macro_rules! charset_label {
    ($name:ident, $label:expr, $canonical:expr) => {
        #[test]
        fn $name() {
            match run(concat!("text/plain;charset=", $label), b"").declaration() {
                MediaDeclaration::Parsed {
                    charset:
                        CharsetDeclaration::Label {
                            canonical,
                            duplicate: false,
                        },
                    ..
                } => assert_eq!(canonical, $canonical),
                other => panic!("{other:?}"),
            }
        }
    };
}
charset_label!(utf8, "utf-8", "utf-8");
charset_label!(utf8_alias, "utf8", "utf-8");
charset_label!(unicode11, "unicode-1-1-utf-8", "utf-8");
charset_label!(ascii_alias, "us-ascii", "windows-1252");
charset_label!(latin1_alias, "iso-8859-1", "windows-1252");
charset_label!(cp1252_alias, "cp1252", "windows-1252");
charset_label!(utf16, "utf-16", "utf-16le");
charset_label!(utf16le, "utf-16le", "utf-16le");
charset_label!(utf16be, "utf-16be", "utf-16be");
charset_label!(shift_jis, "shift_jis", "shift_jis");
charset_label!(sjis_alias, "sjis", "shift_jis");
charset_label!(gbk, "gbk", "gbk");
charset_label!(gb2312_alias, "gb2312", "gbk");
charset_label!(big5, "big5", "big5");
charset_label!(eucjp, "euc-jp", "euc-jp");
charset_label!(korean, "euc-kr", "euc-kr");
charset_label!(iso2022jp, "iso-2022-jp", "iso-2022-jp");
charset_label!(koi8r, "koi8-r", "koi8-r");

#[test]
fn charset_quoted_and_trimmed() {
    match run("text/plain;charset=\" utf-8 \"", b"").declaration() {
        MediaDeclaration::Parsed {
            charset: CharsetDeclaration::Label { canonical, .. },
            ..
        } => assert_eq!(canonical, "utf-8"),
        other => panic!("{other:?}"),
    }
}
#[test]
fn equal_aliases_are_duplicate_not_conflict() {
    match run("text/plain;charset=utf8;charset=unicode-1-1-utf-8", b"").declaration() {
        MediaDeclaration::Parsed {
            charset:
                CharsetDeclaration::Label {
                    canonical,
                    duplicate: true,
                },
            ..
        } => assert_eq!(canonical, "utf-8"),
        other => panic!("{other:?}"),
    }
}
#[test]
fn conflicting_labels_are_specific() {
    assert!(matches!(
        run("text/plain;charset=utf-8;charset=windows-1252", b"").declaration(),
        MediaDeclaration::Parsed {
            charset: CharsetDeclaration::Issue(CharsetIssue::Conflicting),
            ..
        }
    ));
}
#[test]
fn empty_charset_is_invalid() {
    assert!(matches!(
        run("text/plain;charset=\"\"", b"").declaration(),
        MediaDeclaration::Parsed {
            charset: CharsetDeclaration::Issue(CharsetIssue::Invalid),
            ..
        }
    ));
}
#[test]
fn unsupported_utf7_is_bounded() {
    match run("text/plain;charset=utf-7", b"").declaration() {
        MediaDeclaration::Parsed {
            charset: CharsetDeclaration::Issue(CharsetIssue::Unsupported { normalized }),
            ..
        } => assert_eq!(normalized, "utf-7"),
        other => panic!("{other:?}"),
    }
}
#[test]
fn unsupported_replacement_is_bounded() {
    assert!(matches!(
        run("text/plain;charset=replacement", b"").declaration(),
        MediaDeclaration::Parsed {
            charset: CharsetDeclaration::Issue(CharsetIssue::Unsupported { .. }),
            ..
        }
    ));
}
#[test]
fn oversized_observation_is_refused() {
    assert!(matches!(
        SourceMediaType::from_text("x".repeat(1025)),
        SourceMediaType::TooLong
    ));
}
#[test]
fn exact_observation_bound_is_value() {
    let media_type = SourceMediaType::from_text("x".repeat(1024));
    assert!(matches!(media_type, SourceMediaType::Value(_)));
    assert_eq!(media_type.value().map(str::len), Some(1024));
}
#[test]
fn bounded_value_constructor_rejects_one_byte_over_the_boundary() {
    assert!(BoundedSourceMediaType::try_from_text("x".repeat(1024)).is_ok());
    assert_eq!(
        BoundedSourceMediaType::try_from_text("x".repeat(1025)),
        Err(SourceMediaTypeTooLong)
    );
}
#[test]
fn duplicate_field_observation_is_malformed() {
    assert_eq!(
        run_limit(SourceMediaType::Duplicate, b"{}", 100).declaration(),
        &MediaDeclaration::Malformed(MediaDeclarationIssue::DuplicateField)
    );
}
#[test]
fn invalid_field_encoding_is_malformed() {
    assert_eq!(
        run_limit(SourceMediaType::InvalidEncoding, b"{}", 100).declaration(),
        &MediaDeclaration::Malformed(MediaDeclarationIssue::InvalidEncoding)
    );
}
#[test]
fn too_long_field_is_malformed() {
    assert_eq!(
        run_limit(SourceMediaType::TooLong, b"{}", 100).declaration(),
        &MediaDeclaration::Malformed(MediaDeclarationIssue::TooLong)
    );
}

macro_rules! mapping {
    ($name:ident,$media:expr,$format:expr) => {
        #[test]
        fn $name() {
            let r = run($media, b"");
            match r.classification() {
                SourceClassificationOutcome::Classified(c) => assert_eq!(c.format(), $format),
                o => panic!("{o:?}"),
            }
        }
    };
}
mapping!(map_html, "text/html", SourceFormat::Html);
mapping!(
    map_xhtml,
    "application/xhtml+xml",
    SourceFormat::Xml(XmlProfile::Xhtml)
);
mapping!(map_json, "application/json", SourceFormat::Json);
mapping!(
    map_xml_app,
    "application/xml",
    SourceFormat::Xml(XmlProfile::Generic)
);
mapping!(
    map_xml_text,
    "text/xml",
    SourceFormat::Xml(XmlProfile::Generic)
);
mapping!(map_plain, "text/plain", SourceFormat::PlainText);
mapping!(
    map_json_suffix,
    "application/problem+json",
    SourceFormat::Json
);
mapping!(
    map_xml_suffix,
    "application/atom+xml",
    SourceFormat::Xml(XmlProfile::Generic)
);

macro_rules! unsupported {
    ($name:ident,$media:expr) => {
        #[test]
        fn $name() {
            assert!(matches!(
                run($media, b"x").classification(),
                SourceClassificationOutcome::Unsupported { .. }
            ));
        }
    };
}
unsupported!(unsupported_csv, "text/csv");
unsupported!(unsupported_text_json, "text/json");
unsupported!(unsupported_png, "image/png");
unsupported!(unsupported_vendor, "application/vnd.test");
unsupported!(unsupported_bare_json_suffix, "application/+json");
unsupported!(unsupported_bare_xml_suffix, "application/+xml");
