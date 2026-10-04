use serde_json::Value;
use thiserror::Error;

use crate::{DocumentClass, DocumentId};

/// Syntax errors in the deliberately small JSON query language.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum JsonQuerySyntaxError {
    #[error("JSON Pointer must be empty or begin with a slash")]
    InvalidPointerSyntax,
    #[error("JSON Pointer contains an invalid tilde escape")]
    InvalidPointerEscape,
    #[error("JSONPath expression is malformed")]
    InvalidPathSyntax,
    #[error("JSONPath expression uses syntax outside the supported subset")]
    UnsupportedPathFeature,
}

/// A bounded source-JSON parsing failure.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum JsonParseError {
    #[error("{document:?} is not a source JSON document")]
    UnsupportedDocument { document: DocumentClass },
    #[error("JSON input is {observed} bytes, above the {maximum}-byte limit")]
    InputLimitExceeded { maximum: u64, observed: u64 },
    #[error("JSON nesting depth is {observed}, above the {maximum}-level limit")]
    DepthLimitExceeded { maximum: u64, observed: u64 },
    #[error("JSON object contains a duplicate member name")]
    DuplicateObjectKey,
    #[error("JSON document ended before a complete value was read")]
    TruncatedJson,
    #[error("JSON document is malformed")]
    MalformedJson,
}

/// A parsed source-JSON document, ready for repeated synchronous locator plans.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ParsedJsonDocument {
    pub(super) document_id: DocumentId,
    pub(super) root: Value,
    pub(super) input_bytes: u64,
    pub(super) maximum_depth: u32,
}

impl ParsedJsonDocument {
    /// The native parsed JSON value.
    pub const fn value(&self) -> &Value {
        &self.root
    }

    /// The identity of the immutable source document that was parsed.
    pub const fn document_id(&self) -> &DocumentId {
        &self.document_id
    }
}

pub(super) fn parse_failure(error: &JsonParseError) -> crate::LocateFailure {
    use crate::{LocateFailure, ResourceLimit};

    match error {
        JsonParseError::UnsupportedDocument { document } => LocateFailure::UnsupportedCombination {
            document: *document,
        },
        JsonParseError::InputLimitExceeded { maximum, observed } => LocateFailure::LimitExhausted {
            limit: ResourceLimit::InputBytes,
            maximum: *maximum,
            observed: *observed,
        },
        JsonParseError::DepthLimitExceeded { maximum, observed } => LocateFailure::LimitExhausted {
            limit: ResourceLimit::Depth,
            maximum: *maximum,
            observed: *observed,
        },
        JsonParseError::DuplicateObjectKey => LocateFailure::ParseFailed {
            code: "duplicate_json_object_key".to_owned(),
        },
        JsonParseError::TruncatedJson => LocateFailure::ParseFailed {
            code: "truncated_json".to_owned(),
        },
        JsonParseError::MalformedJson => LocateFailure::ParseFailed {
            code: "malformed_json".to_owned(),
        },
    }
}
