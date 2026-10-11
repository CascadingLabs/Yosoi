use super::{JavaScriptModuleError, JavaScriptModuleImportKind};
use std::ops::Range;
use tree_sitter::{Node, Parser};

#[derive(Clone, Debug, Eq, PartialEq)]
pub(super) struct ParsedImport {
    pub specifier: String,
    pub source_range: Range<usize>,
    pub kind: JavaScriptModuleImportKind,
}

pub(super) fn parse_imports(
    source: &str,
    module_id: &str,
) -> Result<Vec<ParsedImport>, JavaScriptModuleError> {
    let mut parser = Parser::new();
    let language = tree_sitter_javascript::LANGUAGE.into();
    parser
        .set_language(&language)
        .map_err(|_| JavaScriptModuleError::ParserConfiguration)?;
    let tree = parser
        .parse(source, None)
        .ok_or_else(|| JavaScriptModuleError::ParseFailed {
            module_id: module_id.to_owned(),
        })?;
    if tree.root_node().has_error() {
        return Err(JavaScriptModuleError::InvalidSyntax {
            module_id: module_id.to_owned(),
        });
    }

    let mut imports = Vec::new();
    let mut pending = vec![tree.root_node()];
    while let Some(node) = pending.pop() {
        match node.kind() {
            "import_statement" => {
                if has_import_attributes(node, module_id)? {
                    return Err(JavaScriptModuleError::UnsupportedImportAttributes {
                        module_id: module_id.to_owned(),
                    });
                }
                let source_node = node.child_by_field_name("source").ok_or_else(|| {
                    JavaScriptModuleError::MalformedImport {
                        module_id: module_id.to_owned(),
                    }
                })?;
                imports.push(parse_string_import(
                    source,
                    module_id,
                    source_node,
                    JavaScriptModuleImportKind::Static,
                )?);
            }
            "export_statement" => {
                if has_import_attributes(node, module_id)? {
                    return Err(JavaScriptModuleError::UnsupportedImportAttributes {
                        module_id: module_id.to_owned(),
                    });
                }
                if let Some(source_node) = node.child_by_field_name("source") {
                    imports.push(parse_string_import(
                        source,
                        module_id,
                        source_node,
                        JavaScriptModuleImportKind::ReExport,
                    )?);
                }
            }
            "call_expression" if is_dynamic_import(node) => {
                let arguments = node.child_by_field_name("arguments").ok_or_else(|| {
                    JavaScriptModuleError::MalformedImport {
                        module_id: module_id.to_owned(),
                    }
                })?;
                let first = first_non_comment_child(arguments, module_id)?.ok_or_else(|| {
                    JavaScriptModuleError::ComputedDynamicImport {
                        module_id: module_id.to_owned(),
                    }
                })?;
                if first.kind() != "string" {
                    return Err(JavaScriptModuleError::ComputedDynamicImport {
                        module_id: module_id.to_owned(),
                    });
                }
                if non_comment_child_count(arguments, module_id)? > 1 {
                    return Err(JavaScriptModuleError::UnsupportedImportAttributes {
                        module_id: module_id.to_owned(),
                    });
                }
                imports.push(parse_string_import(
                    source,
                    module_id,
                    first,
                    JavaScriptModuleImportKind::Dynamic,
                )?);
            }
            _ => {}
        }

        for child in named_children(node, module_id)? {
            if child.kind() != "comment" {
                pending.push(child);
            }
        }
    }
    imports.sort_by_key(|item| item.source_range.start);
    Ok(imports)
}

fn is_dynamic_import(node: Node<'_>) -> bool {
    node.child_by_field_name("function")
        .is_some_and(|function| function.kind() == "import")
}

fn named_children<'a>(
    node: Node<'a>,
    module_id: &str,
) -> Result<Vec<Node<'a>>, JavaScriptModuleError> {
    let mut children = Vec::new();
    for index in 0..node.named_child_count() {
        let child_index =
            u32::try_from(index).map_err(|_| JavaScriptModuleError::MalformedImport {
                module_id: module_id.to_owned(),
            })?;
        if let Some(child) = node.named_child(child_index) {
            children.push(child);
        }
    }
    Ok(children)
}

fn first_non_comment_child<'a>(
    node: Node<'a>,
    module_id: &str,
) -> Result<Option<Node<'a>>, JavaScriptModuleError> {
    Ok(named_children(node, module_id)?
        .into_iter()
        .find(|child| child.kind() != "comment"))
}

fn non_comment_child_count(
    node: Node<'_>,
    module_id: &str,
) -> Result<usize, JavaScriptModuleError> {
    Ok(named_children(node, module_id)?
        .into_iter()
        .filter(|child| child.kind() != "comment")
        .count())
}

fn has_import_attributes(node: Node<'_>, module_id: &str) -> Result<bool, JavaScriptModuleError> {
    Ok(named_children(node, module_id)?
        .into_iter()
        .any(|child| child.kind() == "import_attribute"))
}

