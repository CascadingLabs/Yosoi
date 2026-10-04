#![allow(clippy::result_large_err)]

mod artifact;

use std::fmt;

use encoding_rs::{Encoding, UTF_8, UTF_16BE, UTF_16LE, WINDOWS_1252};
use serde::{Deserialize, Serialize};
use yosoi_types::{ArtifactRef, Producer, Schema, Sha256Digest};

use super::{
    CharsetDeclaration, CharsetIssue, DecodedOutputIdentity, MediaDeclaration,
    SourceClassificationOutcome, SourceFormat, digest,
};
use crate::{
    ByteCount, DecodedExtent, DecodedSourceArtifact, DecodedSourceInterpretation, DecodingBasis,
    DecodingConflict, RetainedSource, RetainedSourceExtent, SourceArtifactRef,
};

/// Canonical media essence for a decoded source payload.
///
/// This vendor type deliberately distinguishes the canonical UTF-8 view from
/// both `text/plain` and the source format from which the view was derived.
pub const DECODED_SOURCE_UTF8_MEDIA_TYPE: &str = "application/vnd.yosoi.decoded-source+utf8";

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct SelectedEncoding(&'static str);
impl SelectedEncoding {
    pub const fn canonical_name(&self) -> &'static str {
        self.0
    }
}
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DecodingErrorCode {
    NotClassified,
    InvalidCharset,
    ConflictingCharset,
    UnsupportedCharset,
    UnsupportedUtf32,
    UnsupportedJsonUnicode,
    InvalidSequence,
    ArtifactMetadata,
}
#[derive(Clone, Eq, PartialEq)]
pub struct DecodedSourceView {
    utf8: String,
    source: SourceArtifactRef,
    artifact: DecodedSourceArtifact,
    encoding: SelectedEncoding,
    basis: DecodingBasis,
    replacements: u64,
    conflicts: Vec<DecodingConflict>,
    source_truncated: bool,
    incomplete_terminal_sequence: bool,
}
impl DecodedSourceView {
    pub fn text(&self) -> &str {
        &self.utf8
    }

    pub(crate) fn into_bytes(self) -> Vec<u8> {
        self.utf8.into_bytes()
    }
    pub const fn bytes(&self) -> &[u8] {
        self.utf8.as_bytes()
    }
    pub fn size(&self) -> u64 {
        self.artifact
            .metadata()
            .extent()
            .retained_bytes()
            .map_or(0, ByteCount::get)
    }
    pub fn digest(&self) -> Sha256Digest {
        self.artifact
            .metadata()
            .content_digest()
            .unwrap_or_else(|| digest(self.bytes()))
    }
    pub const fn source(&self) -> SourceArtifactRef {
        self.source
    }
    pub const fn artifact(&self) -> &DecodedSourceArtifact {
        &self.artifact
    }
    pub const fn producer(&self) -> &Producer {
        self.artifact.metadata().provenance().producer()
    }
    pub const fn schema(&self) -> &Schema {
        self.artifact.metadata().provenance().schema()
    }
    pub fn derived_from(&self) -> &[ArtifactRef] {
        self.artifact.metadata().provenance().derived_from()
    }
    pub const fn encoding(&self) -> &SelectedEncoding {
        &self.encoding
    }
    pub const fn basis(&self) -> DecodingBasis {
        self.basis
    }
    pub const fn replacements(&self) -> u64 {
        self.replacements
    }
    pub fn conflicts(&self) -> &[DecodingConflict] {
        &self.conflicts
    }
    pub const fn source_truncated(&self) -> bool {
        self.source_truncated
    }
    pub const fn incomplete_terminal_sequence(&self) -> bool {
        self.incomplete_terminal_sequence
    }
}
impl fmt::Debug for DecodedSourceView {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("DecodedSourceView")
            .field("size", &self.size())
            .field("digest", &self.digest())
            .field("source", &self.source)
            .field("artifact", &self.artifact)
            .field("encoding", &self.encoding)
            .field("basis", &self.basis)
            .field("replacements", &self.replacements)
            .field("conflicts", &self.conflicts)
            .field("source_truncated", &self.source_truncated)
            .field(
                "incomplete_terminal_sequence",
                &self.incomplete_terminal_sequence,
            )
            .finish_non_exhaustive()
    }
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CharacterDecodingOutcome {
    Complete(DecodedSourceView),
    OutputTruncated(DecodedSourceView),
    UnsupportedEncoding(DecodingErrorCode),
    Undecodable(DecodingErrorCode),
    NotApplicable(DecodingErrorCode),
}

