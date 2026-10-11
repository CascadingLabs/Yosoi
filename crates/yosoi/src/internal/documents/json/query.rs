use std::str;

use serde_json::Value;

use crate::internal::documents::{LocateFailure, QueryAtom, ResourceLimit};

use super::{evaluation::limit_failure, types::JsonQuerySyntaxError};

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum JsonPathSelector {
    Child(String),
    Index(usize),
    ArrayWildcard,
}

pub(super) struct JsonVisitBudget {
    maximum: u64,
    visited: u64,
}

impl JsonVisitBudget {
    pub(super) const fn new(maximum: u64) -> Self {
        Self {
            maximum,
            visited: 0,
        }
    }

    pub(super) fn charge(&mut self) -> Result<(), LocateFailure> {
        let observed = self
            .visited
            .checked_add(1)
            .ok_or_else(|| limit_failure(ResourceLimit::SelectorVisits, self.maximum, u64::MAX))?;
        if observed > self.maximum {
            return Err(limit_failure(
                ResourceLimit::SelectorVisits,
                self.maximum,
                observed,
            ));
        }
        self.visited = observed;
        Ok(())
    }
}

pub fn parse_json_pointer(expression: &str) -> Result<Vec<String>, JsonQuerySyntaxError> {
    if expression.is_empty() {
        return Ok(Vec::new());
    }
    if !expression.starts_with('/') {
        return Err(JsonQuerySyntaxError::InvalidPointerSyntax);
    }

    expression
        .split('/')
        .skip(1)
        .map(decode_pointer_token)
        .collect()
}

fn decode_pointer_token(token: &str) -> Result<String, JsonQuerySyntaxError> {
    let mut decoded = String::with_capacity(token.len());
    let mut characters = token.chars();
    while let Some(character) = characters.next() {
        if character != '~' {
            decoded.push(character);
            continue;
        }
        match characters.next() {
            Some('0') => decoded.push('~'),
            Some('1') => decoded.push('/'),
            _ => return Err(JsonQuerySyntaxError::InvalidPointerEscape),
        }
    }
    Ok(decoded)
}

pub fn parse_json_path(expression: &str) -> Result<Vec<JsonPathSelector>, JsonQuerySyntaxError> {
    let bytes = expression.as_bytes();
    if bytes.first() != Some(&b'$') {
        return Err(JsonQuerySyntaxError::InvalidPathSyntax);
    }

    let mut selectors = Vec::new();
    let mut position = 1_usize;
    while position < bytes.len() {
        match bytes.get(position).copied() {
            Some(b'.') => {
                advance(&mut position, 1)?;
                if bytes.get(position) == Some(&b'.') {
                    return Err(JsonQuerySyntaxError::UnsupportedPathFeature);
                }
                if bytes.get(position) == Some(&b'*') {
                    return Err(JsonQuerySyntaxError::UnsupportedPathFeature);
                }
                let name = parse_dot_name(bytes, &mut position)?;
                selectors.push(JsonPathSelector::Child(name));
            }
            Some(b'[') => {
                advance(&mut position, 1)?;
                let selector = parse_bracket_selector(bytes, &mut position)?;
                selectors.push(selector);
            }
            Some(byte) if unsupported_jsonpath_marker(byte) => {
                return Err(JsonQuerySyntaxError::UnsupportedPathFeature);
            }
            Some(_) | None => return Err(JsonQuerySyntaxError::InvalidPathSyntax),
        }
    }
    Ok(selectors)
}

pub fn json_query_step_count(atom: &QueryAtom) -> Result<u64, JsonQuerySyntaxError> {
    let count = match atom {
        QueryAtom::JsonPointer(expression) => parse_json_pointer(expression)?.len(),
        QueryAtom::JsonPath(expression) => parse_json_path(expression)?.len(),
        _ => 0,
    };
    u64::try_from(count).map_err(|_| JsonQuerySyntaxError::InvalidPathSyntax)
}

fn parse_dot_name(bytes: &[u8], position: &mut usize) -> Result<String, JsonQuerySyntaxError> {
    let start = *position;
    let first = bytes
        .get(*position)
        .copied()
        .ok_or(JsonQuerySyntaxError::InvalidPathSyntax)?;
    if !is_identifier_start(first) {
        return Err(JsonQuerySyntaxError::InvalidPathSyntax);
    }
    advance(position, 1)?;
    while bytes
        .get(*position)
        .copied()
        .is_some_and(is_identifier_continue)
    {
        advance(position, 1)?;
    }

    let name = bytes
        .get(start..*position)
        .ok_or(JsonQuerySyntaxError::InvalidPathSyntax)?;
    String::from_utf8(name.to_vec()).map_err(|_| JsonQuerySyntaxError::InvalidPathSyntax)
}