fn parse_string_import(
    source: &str,
    module_id: &str,
    node: Node<'_>,
    kind: JavaScriptModuleImportKind,
) -> Result<ParsedImport, JavaScriptModuleError> {
    let source_range = node.byte_range();
    let literal =
        source
            .get(source_range.clone())
            .ok_or_else(|| JavaScriptModuleError::MalformedImport {
                module_id: module_id.to_owned(),
            })?;
    let specifier = decode_string_literal(literal).ok_or_else(|| {
        JavaScriptModuleError::InvalidStringSpecifier {
            module_id: module_id.to_owned(),
        }
    })?;
    Ok(ParsedImport {
        specifier,
        source_range,
        kind,
    })
}

fn decode_string_literal(literal: &str) -> Option<String> {
    let quote = literal.as_bytes().first().copied()?;
    if !matches!(quote, b'\'' | b'"') || literal.as_bytes().last().copied()? != quote {
        return None;
    }
    let body = literal.get(1..literal.len().checked_sub(1)?)?;
    let bytes = body.as_bytes();
    let mut index = 0_usize;
    let mut decoded = String::new();

    while index < bytes.len() {
        let remaining = body.get(index..)?;
        let character = remaining.chars().next()?;
        if character != '\\' {
            decoded.push(character);
            index = index.checked_add(character.len_utf8())?;
            continue;
        }
        index = index.checked_add(1)?;
        let escaped = body.get(index..)?.chars().next()?;
        index = index.checked_add(escaped.len_utf8())?;
        match escaped {
            '\'' => decoded.push('\''),
            '"' => decoded.push('"'),
            '\\' => decoded.push('\\'),
            '/' => decoded.push('/'),
            'b' => decoded.push('\u{0008}'),
            'f' => decoded.push('\u{000c}'),
            'n' => decoded.push('\n'),
            'r' => decoded.push('\r'),
            't' => decoded.push('\t'),
            'v' => decoded.push('\u{000b}'),
            '0' => {
                if bytes.get(index).is_some_and(u8::is_ascii_digit) {
                    return None;
                }
                decoded.push('\0');
            }
            'x' => {
                let value = read_hex(bytes, &mut index, 2)?;
                decoded.push(char::from_u32(value)?);
            }
            'u' => {
                let first = read_unicode_escape(bytes, &mut index)?;
                let scalar = if (0xd800..=0xdbff).contains(&first) {
                    let start = index;
                    let has_escape = bytes.get(start) == Some(&b'\\')
                        && bytes.get(start.checked_add(1)?) == Some(&b'u');
                    if !has_escape {
                        return None;
                    }
                    index = start.checked_add(2)?;
                    let second = read_unicode_escape(bytes, &mut index)?;
                    if !(0xdc00..=0xdfff).contains(&second) {
                        return None;
                    }
                    let high = first.checked_sub(0xd800)?;
                    let low = second.checked_sub(0xdc00)?;
                    0x10000_u32
                        .checked_add(high.checked_mul(0x400)?)?
                        .checked_add(low)?
                } else if (0xdc00..=0xdfff).contains(&first) {
                    return None;
                } else {
                    first
                };
                decoded.push(char::from_u32(scalar)?);
            }
            '\n' | '\u{2028}' | '\u{2029}' => {}
            '\r' => {
                if bytes.get(index) == Some(&b'\n') {
                    index = index.checked_add(1)?;
                }
            }
            value if value.is_ascii_digit() => return None,
            value => decoded.push(value),
        }
    }
    Some(decoded)
}

fn read_unicode_escape(bytes: &[u8], index: &mut usize) -> Option<u32> {
    if bytes.get(*index) == Some(&b'{') {
        *index = index.checked_add(1)?;
        let mut value = 0_u32;
        let mut digits = 0_u32;
        loop {
            let byte = *bytes.get(*index)?;
            if byte == b'}' {
                *index = index.checked_add(1)?;
                return (digits > 0).then_some(value);
            }
            value = value
                .checked_mul(16)?
                .checked_add(u32::from(hex_digit(byte)?))?;
            digits = digits.checked_add(1)?;
            *index = index.checked_add(1)?;
        }
    }
    read_hex(bytes, index, 4)
}

fn read_hex(bytes: &[u8], index: &mut usize, count: usize) -> Option<u32> {
    let mut value = 0_u32;
    for _ in 0..count {
        value = value
            .checked_mul(16)?
            .checked_add(u32::from(hex_digit(*bytes.get(*index)?)?))?;
        *index = index.checked_add(1)?;
    }
    Some(value)
}

fn hex_digit(byte: u8) -> Option<u8> {
    match byte {
        b'0'..=b'9' => byte.checked_sub(b'0'),
        b'a'..=b'f' => byte.checked_sub(b'a')?.checked_add(10),
        b'A'..=b'F' => byte.checked_sub(b'A')?.checked_add(10),
        _ => None,
    }
}
