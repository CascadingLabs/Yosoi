use super::*;
use yosoi_web_capture::{
    ClassificationBasis, ClassificationExtent, DeclarationDisagreement,
    SourceClassificationOutcome, SourceFormat, UnknownReason, XmlProfile,
};

fn sniffed(bytes: &[u8]) -> SourceFormat {
    match missing(bytes).classification() {
        SourceClassificationOutcome::Classified(c) => {
            assert_eq!(c.basis(), ClassificationBasis::Sniffed);
            c.format()
        }
        other => panic!("{other:?}"),
    }
}
macro_rules! html_yes {
    ($name:ident,$bytes:expr) => {
        #[test]
        fn $name() {
            assert_eq!(sniffed($bytes), SourceFormat::Html);
        }
    };
}
html_yes!(html_tag, b"<html>");
html_yes!(html_upper, b"<HTML>");
html_yes!(head, b"<head>");
html_yes!(body, b"<body>");
html_yes!(script, b"<script>");
html_yes!(iframe, b"<iframe>");
html_yes!(h1, b"<h1>");
html_yes!(div, b"<div>");
html_yes!(font, b"<font>");
html_yes!(table, b"<table>");
html_yes!(a_tag, b"<a>");
html_yes!(style, b"<style>");
html_yes!(title, b"<title>");
html_yes!(b_tag, b"<b>");
html_yes!(br, b"<br>");
html_yes!(p_tag, b"<p>");
html_yes!(doctype, b"<!DOCTYPE HTML>");
html_yes!(doctype_mixed, b"<!DoCtYpE hTmL>");
html_yes!(leading_space, b" \t\r\n<html>");
html_yes!(terminator_space, b"<html x>");
html_yes!(terminator_tab, b"<html\tx>");
html_yes!(terminator_lf, b"<html\nx>");
html_yes!(terminator_cr, b"<html\rx>");
html_yes!(terminator_formfeed, b"<html\x0cx>");
html_yes!(terminator_gt, b"<html>");

macro_rules! no_html {
    ($name:ident,$bytes:expr) => {
        #[test]
        fn $name() {
            assert!(matches!(
                missing($bytes).classification(),
                SourceClassificationOutcome::Unknown {
                    reason: UnknownReason::NoStrongSignature,
                    ..
                }
            ));
        }
    };
}
no_html!(terminator_equal, b"<html=x>");
no_html!(terminator_colon, b"<html:x>");
no_html!(terminator_nul, b"<html\0>");
no_html!(terminator_vtab, b"<html\x0b>");
no_html!(terminator_slash, b"<html/x>");
no_html!(terminator_nonascii, b"<html\x80>");
no_html!(prefix_only, b"<htmlx>");
no_html!(closing_tag, b"</html>");
no_html!(doctype_xml, b"<!doctype xml>");
html_yes!(comment_html, b"<!--<html>-->");
no_html!(plain_scalar, b"42");
no_html!(json_true, b"true");
no_html!(json_string, b"\"x\"");

macro_rules! xml_yes {
    ($name:ident,$bytes:expr) => {
        #[test]
        fn $name() {
            assert_eq!(sniffed($bytes), SourceFormat::Xml(XmlProfile::Generic));
        }
    };
}
xml_yes!(xml_decl, b"<?xml version='1.0'?>");
no_html!(xml_decl_upper, b"<?XML version='1.0'?>");
xml_yes!(xml_leading_ws, b" \t<?xml?>");
xml_yes!(xml_utf8_bom, b"\xef\xbb\xbf<?xml?>");
xml_yes!(xml_utf16le_bom, b"\xff\xfe<\0?\0x\0m\0l\0");
xml_yes!(xml_utf16be_bom, b"\xfe\xff\0<\0?\0x\0m\0l");
xml_yes!(xml_utf16le_signature, b"<\0?\0x\0m\0l\0");
xml_yes!(xml_utf16be_signature, b"\0<\0?\0x\0m\0l");

macro_rules! json_yes {
    ($name:ident,$bytes:expr) => {
        #[test]
        fn $name() {
            assert_eq!(sniffed($bytes), SourceFormat::Json);
        }
    };
}
json_yes!(json_object, b"{}");
json_yes!(json_array, b"[]");
json_yes!(json_object_prefix, b"{");
json_yes!(json_array_prefix, b"[");
json_yes!(json_space, b" \t\r\n{");
json_yes!(json_utf8_bom, b"\xef\xbb\xbf{");
no_html!(json_nul_before, b"\0{");
no_html!(json_scalar_null, b"null");
no_html!(json_scalar_false, b"false");
no_html!(json_number, b"0");

#[test]
fn empty_is_exact_unknown_reason() {
    assert!(
        matches!(missing(b"").classification(), SourceClassificationOutcome::Unknown { reason: UnknownReason::Empty, candidates, extent: ClassificationExtent::Complete } if candidates.is_empty())
    );
}
#[test]
fn declaration_support_is_visible() {
    let r = run("text/html", b"<html>");
    match r.classification() {
        SourceClassificationOutcome::Classified(c) => {
            assert_eq!(c.disagreement(), DeclarationDisagreement::Supports);
        }
        o => panic!("{o:?}"),
    }
}
#[test]
fn declaration_conflict_is_visible() {
    let r = run("text/html", b"{}");
    match r.classification() {
        SourceClassificationOutcome::Classified(c) => assert_eq!(
            c.disagreement(),
            DeclarationDisagreement::Conflicts(SourceFormat::Json)
        ),
        o => panic!("{o:?}"),
    }
}
#[test]
fn generic_uses_signature() {
    assert_eq!(
        match run("application/octet-stream", b"{}").classification() {
            SourceClassificationOutcome::Classified(c) => c.format(),
            o => panic!("{o:?}"),
        },
        SourceFormat::Json
    );
}
#[test]
fn unsupported_retains_deterministic_candidate_order() {
    match run("image/png", b"<html>{").classification() {
        SourceClassificationOutcome::Unsupported {
            candidates,
            disagreement,
            ..
        } => {
            assert_eq!(candidates.as_slice(), [SourceFormat::Html]);
            assert_eq!(
                *disagreement,
                DeclarationDisagreement::Conflicts(SourceFormat::Html)
            );
        }
        o => panic!("{o:?}"),
    }
}
#[test]
fn signature_ending_exactly_at_4096_is_seen() {
    let mut b = vec![b' '; 4090];
    b.extend_from_slice(b"<html>");
    assert_eq!(sniffed(&b), SourceFormat::Html);
}
#[test]
fn signature_starting_at_4096_is_not_seen() {
    let mut b = vec![b' '; 4096];
    b.extend_from_slice(b"<html>");
    assert!(matches!(
        missing(&b).classification(),
        SourceClassificationOutcome::Unknown { .. }
    ));
}
#[test]
fn signature_straddling_4096_is_not_seen() {
    let mut b = vec![b' '; 4093];
    b.extend_from_slice(b"<html>");
    assert!(matches!(
        missing(&b).classification(),
        SourceClassificationOutcome::Unknown { .. }
    ));
}
#[test]
fn json_marker_at_4095_is_seen() {
    let mut b = vec![b' '; 4095];
    b.push(b'{');
    assert_eq!(sniffed(&b), SourceFormat::Json);
}
#[test]
fn json_marker_at_4096_is_not_seen() {
    let mut b = vec![b' '; 4096];
    b.push(b'{');
    assert!(matches!(
        missing(&b).classification(),
        SourceClassificationOutcome::Unknown { .. }
    ));
}
