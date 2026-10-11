//! Bounded source-JSON parsing and the RFC 6901 / small JSONPath evaluator.
//!
//! JSONPath accepts `$`, ASCII identifier children (`.name`), double-quoted
//! object children (`["arbitrary key"]`), canonical non-negative array indexes
//! (`[0]`, `[1]`, ...), and array wildcards (`[*]`). Recursive descent, object
//! wildcards, filters, scripts, unions, slices, negative indexes, and functions
//! are rejected during query construction and plan compilation. Dot identifiers
//! use `[A-Za-z_][A-Za-z0-9_]*`; quote notation selects keys outside that set.
//!
//! Query cost is bounded by the shared input, query-byte, query-step, depth,
//! match, and output-byte budgets. JSON Pointer tokens and JSONPath selectors
//! each count as query steps. Source parsing additionally caps nesting at 128
//! levels to stay within serde_json's recursive parser bound. Duplicate object
//! member names are rejected so Pointer and named-child results stay unambiguous.
//! The JSON output-byte budget counts compact projected JSON values plus their
//! canonical Pointer coordinates; it excludes the outer outcome envelope.

use crate::internal::documents as yosoi_documents;

mod evaluation;
mod parser;
mod query;
mod source;
mod types;

pub use query::{json_query_step_count, parse_json_path, parse_json_pointer};
pub use source::parse_json_document;
pub use types::{JsonParseError, JsonQuerySyntaxError, ParsedJsonDocument};

pub fn parse_failure(error: &JsonParseError) -> yosoi_documents::LocateFailure {
    types::parse_failure(error)
}
