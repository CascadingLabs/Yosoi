use serde::{Deserialize, Serialize};

use crate::internal::web_capture::SourceMediaType;

const MAX_ESSENCE: usize = 127;
const MAX_LABEL: usize = 63;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MediaDeclarationIssue {
    InvalidEncoding,
    TooLong,
    DuplicateField,
    InvalidSyntax,
}
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum CharsetIssue {
    Invalid,
    Unsupported { normalized: String },
    Conflicting,
}
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum CharsetDeclaration {
    Missing,
    Label { canonical: String, duplicate: bool },
    Issue(CharsetIssue),
}
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum MediaDeclaration {
    Missing,
    Parsed {
        essence: String,
        charset: CharsetDeclaration,
    },
    Malformed(MediaDeclarationIssue),
}

pub fn parse(value: &SourceMediaType) -> MediaDeclaration {
    let text = match value {
        SourceMediaType::Absent => return MediaDeclaration::Missing,
        SourceMediaType::InvalidEncoding => {
            return MediaDeclaration::Malformed(MediaDeclarationIssue::InvalidEncoding);
        }
        SourceMediaType::Duplicate => {
            return MediaDeclaration::Malformed(MediaDeclarationIssue::DuplicateField);
        }
        SourceMediaType::Value(value) => value.as_str(),
        SourceMediaType::TooLong => {
            return MediaDeclaration::Malformed(MediaDeclarationIssue::TooLong);
        }
    };
    parse_text(text).unwrap_or(MediaDeclaration::Malformed(
        MediaDeclarationIssue::InvalidSyntax,
    ))
}

fn parse_text(text: &str) -> Option<MediaDeclaration> {
    if !text.is_ascii() || text.bytes().any(is_forbidden_control) {
        return None;
    }
    let mut cursor = Cursor::new(text.as_bytes());
    cursor.ows();
    let top = cursor.token()?;
    if !cursor.take(b'/') {
        return None;
    }
    let subtype = cursor.token()?;
    let essence_len = top.len().checked_add(subtype.len())?.checked_add(1)?;
    if essence_len > MAX_ESSENCE {
        return None;
    }
    let essence = format!("{}/{}", ascii_lower(top), ascii_lower(subtype));
    cursor.ows();
    let mut labels: Vec<String> = Vec::new();
    while !cursor.done() {
        if !cursor.take(b';') {
            return None;
        }
        cursor.ows();
        let name = cursor.token()?;
        cursor.ows();
        if !cursor.take(b'=') {
            return None;
        }
        cursor.ows();
        let value = if cursor.peek() == Some(b'"') {
            cursor.quoted()?
        } else {
            cursor.token()?.to_vec()
        };
        cursor.ows();
        if name.eq_ignore_ascii_case(b"charset") {
            let trimmed = trim_http_ws(&value);
            if trimmed.is_empty()
                || trimmed.len() > MAX_LABEL
                || !trimmed.iter().all(|b| valid_label_byte(*b))
            {
                return Some(MediaDeclaration::Parsed {
                    essence,
                    charset: CharsetDeclaration::Issue(CharsetIssue::Invalid),
                });
            }
            labels.push(ascii_lower(trimmed));
        }
    }
    let charset = resolve_labels(&labels);
    Some(MediaDeclaration::Parsed { essence, charset })
}

