use super::super::{HtmlParseError, append_normalized_text};
use super::{HtmlTree, node::HtmlNodeKind};

#[derive(Clone, Copy, Debug)]
pub struct TextSegment {
    pub(crate) start: usize,
    pub(crate) end: usize,
    pub(crate) owner: usize,
}

#[derive(Debug)]
pub(in crate::html) struct HtmlTextIndex {
    normalized: String,
    segments: Vec<TextSegment>,
    ranges: Vec<Option<(usize, usize)>>,
}
impl HtmlTextIndex {
    pub(in crate::html) fn normalized(&self) -> &str {
        &self.normalized
    }
    pub(in crate::html) fn segments(&self) -> &[TextSegment] {
        &self.segments
    }
    pub(in crate::html) fn range(&self, node: usize) -> Option<(usize, usize)> {
        self.ranges.get(node).copied().flatten()
    }
}

impl HtmlTree {
    pub(in crate::html) fn text_index(&self) -> Result<HtmlTextIndex, HtmlParseError> {
        let mut normalized = String::new();
        let mut segments = Vec::new();
        let mut ranges = vec![None; self.elements.len()];
        let mut previous_space = false;
        let mut element_order = Vec::new();
        let mut stack = Vec::new();
        self.push_children(0, None, &mut stack)?;
        while let Some((id, owner)) = stack.pop() {
            let node = self
                .nodes
                .get(id)
                .ok_or(HtmlParseError::InvalidParserTree)?;
            match &node.kind {
                HtmlNodeKind::Element { .. } if node.in_document => {
                    let owner = node
                        .element_index
                        .get()
                        .ok_or(HtmlParseError::InvalidParserTree)?;
                    element_order.push(owner);
                    self.push_children(id, Some(owner), &mut stack)?;
                }
                HtmlNodeKind::Text(text) => {
                    if let Some(owner) = owner {
                        let start = normalized.len();
                        append_normalized_text(text.as_ref(), &mut normalized, &mut previous_space);
                        let end = normalized.len();
                        if end > start {
                            segments.push(TextSegment { start, end, owner });
                            merge_range(
                                ranges
                                    .get_mut(owner)
                                    .ok_or(HtmlParseError::InvalidParserTree)?,
                                (start, end),
                            );
                        }
                    }
                }
                HtmlNodeKind::Document => self.push_children(id, owner, &mut stack)?,
                _ => {}
            }
        }
        for child in element_order.into_iter().rev() {
            let node = self
                .element(child)
                .ok_or(HtmlParseError::InvalidParserTree)?;
            if let (Some(parent), Some(range)) =
                (node.element_parent(), ranges.get(child).copied().flatten())
            {
                merge_range(
                    ranges
                        .get_mut(parent)
                        .ok_or(HtmlParseError::InvalidParserTree)?,
                    range,
                );
            }
        }
        Ok(HtmlTextIndex {
            normalized,
            segments,
            ranges,
        })
    }
    fn push_children(
        &self,
        parent: usize,
        owner: Option<usize>,
        stack: &mut Vec<(usize, Option<usize>)>,
    ) -> Result<(), HtmlParseError> {
        let mut child = self
            .nodes
            .get(parent)
            .ok_or(HtmlParseError::InvalidParserTree)?
            .last_child
            .get();
        while let Some(id) = child {
            let node = self
                .nodes
                .get(id)
                .ok_or(HtmlParseError::InvalidParserTree)?;
            stack.push((id, owner));
            child = node.previous.get();
        }
        Ok(())
    }
}

fn merge_range(target: &mut Option<(usize, usize)>, incoming: (usize, usize)) {
    match target {
        Some((start, end)) => {
            *start = (*start).min(incoming.0);
            *end = (*end).max(incoming.1);
        }
        None => *target = Some(incoming),
    }
}
