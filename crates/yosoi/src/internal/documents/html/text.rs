use std::collections::HashSet;

use crate::internal::documents::LocateFailure;

use super::tree::{HtmlNode, HtmlTree};
use super::{
    SelectorElement, SelectorVisitBudget, TextSegment, invalid_failure, push_limited_match,
};

pub trait ElementTree {
    type Element: SelectorElement;

    fn element_count(&self) -> usize;
    fn element(&self, index: usize) -> Option<&Self::Element>;
    fn parent(&self, index: usize) -> Option<usize>;
    fn children(&self, index: usize) -> Option<&[usize]>;

    fn is_descendant(
        &self,
        candidate: usize,
        ancestor: usize,
        budget: &mut SelectorVisitBudget,
    ) -> Result<bool, LocateFailure> {
        let mut current = self.parent(candidate);
        let mut traversed = 0_usize;
        while let Some(index) = current {
            budget.charge()?;
            if index == ancestor {
                return Ok(true);
            }
            traversed = match traversed.checked_add(1) {
                Some(value) if value <= self.element_count() => value,
                _ => return Ok(false),
            };
            current = self.parent(index);
        }
        Ok(false)
    }
}

impl ElementTree for HtmlTree {
    type Element = HtmlNode;

    fn element_count(&self) -> usize {
        self.element_count()
    }

    fn element(&self, index: usize) -> Option<&Self::Element> {
        self.element(index)
    }

    fn parent(&self, index: usize) -> Option<usize> {
        self.element(index).and_then(HtmlNode::element_parent)
    }

    fn children(&self, index: usize) -> Option<&[usize]> {
        self.element_children(index)
    }
}

pub fn select_tree_text<T: ElementTree + ?Sized>(
    elements: &T,
    normalized_text: &str,
    text_segments: &[TextSegment],
    expression: &str,
    scope: Option<usize>,
    maximum: u64,
    budget: &mut SelectorVisitBudget,
) -> Result<Vec<usize>, LocateFailure> {
    let mut contains = Vec::with_capacity(elements.element_count());
    for _ in 0..elements.element_count() {
        budget.charge()?;
        contains.push(false);
    }
    let mut last_owners = None;
    let mut start_segment = 0_usize;
    let mut end_segment = 0_usize;
    visit_substring_matches(normalized_text, expression, budget, |start, end, budget| {
        let start_owner = text_owner_at(text_segments, start, &mut start_segment, budget)?;
        let end_position = end.checked_sub(1);
        let end_owner = match end_position {
            Some(position) => text_owner_at(text_segments, position, &mut end_segment, budget)?,
            None => None,
        };
        let (Some(start_owner), Some(end_owner)) = (start_owner, end_owner) else {
            last_owners = None;
            return Ok(());
        };
        let owners = (start_owner, end_owner);
        if last_owners == Some(owners) {
            return Ok(());
        }
        last_owners = Some(owners);
        if let Some(common_ancestor) =
            lowest_common_ancestor(elements, start_owner, end_owner, budget)?
        {
            let Some(flag) = contains.get_mut(common_ancestor) else {
                return Err(invalid_failure("tree_text_element_invalid"));
            };
            *flag = true;
        }
        Ok(())
    })?;

    for index in (0..elements.element_count()).rev() {
        budget.charge()?;
        let Some(children) = elements.children(index) else {
            return Err(invalid_failure("tree_text_element_invalid"));
        };
        let mut child_match = false;
        for child in children {
            budget.charge()?;
            child_match |= contains.get(*child).copied().unwrap_or(false);
        }
        if child_match {
            let Some(flag) = contains.get_mut(index) else {
                return Err(invalid_failure("tree_text_element_invalid"));
            };
            *flag = true;
        }
    }

    let mut matches = Vec::new();
    for index in 0..elements.element_count() {
        budget.charge()?;
        if let Some(scope_index) = scope
            && !elements.is_descendant(index, scope_index, budget)?
        {
            continue;
        }
        if !contains.get(index).copied().unwrap_or(false) {
            continue;
        }
        let Some(children) = elements.children(index) else {
            return Err(invalid_failure("tree_text_element_invalid"));
        };
        let mut has_matching_child = false;
        for child in children {
            budget.charge()?;
            has_matching_child |= contains.get(*child).copied().unwrap_or(false);
        }
        if !has_matching_child {
            push_limited_match(&mut matches, index, maximum)?;
        }
    }
    Ok(matches)
}

