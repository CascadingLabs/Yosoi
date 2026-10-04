use crate::decoded_text::compile_regex;
use crate::json::{parse_json_path, parse_json_pointer};
use crate::query::{AccessibilityStateName, QueryAtom, QueryError, QueryResultShape, QuerySpec};

pub fn css(value: impl Into<String>) -> Result<QuerySpec, QueryError> {
    query(value, QueryAtom::Css, QueryResultShape::TreeNodes)
}

pub fn xpath(value: impl Into<String>) -> Result<QuerySpec, QueryError> {
    query(value, QueryAtom::XPath, QueryResultShape::TreeNodes)
}

pub fn tree_text_contains(value: impl Into<String>) -> Result<QuerySpec, QueryError> {
    query(
        value,
        QueryAtom::TreeTextContains,
        QueryResultShape::TreeNodes,
    )
}

pub fn json_pointer(value: impl Into<String>) -> Result<QuerySpec, QueryError> {
    let value = value.into();
    parse_json_pointer(&value)?;
    Ok(QuerySpec::new(
        QueryAtom::JsonPointer(value),
        QueryResultShape::JsonValues,
    ))
}

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

pub fn role(value: impl Into<String>) -> Result<QuerySpec, QueryError> {
    query(
        value,
        QueryAtom::AccessibilityRole,
        QueryResultShape::AccessibilityNodes,
    )
}

pub fn accessible_name(value: impl Into<String>) -> Result<QuerySpec, QueryError> {
    query(
        value,
        QueryAtom::AccessibleName,
        QueryResultShape::AccessibilityNodes,
    )
}

pub fn accessibility_text(value: impl Into<String>) -> Result<QuerySpec, QueryError> {
    query(
        value,
        QueryAtom::AccessibilityText,
        QueryResultShape::AccessibilityNodes,
    )
}

pub const fn accessibility_state(name: AccessibilityStateName, value: bool) -> QuerySpec {
    QuerySpec::new(
        QueryAtom::AccessibilityState { name, value },
        QueryResultShape::AccessibilityNodes,
    )
}

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
