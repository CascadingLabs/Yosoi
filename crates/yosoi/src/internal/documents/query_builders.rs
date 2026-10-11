use crate::internal::documents::decoded_text::compile_regex;
use crate::internal::documents::json::{parse_json_path, parse_json_pointer};
use crate::internal::documents::query::{
    AccessibilityStateName, QueryAtom, QueryError, QueryResultShape, QuerySpec,
};

/// Owns a nonblank CSS expression with tree-node result shape, without locating a document.
/// Returns [`QueryError`] for blank input; syntax, projection, namespace, and
/// document-capability checks remain part of supported compilation/execution paths.
pub fn css(value: impl Into<String>) -> Result<QuerySpec, QueryError> {
    query(value, QueryAtom::Css, QueryResultShape::TreeNodes)
}

/// Owns a nonblank supported XPath expression with tree-node result shape.
/// Returns [`QueryError`] for blank input. XML namespace and supported evaluator
/// semantics are validated separately; this constructor does not acquire evidence.
pub fn xpath(value: impl Into<String>) -> Result<QuerySpec, QueryError> {
    query(value, QueryAtom::XPath, QueryResultShape::TreeNodes)
}

/// Declares nonblank literal substring selection over tree descendant text.
/// Returns [`QueryError`] for blank input. Results are tree nodes, distinct
/// from accessible-name selection or decoded-text ranges; no document is searched here.
pub fn tree_text_contains(value: impl Into<String>) -> Result<QuerySpec, QueryError> {
    query(
        value,
        QueryAtom::TreeTextContains,
        QueryResultShape::TreeNodes,
    )
}

/// Validates JSON Pointer syntax and declares native JSON-value selection.
/// The empty pointer denotes the root. Returns [`QueryError`] for invalid
/// pointer syntax or escapes, without proving resolution in any document.
pub fn json_pointer(value: impl Into<String>) -> Result<QuerySpec, QueryError> {
    let value = value.into();
    parse_json_pointer(&value)?;
    Ok(QuerySpec::new(
        QueryAtom::JsonPointer(value),
        QueryResultShape::JsonValues,
    ))
}

/// Validates the supported JSONPath subset and declares JSON-value selection.
/// Returns [`QueryError`] for blank expressions, invalid syntax, or unsupported
/// path features. Construction performs no document acquisition or matching.
pub fn json_path(value: impl Into<String>) -> Result<QuerySpec, QueryError> {
    let value = value.into();
    if value.trim().is_empty() {
        return Err(QueryError::EmptyExpression);
    }
    parse_json_path(&value)?;
    Ok(QuerySpec::new(
        QueryAtom::JsonPath(value),
        QueryResultShape::JsonValues,
    ))
}

/// Owns a nonblank accessibility-role query for immutable snapshot nodes.
/// Returns [`QueryError`] for blank input; it does not inspect or mutate a live browser.
pub fn role(value: impl Into<String>) -> Result<QuerySpec, QueryError> {
    query(
        value,
        QueryAtom::AccessibilityRole,
        QueryResultShape::AccessibilityNodes,
    )
}

/// Owns a nonblank accessible-name query, distinct from descendant or decoded text.
/// Returns [`QueryError`] for blank input; matching requires supported accessibility evidence.
pub fn accessible_name(value: impl Into<String>) -> Result<QuerySpec, QueryError> {
    query(
        value,
        QueryAtom::AccessibleName,
        QueryResultShape::AccessibilityNodes,
    )
}

/// Owns a nonblank text query over supported immutable accessibility-node evidence.
/// Returns [`QueryError`] for blank input and performs no live browser observation.
pub fn accessibility_text(value: impl Into<String>) -> Result<QuerySpec, QueryError> {
    query(
        value,
        QueryAtom::AccessibilityText,
        QueryResultShape::AccessibilityNodes,
    )
}

/// Declares a supported expanded/focused boolean state query without mutating a browser.
/// Matching requires immutable accessibility evidence; result shape is accessibility nodes.
pub const fn accessibility_state(name: AccessibilityStateName, value: bool) -> QuerySpec {
    QuerySpec::new(
        QueryAtom::AccessibilityState { name, value },
        QueryResultShape::AccessibilityNodes,
    )
}

/// Owns a nonempty exact literal query yielding decoded-text ranges.
/// Whitespace is meaningful literal content. Returns [`QueryError`] for empty
/// input without parsing or searching any document.
pub fn text_literal(value: impl Into<String>) -> Result<QuerySpec, QueryError> {
    let value = value.into();
    if value.is_empty() {
        return Err(QueryError::EmptyExpression);
    }
    Ok(QuerySpec::new(
        QueryAtom::TextLiteral(value),
        QueryResultShape::TextRanges,
    ))
}

/// Checks supported regex syntax and declares decoded-text range selection.
/// Returns [`QueryError::InvalidRegexSyntax`] for rejected patterns; later
/// projection and execution budgets still apply. This does not search a payload.
pub fn regex(value: impl Into<String>) -> Result<QuerySpec, QueryError> {
    let value = value.into();
    compile_regex(&value).map_err(|_| QueryError::InvalidRegexSyntax)?;
    Ok(QuerySpec::new(
        QueryAtom::TextRegex(value),
        QueryResultShape::TextRanges,
    ))
}

fn query(
    value: impl Into<String>,
    constructor: impl FnOnce(String) -> QueryAtom,
    result_shape: QueryResultShape,
) -> Result<QuerySpec, QueryError> {
    let value = value.into();
    if value.trim().is_empty() {
        return Err(QueryError::EmptyExpression);
    }
    Ok(QuerySpec::new(constructor(value), result_shape))
}
