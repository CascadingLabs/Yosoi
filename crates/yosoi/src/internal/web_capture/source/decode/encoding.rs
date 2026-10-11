use super::super::{CharsetDeclaration, CharsetIssue};
use super::{CharacterDecodingOutcome, DecodingErrorCode, Selection};
use crate::internal::web_capture::{DecodingBasis, DecodingConflict};
use encoding_rs::{Encoding, UTF_8, UTF_16BE, UTF_16LE, WINDOWS_1252};

pub(super) fn bom(bytes: &[u8]) -> Option<Selection> {
    if signature_utf32(bytes) {
        return Some(Err(CharacterDecodingOutcome::UnsupportedEncoding(
            DecodingErrorCode::UnsupportedUtf32,
        )));
    }
    if bytes.starts_with(b"\xef\xbb\xbf") {
        Some(Ok((UTF_8, DecodingBasis::Bom, 3, true, Vec::new())))
    } else if bytes.starts_with(b"\xff\xfe") {
        Some(Ok((UTF_16LE, DecodingBasis::Bom, 2, true, Vec::new())))
    } else if bytes.starts_with(b"\xfe\xff") {
        Some(Ok((UTF_16BE, DecodingBasis::Bom, 2, true, Vec::new())))
    } else {
        None
    }
}
pub(super) fn label(
    value: Option<&CharsetDeclaration>,
    terminal: bool,
) -> Result<Option<&'static Encoding>, CharacterDecodingOutcome> {
    match value {
        Some(CharsetDeclaration::Label { canonical, .. }) => {
            Ok(Encoding::for_label(canonical.as_bytes()))
        }
        Some(CharsetDeclaration::Issue(issue)) if terminal => Err(match issue {
            CharsetIssue::Invalid => {
                CharacterDecodingOutcome::Undecodable(DecodingErrorCode::InvalidCharset)
            }
            CharsetIssue::Conflicting => {
                CharacterDecodingOutcome::Undecodable(DecodingErrorCode::ConflictingCharset)
            }
            CharsetIssue::Unsupported { .. } => {
                CharacterDecodingOutcome::UnsupportedEncoding(DecodingErrorCode::UnsupportedCharset)
            }
        }),
        _ => Ok(None),
    }
}
pub(super) fn select_html(bytes: &[u8], charset: Option<&CharsetDeclaration>) -> Selection {
    if let Some(v) = bom(bytes) {
        return v;
    }
    if let Some(enc) = label(charset, false)? {
        return Ok((enc, DecodingBasis::HttpCharset, 0, false, Vec::new()));
    }
    if let Some(enc) = super::super::html_prescan::encoding(bytes) {
        return Ok((enc, DecodingBasis::HtmlMeta, 0, false, Vec::new()));
    }
    Ok((
        WINDOWS_1252,
        DecodingBasis::HtmlFallback,
        0,
        false,
        Vec::new(),
    ))
}
pub(super) fn select_xml(bytes: &[u8], charset: Option<&CharsetDeclaration>) -> Selection {
    if let Some(v) = bom(bytes) {
        return v;
    }
    if let Some(enc) = label(charset, true)? {
        return Ok((enc, DecodingBasis::HttpCharset, 0, true, Vec::new()));
    }
    if signature_utf32(bytes) {
        return Err(CharacterDecodingOutcome::UnsupportedEncoding(
            DecodingErrorCode::UnsupportedUtf32,
        ));
    }
    if bytes.starts_with(b"<\0?\0x\0m\0l\0") {
        return Ok((
            UTF_16LE,
            DecodingBasis::XmlAutodetection,
            0,
            true,
            Vec::new(),
        ));
    }
    if bytes.starts_with(b"\0<\0?\0x\0m\0l") {
        return Ok((
            UTF_16BE,
            DecodingBasis::XmlAutodetection,
            0,
            true,
            Vec::new(),
        ));
    }
    match super::super::xml_declaration::inspect(bytes) {
        super::super::xml_declaration::XmlDeclarationEvidence::Encoding(enc) => {
            Ok((enc, DecodingBasis::XmlDeclaration, 0, true, Vec::new()))
        }
        super::super::xml_declaration::XmlDeclarationEvidence::Unsupported => Err(
            CharacterDecodingOutcome::UnsupportedEncoding(DecodingErrorCode::UnsupportedCharset),
        ),
        super::super::xml_declaration::XmlDeclarationEvidence::Conflicting
        | super::super::xml_declaration::XmlDeclarationEvidence::Malformed => Err(
            CharacterDecodingOutcome::Undecodable(DecodingErrorCode::InvalidCharset),
        ),
        super::super::xml_declaration::XmlDeclarationEvidence::Absent => {
            Ok((UTF_8, DecodingBasis::XmlDefaultUtf8, 0, true, Vec::new()))
        }
    }
}
pub(super) fn select_json(bytes: &[u8], charset: Option<&CharsetDeclaration>) -> Selection {
    if signature_utf32(bytes) || bytes.starts_with(b"\xff\xfe") || bytes.starts_with(b"\xfe\xff") {
        return Err(CharacterDecodingOutcome::UnsupportedEncoding(
            DecodingErrorCode::UnsupportedJsonUnicode,
        ));
    }
    let mut c = Vec::new();
    if !matches!(charset, None | Some(CharsetDeclaration::Missing)) {
        c.push(DecodingConflict::JsonCharsetIgnored);
    }
    let skip = if bytes.starts_with(b"\xef\xbb\xbf") {
        c.push(DecodingConflict::JsonBomAccepted);
        3
    } else {
        0
    };
    Ok((UTF_8, DecodingBasis::JsonUtf8, skip, true, c))
}
pub(super) fn select_plain(bytes: &[u8], charset: Option<&CharsetDeclaration>) -> Selection {
    if let Some(v) = bom(bytes) {
        return v;
    }
    if let Some(enc) = label(charset, true)? {
        return Ok((enc, DecodingBasis::HttpCharset, 0, true, Vec::new()));
    }
    Ok((
        UTF_8,
        DecodingBasis::PlainUtf8Validation,
        0,
        true,
        Vec::new(),
    ))
}
pub(super) fn signature_utf32(bytes: &[u8]) -> bool {
    bytes.starts_with(b"\0\0\xfe\xff")
        || bytes.starts_with(b"\xff\xfe\0\0")
        || bytes.starts_with(b"\0\0\0<")
        || bytes.starts_with(b"<\0\0\0")
}
pub(super) fn in_band(bytes: &[u8]) -> Option<&'static Encoding> {
    match super::super::xml_declaration::inspect(bytes) {
        super::super::xml_declaration::XmlDeclarationEvidence::Encoding(v) => Some(v),
        _ => super::super::html_prescan::encoding(bytes),
    }
}
pub(super) fn add_conflicts(
    bytes: &[u8],
    charset: Option<&CharsetDeclaration>,
    selected: &'static Encoding,
    out: &mut Vec<DecodingConflict>,
) {
    if matches!(charset,Some(CharsetDeclaration::Label{canonical,..}) if Encoding::for_label(canonical.as_bytes()).is_some_and(|v|v!=selected))
    {
        out.push(DecodingConflict::HttpCharset);
    }
    if in_band(bytes).is_some_and(|v| v != selected) {
        out.push(DecodingConflict::InBandDeclaration);
    }
    if (bytes.starts_with(b"<\0") && selected != UTF_16LE)
        || (bytes.starts_with(b"\0<") && selected != UTF_16BE)
    {
        out.push(DecodingConflict::EncodingSignature);
    }
}