fn text_owner_at(
    segments: &[TextSegment],
    position: usize,
    cursor: &mut usize,
    budget: &mut SelectorVisitBudget,
) -> Result<Option<usize>, LocateFailure> {
    budget.charge()?;
    while segments
        .get(*cursor)
        .is_some_and(|segment| segment.end <= position)
    {
        budget.charge()?;
        *cursor = cursor
            .checked_add(1)
            .ok_or_else(|| invalid_failure("tree_text_segment_cursor_overflow"))?;
    }
    Ok(segments
        .get(*cursor)
        .filter(|segment| segment.start <= position && position < segment.end)
        .map(|segment| segment.owner))
}

fn lowest_common_ancestor<T: ElementTree + ?Sized>(
    elements: &T,
    left: usize,
    right: usize,
    budget: &mut SelectorVisitBudget,
) -> Result<Option<usize>, LocateFailure> {
    let mut left_ancestors = HashSet::new();
    let mut current = Some(left);
    while let Some(index) = current {
        budget.charge()?;
        if !left_ancestors.insert(index) {
            return Ok(None);
        }
        current = elements.parent(index);
    }
    let mut right_current = Some(right);
    while let Some(index) = right_current {
        budget.charge()?;
        if left_ancestors.contains(&index) {
            return Ok(Some(index));
        }
        right_current = elements.parent(index);
    }
    Ok(None)
}

pub fn append_normalized_text(source: &str, target: &mut String, previous_was_space: &mut bool) {
    for character in source.chars() {
        if character.is_ascii_whitespace() {
            if !*previous_was_space {
                target.push(' ');
            }
            *previous_was_space = true;
        } else {
            target.push(character);
            *previous_was_space = false;
        }
    }
}

fn visit_substring_matches(
    haystack: &str,
    needle: &str,
    budget: &mut SelectorVisitBudget,
    mut visitor: impl FnMut(usize, usize, &mut SelectorVisitBudget) -> Result<(), LocateFailure>,
) -> Result<(), LocateFailure> {
    let pattern = needle.as_bytes();
    if pattern.is_empty() {
        return Err(invalid_failure("tree_text_query_empty"));
    }

    let mut prefix = Vec::with_capacity(pattern.len());
    for _ in pattern {
        budget.charge()?;
        prefix.push(0_usize);
    }
    let mut prefix_length = 0_usize;
    budget.charge()?;
    for (position, byte) in pattern.iter().copied().enumerate().skip(1) {
        budget.charge()?;
        while prefix_length > 0 && pattern.get(prefix_length).copied() != Some(byte) {
            let previous = prefix_length
                .checked_sub(1)
                .ok_or_else(|| invalid_failure("tree_text_query_invalid"))?;
            prefix_length = prefix
                .get(previous)
                .copied()
                .ok_or_else(|| invalid_failure("tree_text_query_invalid"))?;
        }
        if pattern.get(prefix_length).copied() == Some(byte) {
            prefix_length = prefix_length
                .checked_add(1)
                .ok_or_else(|| invalid_failure("tree_text_query_invalid"))?;
        }
        let Some(slot) = prefix.get_mut(position) else {
            return Err(invalid_failure("tree_text_query_invalid"));
        };
        *slot = prefix_length;
    }

    let mut matched = 0_usize;
    for (byte_offset, byte) in haystack.bytes().enumerate() {
        budget.charge()?;
        while matched > 0 && pattern.get(matched).copied() != Some(byte) {
            let previous = matched
                .checked_sub(1)
                .ok_or_else(|| invalid_failure("tree_text_query_invalid"))?;
            matched = prefix
                .get(previous)
                .copied()
                .ok_or_else(|| invalid_failure("tree_text_query_invalid"))?;
        }
        if pattern.get(matched).copied() == Some(byte) {
            matched = matched
                .checked_add(1)
                .ok_or_else(|| invalid_failure("tree_text_query_invalid"))?;
        }
        if matched == pattern.len() {
            let end = byte_offset
                .checked_add(1)
                .ok_or_else(|| invalid_failure("tree_text_query_invalid"))?;
            let start = end
                .checked_sub(pattern.len())
                .ok_or_else(|| invalid_failure("tree_text_query_invalid"))?;
            visitor(start, end, budget)?;
            let last = pattern
                .len()
                .checked_sub(1)
                .ok_or_else(|| invalid_failure("tree_text_query_invalid"))?;
            matched = prefix
                .get(last)
                .copied()
                .ok_or_else(|| invalid_failure("tree_text_query_invalid"))?;
        }
    }
    Ok(())
}
