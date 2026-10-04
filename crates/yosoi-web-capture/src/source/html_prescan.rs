use encoding_rs::{Encoding, UTF_8, WINDOWS_1252};

const LIMIT: usize = 1_024;

pub(super) fn encoding(bytes: &[u8]) -> Option<&'static Encoding> {
    let input = bytes.get(..bytes.len().min(LIMIT)).unwrap_or_default();
    let mut cursor = 0;
    while cursor < input.len() {
        if starts_ascii_case(input, cursor, b"<!--") {
            cursor = comment_end(input, cursor.saturating_add(4))?;
            continue;
        }
        if input.get(cursor) != Some(&b'<') {
            cursor = cursor.saturating_add(1);
            continue;
        }
        if matches!(input.get(cursor.saturating_add(1)), Some(b'!' | b'?')) {
            cursor = tag_end(input, cursor.saturating_add(2))?.saturating_add(1);
            continue;
        }
        let start = cursor.saturating_add(1);
        let closing = input.get(start) == Some(&b'/');
        let name_start = start.saturating_add(usize::from(closing));
        let name_end = name_end(input, name_start);
        let name = input.get(name_start..name_end)?;
        if name.is_empty() || !tag_name_delimiter(input.get(name_end).copied()) {
            cursor = cursor.saturating_add(1);
            continue;
        }
        let end = tag_end(input, name_end)?;
        if !closing && (name.eq_ignore_ascii_case(b"script") || name.eq_ignore_ascii_case(b"style"))
        {
            cursor = raw_text_end(input, end.saturating_add(1), name)?;
            continue;
        }
        if !closing && name.eq_ignore_ascii_case(b"meta") {
            let attrs = input.get(name_end..end).unwrap_or_default();
            if let Some(found) = meta_encoding(attrs) {
                return Some(adjust(found));
            }
        }
        cursor = end.saturating_add(1);
    }
    None
}

fn tag_end(input: &[u8], mut at: usize) -> Option<usize> {
    let mut quote = None;
    while let Some(&byte) = input.get(at) {
        match (quote, byte) {
            (None, b'\'' | b'"') => quote = Some(byte),
            (Some(expected), value) if expected == value => quote = None,
            (None, b'>') => return Some(at),
            _ => {}
        }
        at = at.saturating_add(1);
    }
    None
}

fn comment_end(input: &[u8], mut at: usize) -> Option<usize> {
    while at < input.len() {
        if input.get(at..).is_some_and(|rest| rest.starts_with(b"-->")) {
            return Some(at.saturating_add(3));
        }
        at = at.saturating_add(1);
    }
    None
}

fn raw_text_end(input: &[u8], mut at: usize, name: &[u8]) -> Option<usize> {
    while at < input.len() {
        if input.get(at..at.saturating_add(2)) == Some(b"</") {
            let start = at.saturating_add(2);
            let end = start.saturating_add(name.len());
            if input
                .get(start..end)
                .is_some_and(|found| found.eq_ignore_ascii_case(name))
                && tag_name_delimiter(input.get(end).copied())
            {
                return Some(tag_end(input, end)?.saturating_add(1));
            }
        }
        at = at.saturating_add(1);
    }
    None
}

fn name_end(input: &[u8], mut at: usize) -> usize {
    while input.get(at).is_some_and(u8::is_ascii_alphanumeric) {
        at = at.saturating_add(1);
    }
    at
}
fn tag_name_delimiter(value: Option<u8>) -> bool {
    value.is_some_and(|byte| is_space(byte) || matches!(byte, b'/' | b'>'))
}
fn starts_ascii_case(input: &[u8], at: usize, expected: &[u8]) -> bool {
    input
        .get(at..at.saturating_add(expected.len()))
        .is_some_and(|found| found.eq_ignore_ascii_case(expected))
}

fn meta_encoding(mut attrs: &[u8]) -> Option<&'static Encoding> {
    let mut charset = None;
    let mut content = None;
    let mut pragma = false;
    let mut seen_charset = false;
    let mut seen_content = false;
    let mut seen_pragma = false;
    while let Some((name, value, rest)) = next_attr(attrs) {
        attrs = rest;
        if name.eq_ignore_ascii_case(b"charset") && !seen_charset {
            seen_charset = true;
            charset = label(value);
        } else if name.eq_ignore_ascii_case(b"content") && !seen_content {
            seen_content = true;
            content = content_charset(value);
        } else if name.eq_ignore_ascii_case(b"http-equiv") && !seen_pragma {
            seen_pragma = true;
            pragma = value.eq_ignore_ascii_case(b"content-type");
        }
    }
    if seen_charset {
        charset
    } else if pragma {
        content
    } else {
        None
    }
}