fn parse_bracket_selector(
    bytes: &[u8],
    position: &mut usize,
) -> Result<JsonPathSelector, JsonQuerySyntaxError> {
    match bytes.get(*position).copied() {
        Some(b'*') => {
            advance(position, 1)?;
            require_closing_bracket(bytes, position)?;
            Ok(JsonPathSelector::ArrayWildcard)
        }
        Some(b'"') => {
            let name = parse_quoted_name(bytes, position)?;
            require_closing_bracket(bytes, position)?;
            Ok(JsonPathSelector::Child(name))
        }
        Some(byte) if byte.is_ascii_digit() => {
            let index = parse_array_index(bytes, position)?;
            require_closing_bracket(bytes, position)?;
            Ok(JsonPathSelector::Index(index))
        }
        Some(byte) if unsupported_jsonpath_marker(byte) => {
            Err(JsonQuerySyntaxError::UnsupportedPathFeature)
        }
        Some(_) | None => Err(JsonQuerySyntaxError::InvalidPathSyntax),
    }
}

fn parse_quoted_name(bytes: &[u8], position: &mut usize) -> Result<String, JsonQuerySyntaxError> {
    let start = *position;
    advance(position, 1)?;
    let mut escaped = false;
    let mut closed = false;
    while let Some(byte) = bytes.get(*position).copied() {
        if escaped {
            escaped = false;
            advance(position, 1)?;
            continue;
        }
        match byte {
            b'\\' => {
                escaped = true;
                advance(position, 1)?;
            }
            b'"' => {
                advance(position, 1)?;
                closed = true;
                break;
            }
            _ => advance(position, 1)?,
        }
    }
    if !closed {
        return Err(JsonQuerySyntaxError::InvalidPathSyntax);
    }
    let encoded = bytes
        .get(start..*position)
        .ok_or(JsonQuerySyntaxError::InvalidPathSyntax)?;
    let name = serde_json::from_slice::<String>(encoded)
        .map_err(|_| JsonQuerySyntaxError::InvalidPathSyntax)?;
    Ok(name)
}

fn parse_array_index(bytes: &[u8], position: &mut usize) -> Result<usize, JsonQuerySyntaxError> {
    let start = *position;
    while bytes
        .get(*position)
        .copied()
        .is_some_and(|byte| byte.is_ascii_digit())
    {
        advance(position, 1)?;
    }
    let encoded = bytes
        .get(start..*position)
        .ok_or(JsonQuerySyntaxError::InvalidPathSyntax)?;
    if encoded.len() > 1 && encoded.first() == Some(&b'0') {
        return Err(JsonQuerySyntaxError::InvalidPathSyntax);
    }
    let text = str::from_utf8(encoded).map_err(|_| JsonQuerySyntaxError::InvalidPathSyntax)?;
    text.parse::<usize>()
        .map_err(|_| JsonQuerySyntaxError::InvalidPathSyntax)
}

fn require_closing_bracket(bytes: &[u8], position: &mut usize) -> Result<(), JsonQuerySyntaxError> {
    match bytes.get(*position).copied() {
        Some(b']') => advance(position, 1),
        Some(byte) if unsupported_jsonpath_marker(byte) => {
            Err(JsonQuerySyntaxError::UnsupportedPathFeature)
        }
        Some(_) | None => Err(JsonQuerySyntaxError::InvalidPathSyntax),
    }
}

fn advance(position: &mut usize, amount: usize) -> Result<(), JsonQuerySyntaxError> {
    *position = position
        .checked_add(amount)
        .ok_or(JsonQuerySyntaxError::InvalidPathSyntax)?;
    Ok(())
}

const fn is_identifier_start(byte: u8) -> bool {
    byte.is_ascii_alphabetic() || byte == b'_'
}

const fn is_identifier_continue(byte: u8) -> bool {
    byte.is_ascii_alphanumeric() || byte == b'_'
}

const fn unsupported_jsonpath_marker(byte: u8) -> bool {
    matches!(
        byte,
        b'?' | b'@' | b',' | b':' | b'(' | b')' | b'!' | b'-' | b'*'
    )
}

pub(super) fn resolve_pointer<'a>(
    root: &'a Value,
    tokens: &[String],
    visit_budget: &mut JsonVisitBudget,
) -> Result<Option<&'a Value>, LocateFailure> {
    let mut current = root;
    visit_budget.charge()?;
    for token in tokens {
        let next = match current {
            Value::Object(object) => object.get(token),
            Value::Array(array) => pointer_array_index(token).and_then(|index| array.get(index)),
            _ => None,
        };
        let Some(next) = next else {
            return Ok(None);
        };
        current = next;
        visit_budget.charge()?;
    }
    Ok(Some(current))
}

fn pointer_array_index(token: &str) -> Option<usize> {
    let bytes = token.as_bytes();
    if bytes.is_empty() || (bytes.len() > 1 && bytes.first() == Some(&b'0')) {
        return None;
    }
    if !bytes.iter().copied().all(|byte| byte.is_ascii_digit()) {
        return None;
    }
    token.parse::<usize>().ok()
}

pub(super) fn canonical_pointer(tokens: &[String]) -> String {
    let mut pointer = String::new();
    for token in tokens {
        append_pointer_token(&mut pointer, token);
    }
    pointer
}

fn append_pointer_token(pointer: &mut String, token: &str) {
    pointer.push('/');
    for character in token.chars() {
        match character {
            '~' => pointer.push_str("~0"),
            '/' => pointer.push_str("~1"),
            _ => pointer.push(character),
        }
    }
}