fn resolve_labels(labels: &[String]) -> CharsetDeclaration {
    if labels.is_empty() {
        return CharsetDeclaration::Missing;
    }
    let resolved: Vec<Option<&'static encoding_rs::Encoding>> = labels
        .iter()
        .map(|label| accepted_encoding(label.as_bytes()))
        .collect();
    let Some(first_resolved) = resolved.first().copied() else {
        return CharsetDeclaration::Missing;
    };
    if resolved.iter().skip(1).any(|item| *item != first_resolved) {
        return CharsetDeclaration::Issue(CharsetIssue::Conflicting);
    }
    if let Some(encoding) = first_resolved {
        CharsetDeclaration::Label {
            canonical: encoding.name().to_ascii_lowercase(),
            duplicate: labels.len() > 1,
        }
    } else {
        let Some(first_label) = labels.first() else {
            return CharsetDeclaration::Missing;
        };
        if labels
            .iter()
            .skip(1)
            .all(|label| label.eq_ignore_ascii_case(first_label))
        {
            CharsetDeclaration::Issue(CharsetIssue::Unsupported {
                normalized: first_label.clone(),
            })
        } else {
            CharsetDeclaration::Issue(CharsetIssue::Conflicting)
        }
    }
}
fn accepted_encoding(label: &[u8]) -> Option<&'static encoding_rs::Encoding> {
    let encoding = encoding_rs::Encoding::for_label(label)?;
    (!matches!(encoding.name(), "replacement" | "UTF-7")).then_some(encoding)
}

struct Cursor<'a> {
    bytes: &'a [u8],
    at: usize,
}
impl<'a> Cursor<'a> {
    const fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, at: 0 }
    }
    const fn done(&self) -> bool {
        self.at == self.bytes.len()
    }
    fn peek(&self) -> Option<u8> {
        self.bytes.get(self.at).copied()
    }
    fn take(&mut self, byte: u8) -> bool {
        if self.peek() == Some(byte) {
            let Some(next) = self.at.checked_add(1) else {
                return false;
            };
            self.at = next;
            true
        } else {
            false
        }
    }
    fn ows(&mut self) {
        while matches!(self.peek(), Some(b' ' | b'\t')) {
            let Some(next) = self.at.checked_add(1) else {
                return;
            };
            self.at = next;
        }
    }
    fn token(&mut self) -> Option<&'a [u8]> {
        let start = self.at;
        while self.peek().is_some_and(token) {
            self.at = self.at.checked_add(1)?;
        }
        (self.at > start)
            .then(|| self.bytes.get(start..self.at))
            .flatten()
    }
    fn quoted(&mut self) -> Option<Vec<u8>> {
        if !self.take(b'"') {
            return None;
        }
        let mut out = Vec::new();
        loop {
            match self.peek()? {
                b'"' => {
                    self.at = self.at.checked_add(1)?;
                    return Some(out);
                }
                b'\\' => {
                    self.at = self.at.checked_add(1)?;
                    let escaped = self.peek()?;
                    if is_forbidden_control(escaped) {
                        return None;
                    }
                    out.push(escaped);
                    self.at = self.at.checked_add(1)?;
                }
                byte if byte == b'\t' || (byte >= 0x20 && byte != 0x7f) => {
                    out.push(byte);
                    self.at = self.at.checked_add(1)?;
                }
                _ => return None,
            }
        }
    }
}
fn trim_http_ws(mut value: &[u8]) -> &[u8] {
    while matches!(value.first(), Some(b' ' | b'\t')) {
        value = value.get(1..).unwrap_or_default();
    }
    while matches!(value.last(), Some(b' ' | b'\t')) {
        value = value
            .get(..value.len().saturating_sub(1))
            .unwrap_or_default();
    }
    value
}
fn ascii_lower(value: &[u8]) -> String {
    value
        .iter()
        .map(|b| char::from(b.to_ascii_lowercase()))
        .collect()
}
const fn is_forbidden_control(value: u8) -> bool {
    value < 0x20 && value != b'\t' || value == 0x7f
}
const fn token(value: u8) -> bool {
    value.is_ascii_alphanumeric()
        || matches!(
            value,
            b'!' | b'#'
                | b'$'
                | b'&'
                | b'\''
                | b'*'
                | b'+'
                | b'-'
                | b'.'
                | b'^'
                | b'_'
                | b'`'
                | b'|'
                | b'~'
        )
}
const fn valid_label_byte(value: u8) -> bool {
    value.is_ascii_alphanumeric() || matches!(value, b'-' | b'_' | b'.' | b':')
}