type Choice = (
    &'static Encoding,
    DecodingBasis,
    usize,
    bool,
    Vec<DecodingConflict>,
);
type Selection = Result<Choice, CharacterDecodingOutcome>;
pub(super) fn decode(
    classification: &SourceClassificationOutcome,
    declaration: &MediaDeclaration,
    body: &RetainedSource,
    source_artifact: &crate::SourceArtifact,
    output: &DecodedOutputIdentity,
    limit: u64,
) -> CharacterDecodingOutcome {
    let SourceClassificationOutcome::Classified(classified) = classification else {
        return CharacterDecodingOutcome::NotApplicable(DecodingErrorCode::NotClassified);
    };
    let charset = match declaration {
        MediaDeclaration::Parsed { charset, .. } => Some(charset),
        _ => None,
    };
    let selected = match classified.format() {
        SourceFormat::Html => select_html(body.bytes(), charset),
        SourceFormat::Xml(_) => select_xml(body.bytes(), charset),
        SourceFormat::Json => select_json(body.bytes(), charset),
        SourceFormat::PlainText => select_plain(body.bytes(), charset),
    };
    let (encoding, basis, skip, strict, mut conflicts) = match selected {
        Ok(v) => v,
        Err(v) => return v,
    };
    add_conflicts(body.bytes(), charset, encoding, &mut conflicts);
    let input = body.bytes().get(skip..).unwrap_or_default();
    let decoded = super::decode_stream::bounded_decode(
        input,
        encoding,
        limit,
        strict,
        body.extent() == RetainedSourceExtent::Truncated,
    );
    let decoded = match decoded {
        Ok(v) => v,
        Err(code) => return CharacterDecodingOutcome::Undecodable(code),
    };
    let source_extent = if body.extent() == RetainedSourceExtent::Complete {
        DecodedExtent::Complete
    } else {
        DecodedExtent::Truncated
    };
    let unicode_extent = if decoded.output_truncated {
        DecodedExtent::Truncated
    } else {
        DecodedExtent::Complete
    };
    let Ok(interpretation) = DecodedSourceInterpretation::new(
        encoding.name(),
        basis,
        decoded.replacements,
        conflicts.clone(),
        source_extent,
        unicode_extent,
    ) else {
        return CharacterDecodingOutcome::Undecodable(DecodingErrorCode::ArtifactMetadata);
    };
    let Some(artifact) = artifact::decoded_artifact(
        source_artifact,
        output,
        decoded.text.as_bytes(),
        decoded.output_truncated,
        interpretation,
    ) else {
        return CharacterDecodingOutcome::Undecodable(DecodingErrorCode::ArtifactMetadata);
    };
    let view = DecodedSourceView {
        utf8: decoded.text,
        source: source_artifact.reference(),
        artifact,
        encoding: SelectedEncoding(encoding.name()),
        basis,
        replacements: decoded.replacements,
        conflicts,
        source_truncated: body.extent() == RetainedSourceExtent::Truncated,
        incomplete_terminal_sequence: decoded.incomplete,
    };
    if decoded.output_truncated {
        CharacterDecodingOutcome::OutputTruncated(view)
    } else {
        CharacterDecodingOutcome::Complete(view)
    }
}

fn bom(bytes: &[u8]) -> Option<Selection> {
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
fn label(
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
fn select_html(bytes: &[u8], charset: Option<&CharsetDeclaration>) -> Selection {
    if let Some(v) = bom(bytes) {
        return v;
    }
    if let Some(enc) = label(charset, false)? {
        return Ok((enc, DecodingBasis::HttpCharset, 0, false, Vec::new()));
    }
    if let Some(enc) = super::html_prescan::encoding(bytes) {
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
fn select_xml(bytes: &[u8], charset: Option<&CharsetDeclaration>) -> Selection {
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
    match super::xml_declaration::inspect(bytes) {
        super::xml_declaration::XmlDeclarationEvidence::Encoding(enc) => {
            Ok((enc, DecodingBasis::XmlDeclaration, 0, true, Vec::new()))
        }
        super::xml_declaration::XmlDeclarationEvidence::Unsupported => Err(
            CharacterDecodingOutcome::UnsupportedEncoding(DecodingErrorCode::UnsupportedCharset),
        ),
        super::xml_declaration::XmlDeclarationEvidence::Conflicting
        | super::xml_declaration::XmlDeclarationEvidence::Malformed => Err(
            CharacterDecodingOutcome::Undecodable(DecodingErrorCode::InvalidCharset),
        ),
        super::xml_declaration::XmlDeclarationEvidence::Absent => {
            Ok((UTF_8, DecodingBasis::XmlDefaultUtf8, 0, true, Vec::new()))
        }
    }
}
fn select_json(bytes: &[u8], charset: Option<&CharsetDeclaration>) -> Selection {
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
fn select_plain(bytes: &[u8], charset: Option<&CharsetDeclaration>) -> Selection {
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
fn signature_utf32(bytes: &[u8]) -> bool {
    bytes.starts_with(b"\0\0\xfe\xff")
        || bytes.starts_with(b"\xff\xfe\0\0")
        || bytes.starts_with(b"\0\0\0<")
        || bytes.starts_with(b"<\0\0\0")
}
fn in_band(bytes: &[u8]) -> Option<&'static Encoding> {
    match super::xml_declaration::inspect(bytes) {
        super::xml_declaration::XmlDeclarationEvidence::Encoding(v) => Some(v),
        _ => super::html_prescan::encoding(bytes),
    }
}
fn add_conflicts(
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