fn next_attr(mut input: &[u8]) -> Option<(&[u8], &[u8], &[u8])> {
    input = trim_start(input);
    if input.is_empty() || input.first() == Some(&b'/') {
        return None;
    }
    let name_len = input
        .iter()
        .position(|byte| is_space(*byte) || matches!(*byte, b'=' | b'/'))
        .unwrap_or(input.len());
    if name_len == 0 {
        return next_attr(input.get(1..).unwrap_or_default());
    }
    let name = input.get(..name_len)?;
    input = trim_start(input.get(name_len..)?);
    if input.first() != Some(&b'=') {
        return Some((name, b"", input));
    }
    input = trim_start(input.get(1..)?);
    if let Some(quote @ (b'\'' | b'"')) = input.first().copied() {
        let value_start = input.get(1..)?;
        let end = value_start.iter().position(|byte| *byte == quote)?;
        return Some((
            name,
            value_start.get(..end)?,
            value_start.get(end.saturating_add(1)..)?,
        ));
    }
    let end = input
        .iter()
        .position(|byte| is_space(*byte) || *byte == b'/')
        .unwrap_or(input.len());
    Some((name, input.get(..end)?, input.get(end..)?))
}

fn content_charset(value: &[u8]) -> Option<&'static Encoding> {
    for (at, window) in value.windows(7).enumerate() {
        if !window.eq_ignore_ascii_case(b"charset") {
            continue;
        }
        let mut rest = trim_start(value.get(at.saturating_add(7)..)?);
        if rest.first() != Some(&b'=') {
            continue;
        }
        rest = trim_start(rest.get(1..)?);
        let quote = rest
            .first()
            .copied()
            .filter(|byte| matches!(byte, b'\'' | b'"'));
        if quote.is_some() {
            rest = rest.get(1..)?;
        }
        let end = rest
            .iter()
            .position(|byte| is_space(*byte) || matches!(*byte, b';' | b'\'' | b'"'))
            .unwrap_or(rest.len());
        return label(rest.get(..end)?);
    }
    None
}
fn label(value: &[u8]) -> Option<&'static Encoding> {
    let encoding = Encoding::for_label(value)?;
    (!matches!(encoding.name(), "replacement" | "UTF-7")).then_some(encoding)
}
fn adjust(value: &'static Encoding) -> &'static Encoding {
    match value.name() {
        "UTF-16LE" | "UTF-16BE" => UTF_8,
        "x-user-defined" => WINDOWS_1252,
        _ => value,
    }
}
fn trim_start(mut value: &[u8]) -> &[u8] {
    while value.first().is_some_and(|byte| is_space(*byte)) {
        value = value.get(1..).unwrap_or_default();
    }
    value
}
const fn is_space(value: u8) -> bool {
    matches!(value, b'\t' | b'\n' | 0x0c | b'\r' | b' ')
}

#[cfg(test)]
mod tests {
    use super::*;
    fn name(input: &[u8]) -> Option<&'static str> {
        encoding(input).map(Encoding::name)
    }

    #[test]
    fn adversarial_structure_cases() {
        let cases: &[(&[u8], Option<&str>)] = &[
            (b"<meta data='>' charset=UTF-8>", Some("UTF-8")),
            (b"<!-- <meta charset=utf-8> -->", None),
            (b"<script>'</nope><meta charset=utf-8>'</script>", None),
            (b"<style><meta charset=utf-8></style>", None),
            (b"<meta charset=utf-8", None),
            (b"<!bogus <meta charset=utf-8>>", None),
            (b"<div charset=utf-8>", None),
            (b"<MeTa\tChArSeT = 'utf-8' />", Some("UTF-8")),
        ];
        for (input, expected) in cases {
            assert_eq!(name(input), *expected, "{input:?}");
        }
    }

    #[test]
    fn first_occurrences_and_pragma_rules() {
        let cases: &[(&[u8], Option<&str>)] = &[
            (b"<meta charset=x charset=utf-8>", None),
            (b"<meta charset=utf-8 charset=x>", Some("UTF-8")),
            (b"<meta content='text/html;charset=utf-8'>", None),
            (
                b"<meta content='text/html; charset = \"utf-8\"' http-equiv=content-type>",
                Some("UTF-8"),
            ),
            (
                b"<meta http-equiv=content-type content='charset=utf-8'>",
                Some("UTF-8"),
            ),
            (
                b"<meta http-equiv=x http-equiv=content-type content='charset=utf-8'>",
                None,
            ),
            (
                b"<meta content='charset=x' content='charset=utf-8' http-equiv=content-type>",
                None,
            ),
        ];
        for (input, expected) in cases {
            assert_eq!(name(input), *expected, "{input:?}");
        }
    }

    #[test]
    fn bounds_adjustments_and_first_valid() {
        let mut exact = vec![b' '; 1_004];
        exact.extend_from_slice(b"<meta charset=utf-8>");
        assert_eq!(name(&exact), Some("UTF-8"));
        let mut straddle = vec![b' '; 1_005];
        straddle.extend_from_slice(b"<meta charset=utf-8>");
        assert_eq!(name(&straddle), None);
        assert_eq!(name(b"<meta charset=utf-16le>"), Some("UTF-8"));
        assert_eq!(name(b"<meta charset=x-user-defined>"), Some("windows-1252"));
        assert_eq!(name(b"<meta charset=replacement>"), None);
        assert_eq!(
            name(b"<meta charset=windows-1252><meta charset=utf-8>"),
            Some("windows-1252")
        );
    }
}
