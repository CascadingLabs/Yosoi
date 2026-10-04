use super::names::{CLASS, ID, NameKey};
use super::plan::{CompiledCompound, CompiledSelectorPlan, CompiledTest, StreamingProjection};
use super::routing::RelevantAttributes;
use super::scanner::StreamValue;
use super::support::{memchr, memmem};

pub(super) struct ParsedStartTag<'source> {
    pub(super) attributes: RelevantAttributes<'source>,
    pub(super) next: usize,
    pub(super) self_closing: bool,
}

pub(super) fn parse_start_tag<'source>(
    source: &'source str,
    mut cursor: usize,
    plan: &CompiledSelectorPlan,
    collect_values: bool,
) -> Option<ParsedStartTag<'source>> {
    let bytes = source.as_bytes();
    let mut result = RelevantAttributes::empty();
    loop {
        while bytes.get(cursor).is_some_and(u8::is_ascii_whitespace) {
            cursor = cursor.checked_add(1)?;
        }
        match bytes.get(cursor).copied()? {
            b'>' => {
                return Some(ParsedStartTag {
                    attributes: result,
                    next: cursor.checked_add(1)?,
                    self_closing: false,
                });
            }
            b'/' => {
                cursor = cursor.checked_add(1)?;
                while bytes.get(cursor).is_some_and(u8::is_ascii_whitespace) {
                    cursor = cursor.checked_add(1)?;
                }
                if bytes.get(cursor) != Some(&b'>') {
                    return None;
                }
                return Some(ParsedStartTag {
                    attributes: result,
                    next: cursor.checked_add(1)?,
                    self_closing: true,
                });
            }
            _ => {}
        }
        let name_start = cursor;
        while bytes
            .get(cursor)
            .is_some_and(|byte| !byte.is_ascii_whitespace() && !matches!(*byte, b'=' | b'/' | b'>'))
        {
            cursor = cursor.checked_add(1)?;
        }
        if cursor == name_start {
            return None;
        }
        let name_key = NameKey::from_ascii_casefold(bytes.get(name_start..cursor)?)?;
        let relevant = collect_values
            && plan
                .attribute_names
                .get(..plan.attribute_name_count)?
                .iter()
                .flatten()
                .any(|candidate| *candidate == name_key);
        result.source_count = result.source_count.checked_add(1)?;
        while bytes.get(cursor).is_some_and(u8::is_ascii_whitespace) {
            cursor = cursor.checked_add(1)?;
        }
        let value_range = if bytes.get(cursor) == Some(&b'=') {
            cursor = cursor.checked_add(1)?;
            while bytes.get(cursor).is_some_and(u8::is_ascii_whitespace) {
                cursor = cursor.checked_add(1)?;
            }
            match bytes.get(cursor).copied() {
                Some(quote @ (b'\'' | b'"')) => {
                    cursor = cursor.checked_add(1)?;
                    let start = cursor;
                    while bytes.get(cursor).copied() != Some(quote) {
                        cursor = cursor.checked_add(1)?;
                        bytes.get(cursor)?;
                    }
                    let end = cursor;
                    cursor = cursor.checked_add(1)?;
                    Some(start..end)
                }
                Some(_) => {
                    let start = cursor;
                    while bytes
                        .get(cursor)
                        .is_some_and(|byte| !byte.is_ascii_whitespace() && *byte != b'>')
                    {
                        cursor = cursor.checked_add(1)?;
                    }
                    Some(start..cursor)
                }
                None => return None,
            }
        } else {
            None
        };
        if relevant {
            let value = match value_range {
                Some(range) => source.get(range)?,
                None => "",
            };
            if !result
                .values
                .iter()
                .flatten()
                .any(|(candidate, _)| *candidate == name_key)
            {
                let slot = result.values.get_mut(result.len)?;
                *slot = Some((name_key, value));
                result.len = result.len.checked_add(1)?;
            }
        }
    }
}

pub(super) fn parse_closing_tag(bytes: &[u8], mut cursor: usize) -> Option<usize> {
    while bytes.get(cursor).is_some_and(u8::is_ascii_whitespace) {
        cursor = cursor.checked_add(1)?;
    }
    if bytes.get(cursor) == Some(&b'>') {
        cursor.checked_add(1)
    } else {
        None
    }
}

pub(super) fn compound_tests_match(
    attributes: &RelevantAttributes<'_>,
    selector: &CompiledCompound,
) -> bool {
    selector.tests.iter().all(|test| match test {
        CompiledTest::Id(expected) => attribute(attributes, ID) == Some(expected.as_str()),
        CompiledTest::Class(expected) => attribute(attributes, CLASS).is_some_and(|value| {
            value
                .split_ascii_whitespace()
                .any(|class| class == expected)
        }),
        CompiledTest::AttributePresent(name) => attribute(attributes, *name).is_some(),
        CompiledTest::AttributeEquals(name, expected) => {
            attribute(attributes, *name) == Some(expected.as_str())
        }
    })
}

pub(super) fn attribute<'a>(attributes: &RelevantAttributes<'a>, name: NameKey) -> Option<&'a str> {
    attributes
        .values
        .get(..attributes.len)?
        .iter()
        .flatten()
        .find_map(|(candidate, value)| (*candidate == name).then_some(*value))
}

pub(super) fn capture_value(
    attributes: &RelevantAttributes<'_>,
    projection: &StreamingProjection,
) -> Option<StreamValue> {
    match projection {
        StreamingProjection::Text => Some(StreamValue::Text {
            value: String::new(),
            previous_was_space: false,
        }),
        StreamingProjection::Attribute { key, name } => Some(StreamValue::Attribute {
            name: name.clone(),
            value: attribute(attributes, *key)?.to_owned(),
        }),
        StreamingProjection::Node => Some(StreamValue::Node),
    }
}

pub(super) fn find_tag_end(bytes: &[u8], mut cursor: usize) -> Option<usize> {
    let mut quote = None;
    while let Some(byte) = bytes.get(cursor).copied() {
        match (quote, byte) {
            (Some(active), candidate) if active == candidate => quote = None,
            (None, b'\'' | b'"') => quote = Some(byte),
            (None, b'>') => return Some(cursor),
            _ => {}
        }
        cursor = cursor.checked_add(1)?;
    }
    None
}

pub(super) fn simple_raw_text_island(bytes: &[u8], name_end: usize, close: &[u8]) -> bool {
    let Some(open_end) = find_tag_end(bytes, name_end) else {
        return false;
    };
    let Some(content_start) = open_end.checked_add(1) else {
        return false;
    };
    let Some(remaining) = bytes.get(content_start..) else {
        return false;
    };
    let Some(close_start) = memmem::find(remaining, close) else {
        return false;
    };
    remaining
        .get(..close_start)
        .is_some_and(|content| memchr(b'<', content).is_none())
}
