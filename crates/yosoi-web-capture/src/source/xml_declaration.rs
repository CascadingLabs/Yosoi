use encoding_rs::Encoding;

const LIMIT: usize = 1_024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum XmlDeclarationEvidence {
    Absent,
    Encoding(&'static Encoding),
    Unsupported,
    Malformed,
    Conflicting,
}

pub(super) fn inspect(bytes: &[u8]) -> XmlDeclarationEvidence {
    let bounded = bytes.get(..bytes.len().min(LIMIT)).unwrap_or_default();
    let input = bounded.strip_prefix(b"\xef\xbb\xbf").unwrap_or(bounded);
    if !input.starts_with(b"<?xml") {
        return XmlDeclarationEvidence::Absent;
    }
    if !input.get(5).is_some_and(|byte| is_space(*byte)) {
        return XmlDeclarationEvidence::Absent;
    }
    let mut cursor = Cursor { input, at: 5 };
    if !cursor.required_space() || cursor.name() != Some(b"version".as_slice()) {
        return XmlDeclarationEvidence::Malformed;
    }
    let Some(version) = cursor.assignment() else {
        return XmlDeclarationEvidence::Malformed;
    };
    if !matches!(version, b"1.0" | b"1.1") {
        return XmlDeclarationEvidence::Malformed;
    }

    let mut encoding = None;
    let mut standalone = false;
    loop {
        let had_space = cursor.space();
        if cursor.consume(b"?>") {
            return encoding.map_or(
                XmlDeclarationEvidence::Absent,
                XmlDeclarationEvidence::Encoding,
            );
        }
        if !had_space {
            return XmlDeclarationEvidence::Malformed;
        }
        let Some(name) = cursor.name() else {
            return XmlDeclarationEvidence::Malformed;
        };
        let Some(value) = cursor.assignment() else {
            return XmlDeclarationEvidence::Malformed;
        };
        match name {
            b"encoding" if encoding.is_some() => return XmlDeclarationEvidence::Conflicting,
            b"encoding" if !standalone => match accepted(value) {
                Ok(found) => encoding = Some(found),
                Err(LabelError::Unsupported) => return XmlDeclarationEvidence::Unsupported,
                Err(LabelError::Invalid) => return XmlDeclarationEvidence::Malformed,
            },
            b"standalone" if !standalone && matches!(value, b"yes" | b"no") => standalone = true,
            _ => return XmlDeclarationEvidence::Malformed,
        }
    }
}

#[derive(Clone, Copy)]
enum LabelError {
    Invalid,
    Unsupported,
}
fn accepted(label: &[u8]) -> Result<&'static Encoding, LabelError> {
    if !valid_encoding_name(label) {
        return Err(LabelError::Invalid);
    }
    Encoding::for_label(label)
        .filter(|encoding| !matches!(encoding.name(), "replacement" | "UTF-7"))
        .ok_or(LabelError::Unsupported)
}
fn valid_encoding_name(label: &[u8]) -> bool {
    label.first().is_some_and(u8::is_ascii_alphabetic)
        && label
            .iter()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
}

struct Cursor<'a> {
    input: &'a [u8],
    at: usize,
}
impl<'a> Cursor<'a> {
    fn consume(&mut self, expected: &[u8]) -> bool {
        if self
            .input
            .get(self.at..)
            .is_some_and(|rest| rest.starts_with(expected))
        {
            self.at = self.at.saturating_add(expected.len());
            true
        } else {
            false
        }
    }
    fn space(&mut self) -> bool {
        let start = self.at;
        while self.input.get(self.at).is_some_and(|byte| is_space(*byte)) {
            self.at = self.at.saturating_add(1);
        }
        self.at > start
    }
    fn required_space(&mut self) -> bool {
        self.space()
    }
    fn name(&mut self) -> Option<&'a [u8]> {
        let start = self.at;
        while self.input.get(self.at).is_some_and(u8::is_ascii_alphabetic) {
            self.at = self.at.saturating_add(1);
        }
        (self.at > start)
            .then(|| self.input.get(start..self.at))
            .flatten()
    }
    fn assignment(&mut self) -> Option<&'a [u8]> {
        self.space();
        if self.input.get(self.at) != Some(&b'=') {
            return None;
        }
        self.at = self.at.saturating_add(1);
        self.space();
        self.quoted()
    }
    fn quoted(&mut self) -> Option<&'a [u8]> {
        let quote = *self.input.get(self.at)?;
        if !matches!(quote, b'\'' | b'"') {
            return None;
        }
        self.at = self.at.saturating_add(1);
        let start = self.at;
        while let Some(byte) = self.input.get(self.at) {
            if *byte == quote {
                let value = self.input.get(start..self.at);
                self.at = self.at.saturating_add(1);
                return value;
            }
            if *byte < 0x20 || *byte == 0x7f {
                return None;
            }
            self.at = self.at.saturating_add(1);
        }
        None
    }
}
const fn is_space(byte: u8) -> bool {
    matches!(byte, b' ' | b'\t' | b'\r' | b'\n')
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn grammar_table() {
        let cases = [
            (
                b"<?xml version='1.0' encoding='utf-8'?>".as_slice(),
                XmlDeclarationEvidence::Encoding(encoding_rs::UTF_8),
            ),
            (b"<?xml version = \"1.1\"?>", XmlDeclarationEvidence::Absent),
            (
                b"<?XML version='1.0' encoding='utf-8'?>",
                XmlDeclarationEvidence::Absent,
            ),
            (
                b" <?xml version='1.0' encoding='utf-8'?>",
                XmlDeclarationEvidence::Absent,
            ),
            (
                b"<?xml encoding='utf-8'?>",
                XmlDeclarationEvidence::Malformed,
            ),
            (
                b"<?xml version='1.0'encoding='utf-8'?>",
                XmlDeclarationEvidence::Malformed,
            ),
            (
                b"<?xml version='1.0' encoding=\"utf-8'?>",
                XmlDeclarationEvidence::Malformed,
            ),
            (
                b"<?xml version='1.0' encoding=''?>",
                XmlDeclarationEvidence::Malformed,
            ),
            (
                b"<?xml version='1.0' encoding='utf-7'?>",
                XmlDeclarationEvidence::Unsupported,
            ),
            (
                b"<?xml version='1.0' encoding='utf-8' encoding='utf-8'?>",
                XmlDeclarationEvidence::Conflicting,
            ),
            (b"<x encoding='utf-8'/>", XmlDeclarationEvidence::Absent),
            (b"<?xml version='1.0'>", XmlDeclarationEvidence::Malformed),
        ];
        for (input, expected) in cases {
            assert_eq!(inspect(input), expected, "{input:?}");
        }
    }
    #[test]
    fn utf8_bom_and_bound_are_handled() {
        assert_eq!(
            inspect(b"\xef\xbb\xbf<?xml version='1.0' encoding='utf-8'?>"),
            XmlDeclarationEvidence::Encoding(encoding_rs::UTF_8)
        );
        let declaration = b"<?xml version='1.0' encoding='utf-8'?>";
        let mut exact = declaration.to_vec();
        exact.resize(1_024, b' ');
        assert_eq!(
            inspect(&exact),
            XmlDeclarationEvidence::Encoding(encoding_rs::UTF_8)
        );
        let mut straddle = vec![b' '; 990];
        straddle.splice(..5, b"<?xml".iter().copied());
        assert_ne!(
            inspect(&straddle),
            XmlDeclarationEvidence::Encoding(encoding_rs::UTF_8)
        );
    }
}
