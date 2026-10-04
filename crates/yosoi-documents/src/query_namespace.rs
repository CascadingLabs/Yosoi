use std::collections::BTreeSet;

use crate::query::QueryError;

pub(super) fn valid_namespace_prefix(prefix: &str) -> bool {
    let mut characters = prefix.chars();
    characters.next().is_some_and(is_name_start)
        && characters.all(|character| {
            is_name_start(character) || character.is_ascii_digit() || matches!(character, '-' | '.')
        })
}

fn is_name_start(character: char) -> bool {
    character == '_' || character.is_alphabetic()
}

fn is_name_character(character: char) -> bool {
    is_name_start(character) || character.is_ascii_digit() || matches!(character, '-' | '.')
}

pub(super) fn validate_css_prefixes(
    expression: &str,
    bindings: &BTreeSet<&str>,
) -> Result<(), QueryError> {
    let mut prefix = String::new();
    let mut quoted = None;
    let mut escaped = false;
    let mut characters = expression.chars().peekable();
    while let Some(character) = characters.next() {
        if let Some(quote) = quoted {
            if escaped {
                escaped = false;
            } else if character == '\\' {
                escaped = true;
            } else if character == quote {
                quoted = None;
            }
            continue;
        }
        if matches!(character, '\'' | '"') {
            quoted = Some(character);
            prefix.clear();
            continue;
        }
        if character == '|' {
            if characters.peek() == Some(&'=') {
                prefix.clear();
                continue;
            }
            if prefix != "*"
                && prefix != "xml"
                && !prefix.is_empty()
                && !bindings.contains(prefix.as_str())
            {
                return Err(QueryError::UnboundNamespacePrefix);
            }
            prefix.clear();
            continue;
        }
        if is_name_character(character) || character == '*' {
            prefix.push(character);
        } else {
            prefix.clear();
        }
    }
    Ok(())
}

pub(super) fn css_uses_namespace_syntax(expression: &str) -> bool {
    let mut quoted = None;
    let mut escaped = false;
    let mut characters = expression.chars().peekable();
    while let Some(character) = characters.next() {
        if let Some(quote) = quoted {
            if escaped {
                escaped = false;
            } else if character == '\\' {
                escaped = true;
            } else if character == quote {
                quoted = None;
            }
            continue;
        }
        if matches!(character, '\'' | '"') {
            quoted = Some(character);
        } else if character == '|' && characters.peek() != Some(&'=') {
            return true;
        }
    }
    false
}

pub(super) fn xpath_uses_namespace_syntax(expression: &str) -> bool {
    let mut quoted = None;
    let mut characters = expression.chars().peekable();
    while let Some(character) = characters.next() {
        if let Some(quote) = quoted {
            if character == quote {
                quoted = None;
            }
            continue;
        }
        if matches!(character, '\'' | '"') {
            quoted = Some(character);
            continue;
        }
        if !is_name_start(character) {
            continue;
        }
        while characters
            .peek()
            .is_some_and(|next| is_name_character(*next))
        {
            characters.next();
        }
        if characters.peek() != Some(&':') {
            continue;
        }
        characters.next();
        if characters.peek() == Some(&':') {
            continue;
        }
        if characters
            .peek()
            .is_some_and(|next| is_name_start(*next) || *next == '*')
        {
            return true;
        }
    }
    false
}

pub(super) fn validate_xpath_prefixes(
    expression: &str,
    bindings: &BTreeSet<&str>,
) -> Result<(), QueryError> {
    let mut characters = expression.chars().peekable();
    let mut quoted = None;
    while let Some(character) = characters.next() {
        if let Some(quote) = quoted {
            if character == quote {
                quoted = None;
            }
            continue;
        }
        if matches!(character, '\'' | '"') {
            quoted = Some(character);
            continue;
        }
        if !is_name_start(character) {
            continue;
        }
        let mut prefix = String::from(character);
        while characters
            .peek()
            .is_some_and(|next| is_name_character(*next))
        {
            if let Some(next) = characters.next() {
                prefix.push(next);
            }
        }
        if characters.peek() != Some(&':') {
            continue;
        }
        characters.next();
        if characters.peek() == Some(&':') {
            continue;
        }
        if characters
            .peek()
            .is_some_and(|next| is_name_start(*next) || *next == '*')
            && prefix != "xml"
            && !bindings.contains(prefix.as_str())
        {
            return Err(QueryError::UnboundNamespacePrefix);
        }
    }
    Ok(())
}
