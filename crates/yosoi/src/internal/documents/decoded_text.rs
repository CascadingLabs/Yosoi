use std::str;

use regex::Regex;
use thiserror::Error;

use crate::internal::documents::{
    Document, DocumentClass, LocateFailure, ResourceBudget, ResourceLimit,
};

#[path = "decoded_text_evaluation.rs"]
mod evaluation;
#[path = "decoded_text_limits.rs"]
mod limits;
#[path = "decoded_text_matching.rs"]
mod matching;

pub fn compile_regex(expression: &str) -> Result<regex::Regex, regex::Error> {
    matching::compile_regex(expression)
}

/// A regex lowered once with the locator plan and reused for every evaluation.
///
/// Capture group indexes follow the requested projection order. The public
/// plan remains the source of truth for names and serialized semantics.
#[derive(Clone, Debug)]
pub struct CompiledTextRegex {
    regex: Regex,
    requested_capture_groups: Vec<usize>,
}

impl CompiledTextRegex {
    pub(super) const fn new(regex: Regex, requested_capture_groups: Vec<usize>) -> Self {
        Self {
            regex,
            requested_capture_groups,
        }
    }

    pub(super) const fn regex(&self) -> &Regex {
        &self.regex
    }

    pub(super) fn requested_capture_groups(&self) -> &[usize] {
        &self.requested_capture_groups
    }

    pub(super) fn set_requested_capture_groups(&mut self, groups: Vec<usize>) {
        self.requested_capture_groups = groups;
    }
}

/// Why exact decoded-text parsing could not produce a UTF-8 view.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum DecodedTextParseError {
    #[error("decoded-text parsing requires a source-text document, got {document:?}")]
    UnsupportedDocument { document: DocumentClass },
    #[error("decoded-text input is {observed} bytes, above the {maximum}-byte limit")]
    InputLimitExceeded { maximum: u64, observed: u64 },
    #[error("source-text input is not UTF-8; the first invalid byte is at offset {byte_offset}")]
    InvalidUtf8 { byte_offset: u64 },
    #[error("UTF-8 error offset cannot be represented as u64")]
    OffsetOverflow,
}

pub fn parse_failure(error: &DecodedTextParseError) -> LocateFailure {
    match error {
        DecodedTextParseError::UnsupportedDocument { document } => {
            LocateFailure::UnsupportedCombination {
                document: *document,
            }
        }
        DecodedTextParseError::InputLimitExceeded { maximum, observed } => {
            LocateFailure::LimitExhausted {
                limit: ResourceLimit::InputBytes,
                maximum: *maximum,
                observed: *observed,
            }
        }
        DecodedTextParseError::InvalidUtf8 { .. } => LocateFailure::ParseFailed {
            code: "invalid_utf8".to_owned(),
        },
        DecodedTextParseError::OffsetOverflow => LocateFailure::ParseFailed {
            code: "utf8_offset_overflow".to_owned(),
        },
    }
}

/// Borrowed, strictly decoded UTF-8 view over one immutable source-text document.
///
/// The input bytes are not normalized, case-folded, or stripped of a BOM.
#[derive(Clone, Copy, Debug)]
pub struct DecodedTextDocument<'a> {
    document: &'a Document,
    text: &'a str,
}

impl<'a> DecodedTextDocument<'a> {
    /// Decodes the document as strict UTF-8 after enforcing the input byte limit.
    pub fn parse(
        document: &'a Document,
        limits: ResourceBudget,
    ) -> Result<Self, DecodedTextParseError> {
        if document.class() != DocumentClass::SourceText {
            return Err(DecodedTextParseError::UnsupportedDocument {
                document: document.class(),
            });
        }
        let observed = document.byte_len();
        let maximum = limits.max_input_bytes();
        if observed > maximum {
            return Err(DecodedTextParseError::InputLimitExceeded { maximum, observed });
        }
        let text = str::from_utf8(document.bytes()).map_err(|error| {
            u64::try_from(error.valid_up_to())
                .map_or(DecodedTextParseError::OffsetOverflow, |byte_offset| {
                    DecodedTextParseError::InvalidUtf8 { byte_offset }
                })
        })?;
        Ok(Self { document, text })
    }

    pub const fn text(&self) -> &'a str {
        self.text
    }
}

#[derive(Clone, Copy, Debug)]
struct TextMatch {
    output_index: usize,
    byte_start: usize,
    byte_end: usize,
    scalar_start: u64,
    scalar_end: u64,
}
