use super::{SourceFormat, XmlProfile};

pub const SNIFF_LIMIT: usize = 4_096;

// The HTML entries and terminator rule are the byte patterns from the MIME
// Sniffing Standard. ASCII letters are compared through a 0xDF mask.
const HTML_PATTERNS: &[&[u8]] = &[
    b"<!DOCTYPE HTML",
    b"<HTML",
    b"<HEAD",
    b"<SCRIPT",
    b"<IFRAME",
    b"<H1",
    b"<DIV",
    b"<FONT",
    b"<TABLE",
    b"<A",
    b"<STYLE",
    b"<TITLE",
    b"<B",
    b"<BODY",
    b"<BR",
    b"<P",
    b"<!--",
];

pub(super) fn detect(bytes: &[u8]) -> Vec<SourceFormat> {
    let bounded = bytes
        .get(..bytes.len().min(SNIFF_LIMIT))
        .unwrap_or_default();
    let mut result = Vec::with_capacity(3);
    if html(bounded) {
        result.push(SourceFormat::Html);
    }
    if xml(bounded) {
        result.push(SourceFormat::Xml(XmlProfile::Generic));
    }
    if json(bounded) {
        result.push(SourceFormat::Json);
    }
    result
}

fn html(bytes: &[u8]) -> bool {
    let value = trim_leading_ws(bytes);
    HTML_PATTERNS.iter().any(|pattern| {
        masked_prefix(value, pattern)
            && (pattern == &b"<!--".as_slice()
                || value
                    .get(pattern.len())
                    .is_some_and(|byte| is_tag_terminator(*byte)))
    })
}

fn masked_prefix(value: &[u8], pattern: &[u8]) -> bool {
    let Some(prefix) = value.get(..pattern.len()) else {
        return false;
    };
    prefix
        .iter()
        .zip(pattern)
        .all(|(actual, expected)| actual & 0xdf == expected & 0xdf)
}

fn xml(bytes: &[u8]) -> bool {
    // BOM patterns are anchored at offset zero. Only the ASCII signature permits
    // leading whitespace under the MIME sniff table.
    bytes.starts_with(b"\xef\xbb\xbf<?xml")
        || bytes.starts_with(b"\xff\xfe<\0?\0x\0m\0l\0")
        || bytes.starts_with(b"\xfe\xff\0<\0?\0x\0m\0l")
        || bytes.starts_with(b"\0\0\xfe\xff\0\0\0<\0\0\0?\0\0\0x\0\0\0m\0\0\0l")
        || bytes.starts_with(b"\xff\xfe\0\0<\0\0\0?\0\0\0x\0\0\0m\0\0\0l\0\0\0")
        || bytes.starts_with(b"<\0?\0x\0m\0l\0")
        || bytes.starts_with(b"\0<\0?\0x\0m\0l")
        || bytes.starts_with(b"\0\0\0<\0\0\0?\0\0\0x\0\0\0m\0\0\0l")
        || bytes.starts_with(b"<\0\0\0?\0\0\0x\0\0\0m\0\0\0l\0\0\0")
        || trim_leading_ws(bytes).starts_with(b"<?xml")
}

fn json(bytes: &[u8]) -> bool {
    // CAS-305 intentionally recognizes only container starts, not scalar JSON.
    let value = bytes.strip_prefix(b"\xef\xbb\xbf").unwrap_or(bytes);
    matches!(trim_leading_json_ws(value).first(), Some(b'{' | b'['))
}

fn trim_leading_ws(bytes: &[u8]) -> &[u8] {
    let count = bytes.iter().take_while(|byte| is_html_ws(**byte)).count();
    bytes.get(count..).unwrap_or_default()
}
fn trim_leading_json_ws(bytes: &[u8]) -> &[u8] {
    let count = bytes.iter().take_while(|byte| is_json_ws(**byte)).count();
    bytes.get(count..).unwrap_or_default()
}
const fn is_html_ws(byte: u8) -> bool {
    matches!(byte, b'\t' | b'\n' | 0x0c | b'\r' | b' ')
}
const fn is_json_ws(byte: u8) -> bool {
    matches!(byte, b'\t' | b'\n' | b'\r' | b' ')
}
const fn is_tag_terminator(byte: u8) -> bool {
    is_html_ws(byte) || byte == b'>'
}
