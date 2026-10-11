use std::cmp::Ordering;
use std::collections::HashSet;

use roxmltree::{Node, NodeId};

use crate::internal::documents::NamespaceBinding;

use super::{QueryWorkBudget, XmlError, enforce_match_limit, order_unique_nodes};

pub(super) fn descendant_text(
    node: Node<'_, '_>,
    work_budget: &mut QueryWorkBudget,
) -> Result<String, XmlError> {
    let mut normalized = String::new();
    let mut pending_space = false;
    for descendant in node.descendants().filter(Node::is_text) {
        work_budget.visit()?;
        if let Some(value) = descendant.text() {
            for character in value.chars() {
                if character.is_whitespace() {
                    pending_space = !normalized.is_empty();
                } else {
                    if pending_space {
                        normalized.push(' ');
                        pending_space = false;
                    }
                    normalized.push(character);
                }
            }
        }
    }
    Ok(normalized)
}

pub(super) fn select_tree_text<'tree, 'input>(
    context: Node<'tree, 'input>,
    needle: &str,
    maximum: u64,
    work_budget: &mut QueryWorkBudget,
) -> Result<Vec<Node<'tree, 'input>>, XmlError> {
    let (text, segments) = normalized_descendant_text(context, work_budget)?;
    let mut elements = Vec::new();
    for node in context.descendants().filter(Node::is_element) {
        work_budget.visit()?;
        if node == context {
            continue;
        }
        let range = node.range();
        let first = segments.partition_point(|segment| segment.source_end <= range.start);
        let after = segments.partition_point(|segment| segment.source_start < range.end);
        let Some(contained) = segments.get(first..after) else {
            return Err(XmlError::InvalidResult);
        };
        let first_text = contained
            .iter()
            .find_map(|segment| segment.normalized_range);
        let last_text = contained
            .iter()
            .rev()
            .find_map(|segment| segment.normalized_range);
        if let (Some(first_text), Some(last_text)) = (first_text, last_text)
            && first_text.start < last_text.end
        {
            elements.push(TextElementRange {
                node,
                source_start: range.start,
                flat_start: first_text.start,
                flat_end: last_text.end,
            });
        }
    }
    elements.sort_by(compare_text_ranges);

    let mut selected = Vec::new();
    let mut selected_ids = HashSet::<NodeId>::new();
    let mut active = Vec::<usize>::new();
    let mut next_element = 0_usize;
    let mut search_from = 0_usize;
    while let Some(suffix) = text.get(search_from..) {
        work_budget.visit()?;
        let Some(relative_start) = suffix.find(needle) else {
            break;
        };
        let match_start = search_from
            .checked_add(relative_start)
            .ok_or(XmlError::InvalidResult)?;
        let match_end = match_start
            .checked_add(needle.len())
            .ok_or(XmlError::InvalidResult)?;
        while let Some(element) = elements.get(next_element) {
            if element.flat_start > match_start {
                break;
            }
            while active
                .last()
                .and_then(|index| elements.get(*index))
                .is_some_and(|previous| previous.flat_end < element.flat_end)
            {
                active.pop();
            }
            active.push(next_element);
            next_element = next_element.saturating_add(1);
        }
        while active
            .last()
            .and_then(|index| elements.get(*index))
            .is_some_and(|element| element.flat_end < match_end)
        {
            active.pop();
        }
        if let Some(element_index) = active.last().copied()
            && let Some(element) = elements.get(element_index)
            && selected_ids.insert(element.node.id())
        {
            selected.push(element.node);
            enforce_match_limit(selected.len(), maximum)?;
        }
        let next_character_width = text
            .get(match_start..)
            .and_then(|remaining| remaining.chars().next())
            .map(char::len_utf8)
            .ok_or(XmlError::InvalidResult)?;
        search_from = match_start
            .checked_add(next_character_width)
            .ok_or(XmlError::InvalidResult)?;
    }
    Ok(order_unique_nodes(selected))
}

#[derive(Clone, Copy, Debug)]
struct TextSourceSegment {
    source_start: usize,
    source_end: usize,
    normalized_range: Option<TextByteRange>,
}

#[derive(Clone, Copy, Debug)]
struct TextByteRange {
    start: usize,
    end: usize,
}

#[derive(Clone, Copy, Debug)]
struct TextElementRange<'tree, 'input> {
    node: Node<'tree, 'input>,
    source_start: usize,
    flat_start: usize,
    flat_end: usize,
}

fn normalized_descendant_text(
    context: Node<'_, '_>,
    work_budget: &mut QueryWorkBudget,
) -> Result<(String, Vec<TextSourceSegment>), XmlError> {
    let mut text = String::new();
    let mut segments = Vec::new();
    let mut pending_space = false;
    for node in context.descendants().filter(Node::is_text) {
        work_budget.visit()?;
        let mut content_start = None;
        let mut content_end = None;
        if let Some(value) = node.text() {
            for character in value.chars() {
                if character.is_whitespace() {
                    pending_space = !text.is_empty();
                } else {
                    if pending_space {
                        text.push(' ');
                        pending_space = false;
                    }
                    if content_start.is_none() {
                        content_start = Some(text.len());
                    }
                    text.push(character);
                    content_end = Some(text.len());
                }
            }
        }
        let range = node.range();
        segments.push(TextSourceSegment {
            source_start: range.start,
            source_end: range.end,
            normalized_range: content_start
                .zip(content_end)
                .map(|(start, end)| TextByteRange { start, end }),
        });
    }
    Ok((text, segments))
}

pub(super) fn normalize_text(value: &str) -> String {
    let mut normalized = String::new();
    let mut pending_space = false;
    for character in value.chars() {
        if character.is_whitespace() {
            pending_space = !normalized.is_empty();
        } else {
            if pending_space {
                normalized.push(' ');
                pending_space = false;
            }
            normalized.push(character);
        }
    }
    normalized
}

fn compare_text_ranges(
    left: &TextElementRange<'_, '_>,
    right: &TextElementRange<'_, '_>,
) -> Ordering {
    left.flat_start
        .cmp(&right.flat_start)
        .then_with(|| right.flat_end.cmp(&left.flat_end))
        .then_with(|| left.source_start.cmp(&right.source_start))
}

pub(super) fn resolve_attribute_name<'a>(
    name: &'a str,
    bindings: &'a [NamespaceBinding],
) -> Result<(Option<String>, &'a str), XmlError> {
    let mut parts = name.split(':');
    let first = parts.next().ok_or(XmlError::InvalidQuery)?;
    let second = parts.next();
    if parts.next().is_some() || first.is_empty() || second.is_some_and(str::is_empty) {
        return Err(XmlError::InvalidQuery);
    }
    match second {
        Some(local_name) => {
            let namespace_uri = if first == "xml" {
                Some(roxmltree::NS_XML_URI.to_owned())
            } else {
                bindings
                    .iter()
                    .find(|binding| binding.prefix() == first)
                    .map(|binding| binding.namespace_uri().to_owned())
            }
            .ok_or(XmlError::UnboundNamespacePrefix)?;
            Ok((Some(namespace_uri), local_name))
        }
        None => Ok((None, first)),
    }
}
