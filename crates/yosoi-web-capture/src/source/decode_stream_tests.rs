use encoding_rs::{GBK, SHIFT_JIS, UTF_8, UTF_16BE, UTF_16LE};

use super::bounded_decode;
use crate::source::DecodingErrorCode;

fn incomplete(bytes: &[u8], encoding: &'static encoding_rs::Encoding, strict: bool) {
    let decoded = bounded_decode(bytes, encoding, 100, strict, true).expect("terminal prefix");
    assert!(decoded.incomplete, "{bytes:x?} with {}", encoding.name());
    assert_eq!(decoded.replacements, 0);
}

fn invalid(bytes: &[u8], encoding: &'static encoding_rs::Encoding) {
    assert_eq!(
        bounded_decode(bytes, encoding, 100, true, true).err(),
        Some(DecodingErrorCode::InvalidSequence),
        "{bytes:x?} with {}",
        encoding.name()
    );
    let html = bounded_decode(bytes, encoding, 100, false, true).expect("replacement policy");
    assert!(!html.incomplete);
    assert!(html.replacements > 0);
}

#[test]
fn utf8_terminal_prefixes_are_distinct_from_invalid_bytes() {
    for bytes in [&[0xf0][..], &[0xf0, 0x9f][..], &[0xf0, 0x9f, 0x92][..]] {
        incomplete(bytes, UTF_8, true);
        incomplete(bytes, UTF_8, false);
    }
    let complete = bounded_decode(&[0xf0, 0x9f, 0x92, 0xa9], UTF_8, 100, true, true).unwrap();
    assert!(!complete.incomplete);
    invalid(&[0xff], UTF_8);
}

#[test]
fn utf16_terminal_code_units_are_classified_exactly() {
    for encoding in [UTF_16LE, UTF_16BE] {
        incomplete(&[0x41], encoding, true);
    }
    incomplete(&[0x00, 0xd8], UTF_16LE, true);
    incomplete(&[0xd8, 0x00], UTF_16BE, true);
    invalid(&[0x00, 0xdc], UTF_16LE);
    invalid(&[0xdc, 0x00], UTF_16BE);
}

#[test]
fn legacy_terminal_leads_are_not_conflated_with_invalid_bytes() {
    incomplete(&[0x82], SHIFT_JIS, true);
    incomplete(&[0x81], GBK, true);
    invalid(&[0x82, 0x20], SHIFT_JIS);
    invalid(&[0x81, 0x20], GBK);
}
